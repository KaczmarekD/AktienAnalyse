"""Projektionen des web-api (P4.4): Run-Status und Ranking im Schema ``web``.

Jede Projektion bekommt die Session des Eventmanagers und schreibt in dessen Transaktion. Sie
liest nur das Event, keine Tabellen anderer Services.

- ``run_status``: eine Zeile je Run, mit jedem Event aktualisiert. Ein Fehlschlag gewinnt, wie
  im ``RunTracker``: Danach aendert nur ein weiterer Fehlschlag nichts mehr, und ein spaetes
  ``report.sent`` setzt den Status nicht zurueck.
- ``ranking_row``: je Bewertungslauf und Titel eine Zeile, nur zum Anfuegen. Auch ein Rescore
  (ohne Run) bekommt sein Ranking.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert

from va_contracts.events.v1 import (
    REASON_NO_DATA,
    REPORT_SENT,
    RUN_FAILED,
    RUN_REQUESTED,
    SCORING_RUN_COMPLETED,
    SNAPSHOT_COMPLETED,
)

from ..adapters.postgres.models import RankingRow, RunStatus

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from va_contracts import Envelope

    from ..events import EventManager

FAILURES = ("failed", "no_data")


def register(manager: EventManager) -> None:
    """Haengt alle Projektionen an den Eventmanager."""
    manager.projection(RUN_REQUESTED)(requested)
    manager.projection(SNAPSHOT_COMPLETED)(fetched)
    manager.projection(SCORING_RUN_COMPLETED)(scored)
    manager.projection(SCORING_RUN_COMPLETED)(ranking)
    manager.projection(REPORT_SENT)(reported)
    manager.projection(RUN_FAILED)(failed)


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
    # Ein Fehlschlag gewinnt; der erste bleibt stehen
    if row.status not in FAILURES:
        row.status = status
    for key, value in values.items():
        if key != "error" or row.error is None:
            setattr(row, key, value)
    row.last_event_type = env.type
    row.last_event_at = env.time
    row.updated_at = func.now()  # type: ignore[assignment]
