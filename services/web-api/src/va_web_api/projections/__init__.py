"""Projektionen des web-api (P4.4): Run-Status und Ranking im Schema ``web``.

Jede Projektion bekommt die Session des Eventmanagers und schreibt in dessen Transaktion. Sie
liest nur das Event, keine Tabellen anderer Services.

- ``run_status``: eine Zeile je Run, mit jedem Event aktualisiert. Ein Fehlschlag gewinnt, wie
  im ``RunTracker``: Danach aendert nur ein weiterer Fehlschlag nichts mehr, und ein spaetes
  ``report.sent`` setzt den Status nicht zurueck.
- ``ranking_row``: je Bewertungslauf und Titel eine Zeile, nur zum Anfuegen. Auch ein Rescore
  (ohne Run) bekommt sein Ranking.
- ``batch.run`` (P4.7): Runs, die das web-api angelegt hat (``web.run_request``), schliesst
  ``close_run`` beim ersten Ergebnis ab. Die Regeln sind die des ``RunTracker``. Runs des Batches
  schliesst der Batch selbst ab.

Die Stufe in ``run_status`` geht nie zurueck: Die Handler des ``NatsBus`` laufen parallel, ein
spaetes ``requested`` darf ein ``fetched`` nicht ueberschreiben.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import func, update
from sqlalchemy.dialects.postgresql import insert

from va_contracts.events.v1 import (
    REASON_NO_DATA,
    REPORT_SENT,
    RUN_FAILED,
    RUN_REQUESTED,
    SCORING_RUN_COMPLETED,
    SNAPSHOT_COMPLETED,
)

from ..adapters.postgres.batch_run import BATCH_RUN
from ..adapters.postgres.models import RankingRow, RunRequest, RunStatus

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from va_contracts import Envelope

    from ..events import EventManager

FAILURES = ("failed", "no_data")
STAGES = ("requested", "fetched", "scored", "reported")  # Reihenfolge der Kette

# Exit-Codes wie im Batch (src/run_tracker.py)
EXIT_OK = 0
EXIT_FAILED = 1
EXIT_NO_DATA = 3


def register(manager: EventManager) -> None:
    """Haengt alle Projektionen an den Eventmanager."""
    manager.projection(RUN_REQUESTED)(requested)
    manager.projection(SNAPSHOT_COMPLETED)(fetched)
    manager.projection(SCORING_RUN_COMPLETED)(scored)
    manager.projection(SCORING_RUN_COMPLETED)(ranking)
    manager.projection(REPORT_SENT)(reported)
    manager.projection(RUN_FAILED)(failed)
    # Nach run_status: close_run liest die Zaehler, die die Projektionen davor gesetzt haben
    manager.projection(REPORT_SENT)(close_run)
    manager.projection(RUN_FAILED)(close_run)


def requested(session: Session, env: Envelope[Any]) -> None:
    data = env.data
    _update_run(session, env, data.run_id, "requested", trigger=data.trigger)


def fetched(session: Session, env: Envelope[Any]) -> None:
    data = env.data
    _update_run(
        session,
        env,
        data.run_id,
        "fetched",
        trigger=data.trigger,
        fetch_run_id=data.fetch_run_id,
        universe_size=data.universe.size,
    )


def scored(session: Session, env: Envelope[Any]) -> None:
    data = env.data
    _update_run(
        session,
        env,
        data.run_id,
        "scored",
        trigger=data.trigger,
        fetch_run_id=data.fetch_run_id,
        scoring_run_id=data.scoring_run_id,
        universe_size=data.universe.size,
        scored_count=sum(row.composite_score is not None for row in data.ranking),
    )


def ranking(session: Session, env: Envelope[Any]) -> None:
    data = env.data
    rows = [
        {
            "scoring_run_id": data.scoring_run_id,
            "symbol": row.fundamentals.identity.symbol,
            "run_id": data.run_id,
            "as_of": data.as_of,
            "name": row.fundamentals.identity.name,
            "index": row.fundamentals.identity.index,
            "rank_overall": row.rank_overall,
            "composite_score": row.composite_score,
            "value_score": row.value_score,
            "quality_score": row.quality_score,
            "value_trap": row.value_trap_flag,
        }
        for row in data.ranking
    ]
    # Schon vorhanden (etwa nach einem Neuaufbau der Inbox): nichts ueberschreiben
    session.execute(insert(RankingRow).values(rows).on_conflict_do_nothing())


def reported(session: Session, env: Envelope[Any]) -> None:
    data = env.data
    _update_run(session, env, data.run_id, "reported", report_id=data.report_id)


def failed(session: Session, env: Envelope[Any]) -> None:
    data = env.data
    status = "no_data" if data.reason == REASON_NO_DATA else "failed"
    _update_run(
        session,
        env,
        data.run_id,
        status,
        trigger=data.trigger,
        scoring_run_id=data.scoring_run_id,
        error=None if status == "no_data" else data.reason,
    )


def _update_run(
    session: Session, env: Envelope[Any], run_id: int | None, status: str, **fields: Any
) -> None:
    if run_id is None:
        return  # Rescore: kein Run
    values = {key: value for key, value in fields.items() if value is not None}
    row = session.get(RunStatus, run_id, with_for_update=True)
    if row is None:
        session.add(
            RunStatus(
                run_id=run_id,
                status=status,
                last_event_type=env.type,
                last_event_at=env.time,
                **values,
            )
        )
        return
    if _advances(row.status, status):
        row.status = status
    for key, value in values.items():
        if key != "error" or row.error is None:
            setattr(row, key, value)
    # Nur vorwaerts in der Zeit: Der Watchdog misst die Dauer einer Stufe ab last_event_at
    if env.time >= row.last_event_at:
        row.last_event_type = env.type
        row.last_event_at = env.time
    row.updated_at = func.now()  # type: ignore[assignment]


def _advances(current: str, new: str) -> bool:
    """Ein Fehlschlag gewinnt, der erste bleibt stehen; sonst geht die Stufe nur vorwaerts."""
    if current in FAILURES:
        return False
    return new in FAILURES or STAGES.index(new) >= STAGES.index(current)


def close_run(session: Session, env: Envelope[Any]) -> None:
    """Schliesst ``batch.run`` beim ersten Ergebnis ab, nur fuer Runs des web-api (P4.7).

    Laeuft nach ``reported`` bzw. ``failed`` in derselben Transaktion und nimmt Abruf, Bewertung
    und Zaehler aus ``run_status``. Ist der Run schon abgeschlossen, aendert sich nichts.
    """
    data = env.data
    run_id = data.run_id
    session.flush()  # eine gerade angelegte Zeile in run_status sichtbar machen
    if run_id is None or session.get(RunRequest, run_id) is None:
        return  # Rescore oder Run des Batches
    row = session.get(RunStatus, run_id)
    assert row is not None  # gerade von reported/failed geschrieben
    universe = row.universe_size
    if env.type == REPORT_SENT.type:
        scored = row.scored_count or 0
        missing = max(0, (universe or 0) - scored)
        finish = {
            "status": "success" if missing == 0 else "partial",
            "exit_code": EXIT_OK,
            "report_id": data.report_id,
            "scored_count": scored,
            "failed_count": missing,
        }
    elif data.reason == REASON_NO_DATA:
        finish = {
            "status": "no_data",
            "exit_code": EXIT_NO_DATA,
            "scored_count": 0,
            "failed_count": universe,
        }
    else:
        finish = {"status": "failed", "exit_code": EXIT_FAILED, "error": data.detail or data.reason}
    session.execute(
        update(BATCH_RUN)
        .where(BATCH_RUN.c.id == run_id, BATCH_RUN.c.finished_at.is_(None))
        .values(
            finished_at=env.time,
            fetch_run_id=row.fetch_run_id,
            scoring_run_id=row.scoring_run_id,
            universe_size=universe,
            **finish,
        )
    )
