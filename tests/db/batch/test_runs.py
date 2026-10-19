"""get/write-Zugriffe auf das Schema batch (Ablaufsteuerung, bleibt bis P1.8 in src)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from src.db.log_handler import LogEntry
from src.db.repositories.runs import RunRepository
from va_platform.db import session_scope

T0 = datetime(2026, 10, 3, 5, 30, tzinfo=UTC)


class TestRuns:
    def test_lifecycle_and_queries(self, engine):
        with session_scope(engine) as s:
            repo = RunRepository(s)
            first = repo.write_run_start(
                kind="batch",
                app_version="0.3.0",
                dry_run=False,
                force_refresh=False,
                universe_mode="DAX_MDAX",
                settings={"top_n": 20},
                started_at=T0,
            )
            repo.write_run_finish(
                first,
                status="success",
                exit_code=0,
                fetch_run_id=3,
                scored_count=90,
                universe_size=90,
                failed_count=0,
            )
            second = repo.write_run_start(
                kind="batch",
                app_version="0.3.0",
                dry_run=True,
                force_refresh=False,
                universe_mode="DAX_MDAX",
                settings={},
                started_at=T0 + timedelta(days=7),
            )
        with session_scope(engine) as s:
            repo = RunRepository(s)
            run = repo.get_run(first)
            assert run is not None
            assert (run.status, run.exit_code, run.fetch_run_id) == ("success", 0, 3)
            assert run.finished_at is not None
            assert [r.id for r in repo.get_runs()] == [first, second]
            assert [r.id for r in repo.get_runs(since=T0 + timedelta(days=1))] == [second]
            latest = repo.get_latest_run(status="success")
            assert latest is not None
            assert latest.id == first

    def test_logs(self, session):
        repo = RunRepository(session)
        rid = repo.write_run_start(
            kind="batch",
            app_version="x",
            dry_run=True,
            force_refresh=False,
            universe_mode=None,
            settings=None,
        )
        written = repo.write_logs(
            rid,
            [
                LogEntry(T0, "INFO", "main", "Start"),
                LogEntry(T0 + timedelta(seconds=1), "WARNING", "data_fetcher", "yfinance zickt"),
            ],
        )
        session.commit()
        assert written == 2
        assert [(e.level, e.message) for e in repo.get_logs(rid)] == [
            ("INFO", "Start"),
            ("WARNING", "yfinance zickt"),
        ]

    def test_import_file_registry(self, session):
        repo = RunRepository(session)
        assert repo.get_import_file("abc") is None
        repo.write_import_file(
            file_name="value_ranking_20260801.csv", sha256="abc", kind="ranking_csv", run_id=None
        )
        session.commit()
        entry = repo.get_import_file("abc")
        assert entry is not None
        assert entry.file_name == "value_ranking_20260801.csv"
