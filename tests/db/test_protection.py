"""Die Datenbank erzwingt "niemals loeschen" - unabhaengig vom Anwendungscode."""

from __future__ import annotations

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError, ProgrammingError

from src.db.engine import session_scope
from src.db.repositories.market_data import MarketDataRepository
from src.db.repositories.runs import RunRepository
from src.db.repositories.scoring import ScoreRow, ScoringRepository

APP_SCHEMAS = ("batch", "market_data", "scoring", "reporting")


def _start_run(engine: Engine) -> int:
    with session_scope(engine) as s:
        return RunRepository(s).write_run_start(
            kind="batch",
            app_version="test",
            dry_run=True,
            force_refresh=False,
            universe_mode="DAX_MDAX",
            settings={},
        )


def _exec(engine: Engine, sql: str, **params: object) -> None:
    with engine.begin() as conn:
        conn.execute(text(sql), params)


class TestTriggers:
    def test_every_table_has_delete_and_truncate_guard(self, engine):
        with engine.connect() as conn:
            tables = conn.execute(
                text(
                    "SELECT table_schema || '.' || table_name FROM information_schema.tables "
                    "WHERE table_schema = ANY(:s) AND table_type = 'BASE TABLE'"
                ),
                {"s": list(APP_SCHEMAS)},
            ).scalars()
            tables = sorted(tables)
            assert len(tables) >= 12
            for table in tables:
                guards = conn.execute(
                    text(
                        "SELECT t.tgname FROM pg_trigger t "
                        "WHERE t.tgrelid = CAST(:t AS regclass) AND NOT t.tgisinternal"
                    ),
                    {"t": table},
                ).scalars()
                names = set(guards)
                assert "va_no_delete" in names, f"{table} ohne DELETE-Schutz"
                assert "va_no_truncate" in names, f"{table} ohne TRUNCATE-Schutz"

    def test_delete_is_rejected(self, engine):
        run_id = _start_run(engine)
        with pytest.raises(DBAPIError, match="verboten"):
            _exec(engine, "DELETE FROM batch.run WHERE id = :id", id=run_id)

    def test_truncate_is_rejected(self, engine):
        _start_run(engine)
        with pytest.raises(DBAPIError, match="verboten"):
            _exec(engine, "TRUNCATE batch.run CASCADE")

    def test_immutable_fact_table_rejects_update(self, engine):
        run_id = _start_run(engine)
        with session_scope(engine) as s:
            ids = MarketDataRepository(s).get_or_create_instruments(["SAP.DE"])
            scoring_run_id = ScoringRepository(s).write_scoring_run(
                fetch_run_id=None, config={}, app_version="test", origin="live"
            )
            ScoringRepository(s).write_score_results(
                scoring_run_id,
                [ScoreRow(ids["SAP.DE"], True, 0.5, 0.5, 0.5, False, 1)],
            )
        assert run_id
        with pytest.raises(DBAPIError, match="verboten"):
            _exec(engine, "UPDATE scoring.score_result SET composite_score = 0.9")

    def test_running_run_may_be_finished_once(self, engine):
        run_id = _start_run(engine)
        with session_scope(engine) as s:
            RunRepository(s).write_run_finish(run_id, status="success", exit_code=0)
        with pytest.raises(DBAPIError, match="abgeschlossen"):
            _exec(engine, "UPDATE batch.run SET status = 'failed' WHERE id = :id", id=run_id)

    def test_instrument_symbol_is_immutable_isin_only_backfilled(self, engine):
        with session_scope(engine) as s:
            MarketDataRepository(s).get_or_create_instruments(["SAP.DE"])
        _exec(engine, "UPDATE market_data.instrument SET isin = 'DE0007164600'")
        with pytest.raises(DBAPIError, match="verboten"):
            _exec(engine, "UPDATE market_data.instrument SET isin = 'XX0000000000'")
        with pytest.raises(DBAPIError, match="verboten"):
            _exec(engine, "UPDATE market_data.instrument SET symbol = 'SAP2.DE'")


class TestRoles:
    def test_app_role_can_write_and_read(self, app_engine):
        run_id = _start_run(app_engine)
        with session_scope(app_engine) as s:
            RunRepository(s).write_run_finish(run_id, status="success", exit_code=0)
            assert RunRepository(s).get_run(run_id) is not None

    def test_app_role_has_no_delete_privilege(self, engine, app_engine):
        _start_run(engine)
        with pytest.raises(ProgrammingError, match="permission denied"):
            _exec(app_engine, "DELETE FROM batch.run")
        with pytest.raises(ProgrammingError, match="permission denied"):
            _exec(app_engine, "TRUNCATE batch.run")

    def test_read_role_is_read_only(self, engine, read_engine):
        _start_run(engine)
        with read_engine.connect() as conn:
            assert conn.execute(text("SELECT count(*) FROM batch.run")).scalar() == 1
        with pytest.raises(ProgrammingError, match="permission denied"):
            _exec(
                read_engine,
                "INSERT INTO batch.run_log (run_id, ts, level, logger, message) "
                "VALUES (1, now(), 'INFO', 'x', 'y')",
            )
