"""get/write-Zugriffe auf die Schemas scoring, reporting und batch."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from src.db.engine import session_scope
from src.db.log_handler import LogEntry
from src.db.repositories.market_data import MarketDataRepository
from src.db.repositories.reporting import ReportingRepository
from src.db.repositories.runs import RunRepository
from src.db.repositories.scoring import FactorScoreRow, ScoreRow, ScoringRepository

T0 = datetime(2026, 10, 3, 5, 30, tzinfo=UTC)


class TestScoring:
    def test_scores_and_factor_ranks_roundtrip(self, session):
        ids = MarketDataRepository(session).get_or_create_instruments(["SAP.DE", "TINY.DE"])
        repo = ScoringRepository(session)
        sid = repo.write_scoring_run(
            fetch_run_id=7, config={"value_weight": 0.6}, app_version="0.3.0", origin="live"
        )
        repo.write_score_results(
            sid,
            [
                ScoreRow(ids["SAP.DE"], True, 0.8, 0.6, 0.72, False, 1),
                ScoreRow(ids["TINY.DE"], False, None, None, None, None, None),
            ],
        )
        repo.write_factor_scores(
            sid, [FactorScoreRow(ids["SAP.DE"], "ev_ebit", "value", "ev_ebit", "low", 22.0, 0.8)]
        )
        session.commit()

        run = repo.get_scoring_run(sid)
        assert run is not None
        assert run.config == {"value_weight": 0.6}
        assert run.config_hash  # deterministischer Hash der Konfiguration
        scores = repo.get_scores_df(sid).set_index("symbol")
        assert scores.loc["SAP.DE", "composite_score"] == 0.72
        assert not scores.loc["TINY.DE", "passed_filter"]
        factors = repo.get_factor_scores_df(sid)
        assert factors[["symbol", "factor_key", "raw_value", "percentile_rank"]].to_dict(
            "records"
        ) == [
            {"symbol": "SAP.DE", "factor_key": "ev_ebit", "raw_value": 22.0, "percentile_rank": 0.8}
        ]

    def test_same_config_same_hash(self, session):
        repo = ScoringRepository(session)
        a = repo.write_scoring_run(fetch_run_id=1, config={"b": 1, "a": 2}, app_version="x")
        b = repo.write_scoring_run(fetch_run_id=2, config={"a": 2, "b": 1}, app_version="x")
        assert repo.get_scoring_run(a).config_hash == repo.get_scoring_run(b).config_hash  # type: ignore[union-attr]

    def test_score_history_orders_by_time(self, engine):
        with session_scope(engine) as s:
            iid = MarketDataRepository(s).get_or_create_instruments(["SAP.DE"])["SAP.DE"]
            repo = ScoringRepository(s)
            for week, composite in enumerate((0.6, 0.7)):
                sid = repo.write_scoring_run(
                    fetch_run_id=week,
                    config={},
                    app_version="x",
                    created_at=T0 + timedelta(days=7 * week),
                )
                repo.write_score_results(sid, [ScoreRow(iid, True, 0.5, 0.5, composite, False, 1)])
        with session_scope(engine) as s:
            history = ScoringRepository(s).get_score_history("SAP.DE")
        assert list(history["composite_score"]) == [0.6, 0.7]


class TestReporting:
    def test_report_and_deliveries(self, session):
        repo = ReportingRepository(session)
        rid = repo.write_report(
            run_id=1,
            scoring_run_id=2,
            subject="[ok 2/2] Test",
            html="<html></html>",
            csv_bytes=b"\xef\xbb\xbfsymbol;score\n",
            csv_filename="value_ranking_20261003.csv",
            top_n=20,
            bottom_n=10,
        )
        repo.write_delivery(
            run_id=1,
            report_id=rid,
            channel="mail",
            kind="report",
            recipient="a@example.com",
            subject="[ok 2/2] Test",
            success=True,
        )
        repo.write_delivery(
            run_id=1,
            report_id=None,
            channel="healthcheck",
            kind="ping_fail",
            recipient="hc-ping.com",
            subject=None,
            success=False,
            error="timeout",
        )
        session.commit()

        report = repo.get_report(rid)
        assert report is not None
        assert report.csv_bytes.startswith(b"\xef\xbb\xbf")
        assert repo.get_report_for_run(1).id == rid  # type: ignore[union-attr]
        deliveries = repo.get_deliveries(1)
        assert [(d.channel, d.success) for d in deliveries] == [
            ("mail", True),
            ("healthcheck", False),
        ]


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
