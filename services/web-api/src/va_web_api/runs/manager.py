"""Run-Verwaltung des web-api (P4.7): Runs anlegen, ueberwachen, Events ueber die Outbox.

- ``start``: ein manueller Run aus dem UI. Laeuft noch einer, gibt es ``RunActive``: Zwei Abrufe
  zugleich verdoppelten die Last auf Yahoo.
- ``schedule``: ein geplanter Run fuer einen Cron-Termin. Derselbe Termin ergibt nur einen Run.
- ``check``: der Watchdog. Haengt ein Run laenger als die Grenze seiner Stufe, meldet er
  ``screening.run.failed`` (``stage=watchdog``, ``reason=timeout``) und schliesst den Run ab.
- ``tick``: ein Takt der Hintergrund-Aufgabe: Scheduler, Watchdog, dann die Outbox leeren.

Jeder Run entsteht in einer Transaktion: ``batch.run``, ``web.run_request`` und
``screening.run.requested`` in ``web.outbox``. Die Outbox leert ``publish_pending`` an NATS; ist
NATS gerade weg, holt der naechste Takt das nach. Eine Sperre in der Datenbank
(``pg_advisory_xact_lock``) haelt Start, Scheduler und Watchdog auseinander, auch ueber mehrere
Instanzen. Die Uhr ist ein Parameter, die Tests steuern sie.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, insert, select

from va_contracts import new_envelope, parse_envelope
from va_contracts.events.v1 import (
    RUN_FAILED,
    RUN_REQUESTED,
    RunFailedV1,
    RunOptionsV1,
    ScreeningRunRequestedV1,
)
from va_platform import tracing
from va_platform.db import session_scope
from va_platform.messaging import Outbox, drain_outbox

from .. import projections
from ..adapters.postgres.batch_run import BATCH_RUN
from ..adapters.postgres.models import RunRequest, RunStatus, WebOutbox
from ..ports import RunActive

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy import Engine
    from sqlalchemy.orm import Session

    from va_contracts import Envelope
    from va_contracts.events.v1 import RunTrigger

    from .schedule import Schedule

    type Publish = Callable[[Envelope[Any]], None]

log = logging.getLogger(__name__)

SOURCE = "va/web-api"
# Schluessel der Sperre fuer Start, Scheduler und Watchdog ("VARU", beliebig, aber fest)
LOCK_KEY = 0x56415255
TIMEOUT = "timeout"


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class WatchdogLimits:
    """So lange darf eine Stufe dauern (events.md): Abruf ab der Anfrage, sonst ab dem Event davor."""

    fetch: timedelta = timedelta(minutes=45)
    scoring: timedelta = timedelta(minutes=5)
    report: timedelta = timedelta(minutes=5)

    @property
    def total(self) -> timedelta:
        return self.fetch + self.scoring + self.report


class RunManager:
    """``engine`` schreibt mit der Rolle ``va_web``. ``publisher`` liefert die Sende-Funktion des
    Busses, solange keiner da ist ``None``; dann bleiben die Events in der Outbox."""

    def __init__(
        self,
        engine: Engine,
        *,
        version: str,
        limits: WatchdogLimits | None = None,
        clock: Callable[[], datetime] = _utcnow,
        publisher: Callable[[], Publish | None] = lambda: None,
    ) -> None:
        self._engine = engine
        self._version = version
        self._limits = limits or WatchdogLimits()
        self._clock = clock
        self._publisher = publisher
        self._outbox = Outbox(WebOutbox)

    def start(self, options: RunOptionsV1) -> int:
        """Ein manueller Run; ``RunActive``, solange ein anderer laeuft."""
        with session_scope(self._engine) as session:
            _lock(session)
            active = self._active(session)
            if active is not None:
                raise RunActive(active)
            run_id = self._create(session, "manual", options)
        log.info("Run #%s aus dem UI angelegt", run_id)
        self._flush()
        return run_id

    def schedule(self, slot: datetime) -> int | None:
        """Ein geplanter Run fuer ``slot``; ``None``, wenn es fuer den Termin schon einen gibt.

        Laeuft gerade ein manueller Run, entsteht der geplante trotzdem: Ein haengender Run soll
        den Wochenlauf nicht verhindern, der Watchdog raeumt ihn ab.
        """
        with session_scope(self._engine) as session:
            _lock(session)
            taken = session.scalar(select(RunRequest.run_id).where(RunRequest.slot == slot))
            if taken is not None:
                return None
            run_id = self._create(session, "scheduled", RunOptionsV1(), slot=slot)
        log.info("Geplanter Run #%s fuer %s angelegt", run_id, slot.isoformat())
        return run_id

    def check(self) -> list[int]:
        """Watchdog: meldet haengende Runs des web-api als gescheitert, jeden einmal."""
        now = self._clock()
        failed: list[int] = []
        with session_scope(self._engine) as session:
            _lock(session)
            open_runs = session.execute(
                select(RunRequest, RunStatus.status, RunStatus.last_event_at)
                .join(BATCH_RUN, BATCH_RUN.c.id == RunRequest.run_id)
                .outerjoin(RunStatus, RunStatus.run_id == RunRequest.run_id)
                .where(BATCH_RUN.c.finished_at.is_(None))
                .order_by(RunRequest.run_id)
            ).all()
            for request, status, last_event_at in open_runs:
                overdue = self._overdue(request, status, last_event_at, now)
                if overdue is not None:
                    self._fail(session, request, overdue, now)
                    failed.append(request.run_id)
        for run_id in failed:
            log.warning("Watchdog: Run #%s haengt und gilt als gescheitert", run_id)
        return failed

    def tick(self, schedule: Schedule | None = None) -> None:
        """Ein Takt: faelligen Termin anlegen, Watchdog, offene Events senden."""
        if schedule is not None:
            slot = schedule.due(self._clock())
            if slot is not None:
                self.schedule(slot)
        self.check()
        self._flush()

    def publish_pending(self, publish: Publish) -> int:
        """Sendet die offenen Events der Outbox; gibt die Anzahl zurueck."""
        return drain_outbox(
            self._engine, self._outbox, lambda message: publish(parse_envelope(message.payload))
        )

    def _flush(self) -> None:
        publish = self._publisher()
        if publish is None:
            return
        try:
            self.publish_pending(publish)
        except Exception:
            log.warning("Outbox nicht geleert, der naechste Takt versucht es erneut", exc_info=True)

    def _active(self, session: Session) -> int | None:
        """Ein laufender Run, egal von wem. Ein Run des Batches, der nie abgeschlossen wurde,
        zaehlt nach der Summe der Grenzen nicht mehr (Absturz)."""
        cutoff = self._clock() - self._limits.total
        return session.scalar(
            select(BATCH_RUN.c.id)
            .where(
                BATCH_RUN.c.kind == "batch",
                BATCH_RUN.c.finished_at.is_(None),
                BATCH_RUN.c.started_at > cutoff,
            )
            .order_by(BATCH_RUN.c.id.desc())
            .limit(1)
        )

    def _create(
        self,
        session: Session,
        trigger: RunTrigger,
        options: RunOptionsV1,
        *,
        slot: datetime | None = None,
    ) -> int:
        now = self._clock()
        run_id: int = session.execute(
            insert(BATCH_RUN)
            .values(
                kind="batch",
                status="running",
                started_at=now,
                app_version=self._version,
                dry_run=options.dry_run,
                force_refresh=options.force_refresh,
            )
            .returning(BATCH_RUN.c.id)
        ).scalar_one()
        session.add(
            RunRequest(
                run_id=run_id,
                trigger=trigger,
                slot=slot,
                force_refresh=options.force_refresh,
                dry_run=options.dry_run,
                notify=options.notify,
                requested_at=now,
            )
        )
        request = ScreeningRunRequestedV1(run_id=run_id, trigger=trigger, options=options)
        with tracing.run_span(run_id) as span:  # P5.5: ein Trace je Run, er beginnt hier
            span.set_attribute("va.trigger", trigger)
            self._outbox.add(
                session,
                new_envelope(RUN_REQUESTED, request, source=SOURCE, correlationid=str(run_id)),
            )
        return run_id

    def _overdue(
        self,
        request: RunRequest,
        status: str | None,
        last_event_at: datetime | None,
        now: datetime,
    ) -> str | None:
        """Beschreibung der haengenden Stufe, oder ``None``, wenn der Run in der Zeit ist."""
        if status in (None, "requested"):
            label, since, limit = "Abruf", request.requested_at, self._limits.fetch
        elif status == "fetched":
            label, since, limit = "Bewertung", last_event_at, self._limits.scoring
        elif status == "scored":
            label, since, limit = "Mail", last_event_at, self._limits.report
        else:
            return None  # Ergebnis da: schliesst die Projektion ab
        assert since is not None
        waited = now - since
        if waited <= limit:
            return None
        return f"{label} ohne Ergebnis seit {_minutes(waited)} min (Grenze {_minutes(limit)} min)"

    def _fail(self, session: Session, request: RunRequest, detail: str, now: datetime) -> None:
        """Fehlschlag in die Outbox und gleich in die Projektionen: Der naechste Takt sieht den
        Run nicht mehr als offen, auch wenn das Event noch nicht zurueck ist."""
        options = RunOptionsV1(
            force_refresh=request.force_refresh, dry_run=request.dry_run, notify=request.notify
        )
        failure = RunFailedV1(
            run_id=request.run_id,
            trigger=request.trigger,  # type: ignore[arg-type] - Check in der Datenbank
            options=options,
            stage="watchdog",
            reason=TIMEOUT,
            detail=detail,
        )
        envelope = new_envelope(
            RUN_FAILED, failure, source=SOURCE, correlationid=str(request.run_id)
        ).model_copy(update={"time": now})
        self._outbox.add(session, envelope)
        projections.failed(session, envelope)
        projections.close_run(session, envelope)


def _lock(session: Session) -> None:
    session.execute(select(func.pg_advisory_xact_lock(LOCK_KEY)))


def _minutes(span: timedelta) -> int:
    return int(span.total_seconds() // 60)
