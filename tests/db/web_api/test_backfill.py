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

WEB = ("snapshot_row", "ranking_run", "ranking_row", "ranking_profile", "ranking_factor")


def _web(added: dict[str, int]) -> dict[str, int]:
    return {table: added[table] for table in WEB}


def _count(engine: Engine, sql: str) -> int:
    with engine.connect() as conn:
        return int(conn.execute(text(sql)).scalar_one())


def _counts(engine: Engine) -> dict[str, Any]:
    return {table: _count(engine, f"SELECT count(*) FROM web.{table}") for table in WEB}


def test_fills_every_projection_from_the_tables(db_settings, engine):
    rc, _, _ = _patched_run(db_settings)
    assert rc == 0
    added = backfill_projections(engine)
    assert _web(added) == _counts(engine)
    assert added["snapshot_row"] == _count(
        engine, "SELECT count(*) FROM market_data.fundamental_snapshot"
    )
    assert added["ranking_run"] == _count(engine, "SELECT count(*) FROM scoring.scoring_run")
    # Nur Titel, die den Groessenfilter passiert haben; die anderen ergeben sich beim Lesen
    assert added["ranking_row"] == _count(
        engine, "SELECT count(*) FROM scoring.score_result WHERE passed_filter"
    )
    assert added["ranking_row"] < added["snapshot_row"]
    # Track G (G3): Profil und Parameter je Bewertungslauf, Perzentile je bewertetem Titel
    assert added["ranking_profile"] == added["ranking_run"]
    assert added["ranking_factor"] == _count(
        engine,
        "SELECT count(*) FROM (SELECT DISTINCT scoring_run_id, instrument_id "
        "FROM scoring.factor_score) f",
    )
    assert added["ranking_factor"] > 0


def test_a_second_call_adds_nothing(db_settings, engine):
    _patched_run(db_settings)
    first = backfill_projections(engine)
    assert backfill_projections(engine) == dict.fromkeys(first, 0)
    assert _counts(engine) == _web(first)


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


def test_profile_parameters_and_factor_ranks_come_along(db_settings, engine):
    _patched_run(db_settings)
    backfill_projections(engine)
    with engine.connect() as conn:
        profile = conn.execute(text("SELECT profile_name, params FROM web.ranking_profile")).one()
        ranks = conn.execute(
            text("SELECT ranks FROM web.ranking_factor WHERE symbol = 'AAA.DE'")
        ).scalar_one()
    assert profile.profile_name == "Standard"
    assert profile.params["value_trap_value_threshold"] == 0.7
    # Die Faktoren des Profils, fehlende Daten als null
    assert set(ranks) == set(profile.params["value_factors"]) | set(
        profile.params["quality_factors"]
    )


def test_migrate_fills_the_projections(db_settings, engine, db_url, monkeypatch):
    _patched_run(db_settings)
    monkeypatch.setenv("DATABASE_OWNER_URL", db_url)
    assert migrate.main() == 0
    assert _counts(engine)["ranking_run"] == 1


def test_copies_the_inputs_of_scoring(db_settings, engine):
    """P5.1a: Die Vorschau rechnet aus scoring.input_snapshot; aeltere Laeufe bekommen sie hier."""
    _patched_run(db_settings)
    with engine.begin() as conn:
        # Wie vor P5.1a: ohne Kopie (nur zum Test, die Tabelle ist sonst nur zum Anfuegen)
        conn.execute(text("ALTER TABLE scoring.input_snapshot DISABLE TRIGGER USER"))
        conn.execute(text("DELETE FROM scoring.input_snapshot"))
        conn.execute(text("ALTER TABLE scoring.input_snapshot ENABLE TRIGGER USER"))
    added = backfill_projections(engine)
    assert added["input_snapshot"] == _count(
        engine, "SELECT count(*) FROM market_data.fundamental_snapshot"
    )
    assert backfill_projections(engine)["input_snapshot"] == 0


def test_covered_titles_are_not_projected(db_settings, engine):
    """D2.2: Snapshots der Abdeckung (``role = 'coverage'``) gehoeren nicht in die Projektionen
    des Rankings; sie kommen erst mit der Einordnung (D4)."""
    from va_market_data.adapters.postgres.store import PostgresSnapshotStore
    from va_market_data.domain.fundamentals import Fundamentals, Identity, MarketData

    _patched_run(db_settings)
    fetch_run_id = _count(engine, "SELECT max(id) FROM market_data.fetch_run")
    store = PostgresSnapshotStore(engine, provider="yfinance", provider_version="test")
    covered = Fundamentals(identity=Identity("AAPL", "Apple Inc.", "-"), market=MarketData())
    store.record_covered(fetch_run_id, covered, "US0378331005")
    backfill_projections(engine)
    assert _count(engine, "SELECT count(*) FROM web.snapshot_row WHERE symbol = 'AAPL'") == 0
