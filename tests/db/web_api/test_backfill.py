"""Projektionen aus den Tabellen nachfuellen (P4.9): ``src.db.backfill``.

Der Stream haelt Events nur 30 Tage, die Historie liegt in den Tabellen. Das Nachfuellen laeuft
mit der Owner-Rolle nach jeder Migration (``python -m src.db.migrate``) und fuegt nur an, was
fehlt: Ein zweiter Aufruf aendert nichts.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Engine, text

from src.db import migrate
from src.db.backfill import backfill_projections
from tests.db.test_pipeline_db import _patched_run


def _count(engine: Engine, sql: str) -> int:
    with engine.connect() as conn:
        return int(conn.execute(text(sql)).scalar_one())


def _counts(engine: Engine) -> dict[str, Any]:
    return {
        table: _count(engine, f"SELECT count(*) FROM web.{table}")
        for table in ("snapshot_row", "ranking_run", "ranking_row")
    }


def test_fills_every_projection_from_the_tables(db_settings, engine):
    rc, _, _ = _patched_run(db_settings)
    assert rc == 0
    added = backfill_projections(engine)
    assert added == _counts(engine)
    assert added["snapshot_row"] == _count(
        engine, "SELECT count(*) FROM market_data.fundamental_snapshot"
    )
    assert added["ranking_run"] == _count(engine, "SELECT count(*) FROM scoring.scoring_run")
    # Nur Titel, die den Groessenfilter passiert haben; die anderen ergeben sich beim Lesen
    assert added["ranking_row"] == _count(
        engine, "SELECT count(*) FROM scoring.score_result WHERE passed_filter"
    )
    assert added["ranking_row"] < added["snapshot_row"]


def test_a_second_call_adds_nothing(db_settings, engine):
    _patched_run(db_settings)
    first = backfill_projections(engine)
    assert backfill_projections(engine) == dict.fromkeys(first, 0)
    assert _counts(engine) == first


def test_isin_and_fetch_day_come_along(db_settings, engine):
    _patched_run(db_settings)
    backfill_projections(engine)
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT isin, fetch_ok, fetched_on FROM web.snapshot_row WHERE symbol = 'AAA.DE'")
        ).one()
        origin = conn.execute(text("SELECT origin FROM web.ranking_run")).scalar_one()
    assert (row.isin, row.fetch_ok) == ("DE000AAA0001", True)
    assert row.fetched_on is not None
    assert origin == "live"


def test_migrate_fills_the_projections(db_settings, engine, db_url, monkeypatch):
    _patched_run(db_settings)
    monkeypatch.setenv("DATABASE_OWNER_URL", db_url)
    assert migrate.main() == 0
    assert _counts(engine)["ranking_run"] == 1
