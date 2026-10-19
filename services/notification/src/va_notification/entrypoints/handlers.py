"""notification am Bus: Mail, Fehlermail und Healthcheck (docs/architecture/events.md).

- ``scoring.run.completed``: Report bauen und speichern; verschicken, ausser bei
  ``dry_run`` (dann Vorschau-Dateien) oder ``notify=False``; Healthcheck bei
  ``trigger=scheduled``; dann ``notification.report.sent``.
- ``screening.run.failed``: Healthcheck ``/fail`` bei ``scheduled``, Fehlermail ausser bei
  ``dry_run``, ``notify=False`` oder ``no_data`` (keine bewertbaren Daten: nur der Ping).
- Ein Rescore loest weder Mail noch Ping aus.

Protokoll-Schreibzugriffe (Versand, Ping) duerfen den Lauf nicht kippen und werden nur
geloggt, wenn sie scheitern.
"""

from __future__ import annotations

import logging
import traceback
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any

import pandas as pd

from va_contracts.events.v1 import (
    REASON_NO_DATA,
    REPORT_SENT,
    RUN_FAILED,
    SCORING_RUN_COMPLETED,
    ReportSentV1,
    RunFailedV1,
    UniverseMemberV1,
)
from va_platform.bus import follow_up

from ..domain.errors import ERROR_SUBJECT, error_mail_html
from ..domain.report import build_report

if TYPE_CHECKING:
    from pathlib import Path

    from va_contracts import Envelope
    from va_contracts.events.v1 import ScoringRunCompletedV1
    from va_platform.bus import EventBus

    from ..application.ports import Heartbeat, ReportSender, ReportStore
    from ..domain.report import ReportArtifacts

log = logging.getLogger(__name__)

CONSUMER = "notification"
SOURCE = "va/notification"
# Text des Pings, wenn es nichts zu bewerten gab
NO_DATA_MESSAGE = "no scoreable data"


@dataclass(frozen=True)
class NotificationConfig:
    top_n: int = 20
    bottom_n: int = 10
    version: str = ""
    recipient: str | None = None  # fuer das Versandprotokoll
    preview_dir: Path | None = None  # Dry-Run: Vorschau-HTML und CSV landen hier
    heartbeat_target: str | None = None  # nur der Host, nie die UUID (Versandprotokoll)
    clock: Callable[[], datetime] = field(default=datetime.now)


class NotificationHandler:
    def __init__(
        self,
        bus: EventBus,
        *,
        sender: ReportSender,
        heartbeat: Heartbeat,
        store: ReportStore,
        config: NotificationConfig,
    ) -> None:
        self._bus = bus
        self._sender = sender
        self._heartbeat = heartbeat
        self._store = store
        self._config = config

    def subscribe(self) -> None:
        self._bus.subscribe(SCORING_RUN_COMPLETED, CONSUMER, self.on_scoring_completed)
        self._bus.subscribe(RUN_FAILED, CONSUMER, self.on_run_failed)

    # --- Report ---------------------------------------------------------------

    def on_scoring_completed(self, env: Envelope[ScoringRunCompletedV1]) -> None:
        event = env.data
        if event.trigger == "rescore":
            return
        try:
            report = self._build(event)
            report_id = self._store.record_report(event.run_id, event.scoring_run_id, report)
            deliver = event.options.notify and not event.options.dry_run
            if event.options.dry_run:
                self._write_preview(report)
            if deliver:
                self._send_report(event.run_id, report_id, report)
        except Exception as e:
            log.exception("Report nicht verschickt")
            failed = RunFailedV1(
                run_id=event.run_id,
                trigger=event.trigger,
                options=event.options,
                stage="notification",
                reason=str(e) or type(e).__name__,
                detail=traceback.format_exc(),
            )
            self._bus.publish(follow_up(env, RUN_FAILED, failed, source=SOURCE))
            return

        if deliver and event.trigger == "scheduled":
            self._ping(event.run_id, True, f"scored {report.scored}/{report.universe_size}")
        if event.run_id is None:  # nur ein Rescore hat keinen Run, der kam oben nicht durch
            return
        sent = ReportSentV1(
            run_id=event.run_id,
            report_id=report_id,
            subject=report.subject,
            dry_run=event.options.dry_run,
        )
        self._bus.publish(follow_up(env, REPORT_SENT, sent, source=SOURCE))

    def _build(self, event: ScoringRunCompletedV1) -> ReportArtifacts:
        cfg = self._config
        frame = pd.DataFrame([row.to_flat() for row in event.ranking])
        return build_report(
            frame,
            top_n=cfg.top_n,
            bottom_n=cfg.bottom_n,
            value_weight=event.value_weight,
            quality_weight=event.quality_weight,
            version=cfg.version,
            universe_size=event.universe.size,
            universe_source=event.universe.source,
            universe_as_of=event.universe.as_of,
            universe_added=[_label(m) for m in event.universe.added],
            universe_removed=[_label(m) for m in event.universe.removed],
            now=cfg.clock(),
        )

    def _send_report(self, run_id: int | None, report_id: int, report: ReportArtifacts) -> None:
        delivery: dict[str, Any] = {
            "run_id": run_id,
            "report_id": report_id,
            "channel": "mail",
            "kind": "report",
            "recipient": self._config.recipient,
            "subject": report.subject,
        }
        try:
            self._sender.send(
                report.subject,
                report.html,
                attachment=(report.csv_filename, report.csv_bytes),
            )
        except Exception as e:
            self._record(**delivery, success=False, error=str(e))
            raise
        self._record(**delivery, success=True)

    def _write_preview(self, report: ReportArtifacts) -> None:
        target = self._config.preview_dir
        if target is None:
            return
        target.mkdir(parents=True, exist_ok=True)
        preview = target / "preview_latest.html"
        preview.write_text(report.html, encoding="utf-8")
        # Praefix: Der Altdaten-Import greift nur value_ranking_*.csv auf
        csv_path = target / f"preview_{report.csv_filename}"
        csv_path.write_bytes(report.csv_bytes)
        log.info("DRY-RUN: HTML-Preview -> %s", preview)
        log.info("DRY-RUN: CSV -> %s", csv_path)
        log.info("DRY-RUN: Subject waere -> %s", report.subject)

    # --- Fehlschlag -------------------------------------------------------------

    def on_run_failed(self, env: Envelope[RunFailedV1]) -> None:
        event = env.data
        if event.trigger == "rescore":
            return
        no_data = event.reason == REASON_NO_DATA
        if event.trigger == "scheduled":
            self._ping(event.run_id, False, NO_DATA_MESSAGE if no_data else event.reason)
        if not no_data and event.options.notify and not event.options.dry_run:
            self._send_error_mail(event.run_id, event.detail or event.reason)

    def _send_error_mail(self, run_id: int | None, trace: str) -> None:
        error = _send_error_mail(self._sender, trace)
        self._record(
            run_id=run_id,
            report_id=None,
            channel="mail",
            kind="error",
            recipient=self._config.recipient,
            subject=ERROR_SUBJECT,
            success=error is None,
            error=error,
        )

    # --- Hilfen -------------------------------------------------------------------

    def _ping(self, run_id: int | None, success: bool, message: str) -> None:
        result = self._heartbeat.ping(success, message)
        if result is None:
            return  # kein Healthcheck konfiguriert
        self._record(
            run_id=run_id,
            report_id=None,
            channel="healthcheck",
            kind="ping_ok" if success else "ping_fail",
            recipient=self._config.heartbeat_target,
            subject=None,
            success=result,
            error=None if result else "Ping fehlgeschlagen",
        )

    def _record(self, **delivery: Any) -> None:
        try:
            self._store.record_delivery(**delivery)
        except Exception:
            log.warning("Versandprotokoll konnte nicht gespeichert werden", exc_info=True)


def notify_failure_without_run(
    sender: ReportSender, heartbeat: Heartbeat, message: str, *, detail: str, dry_run: bool
) -> None:
    """Kein Run (z. B. Datenbank nicht erreichbar): melden, aber nichts speichern."""
    heartbeat.ping(False, message)
    if not dry_run:
        _send_error_mail(sender, detail)


def _send_error_mail(sender: ReportSender, trace: str) -> str | None:
    """Verschickt die Fehlermail. Rueckgabe: der Fehler, falls auch sie scheitert."""
    try:
        sender.send(ERROR_SUBJECT, error_mail_html(trace), attachment=None)
    except Exception as inner:
        log.error("Auch Fehler-Mail fehlgeschlagen: %s", inner)
        return str(inner)
    return None


def _label(member: UniverseMemberV1) -> str:
    return f"{member.name} ({member.symbol}, {member.index})"
