"""Ende-zu-Ende: _run() schreibt einen kompletten Lauf in die Datenbank.

yfinance und SMTP bleiben gemockt, die Datenbank ist echt.
"""

from __future__ import annotations

from datetime import date
from unittest.mock import patch

import pandas as pd
import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from src.consensus import ConsensusEntry
from src.db.engine import session_scope
from src.db.repositories.market_data import MarketDataRepository
from src.db.repositories.reporting import ReportingRepository
from src.db.repositories.runs import RunRepository
from src.db.repositories.scoring import ScoringRepository
from src.main import _run
from src.universe import Ticker, Universe

TICKERS = [
    Ticker("AAA.DE", "Alpha", "DAX", isin="DE000AAA0001"),
    Ticker("BBB.DE", "Beta", "DAX"),
    Ticker("CCC.DE", "Gamma", "MDAX"),
    Ticker("TINY.DE", "Tiny", "MDAX"),
]

UNIVERSE = Universe(tickers=TICKERS, source="iShares", as_of=date(2026, 9, 29))

PERIODS = [pd.Timestamp("2025-12-31"), pd.Timestamp("2024-12-31")]


def _fake_ticker_data(symbol: str):
    base = {"AAA.DE": 1.0, "BBB.DE": 2.0, "CCC.DE": 3.0, "TINY.DE": 1.5}[symbol]
    cap = 1e8 if symbol == "TINY.DE" else 5e9 * base
    info = {
        "currency": "EUR",
        "financialCurrency": "EUR",
        "marketCap": cap,
        "enterpriseValue": cap * 1.2,
        "currentPrice": 10 * base,
        "trailingAnnualDividendYield": 0.01 * base,
        "sector": "Industrials",
        "beta": float("nan"),
    }
    income = pd.DataFrame(
        {
            PERIODS[0]: [1_000.0 * base, 150.0 * base, 100.0 * base, 120.0, 30.0, 200.0 * base],
            PERIODS[1]: [900.0 * base, 140.0 * base, 90.0 * base, 110.0, 28.0, 190.0 * base],
        },
        index=["Total Revenue", "EBIT", "Net Income", "Pretax Income", "Tax Provision", "EBITDA"],
    )
    balance = pd.DataFrame(
        {PERIODS[0]: [2_000.0 * base, 500.0, 200.0, 5_000.0]},
        index=["Stockholders Equity", "Total Debt", "Cash And Cash Equivalents", "Total Assets"],
    )
    cashflow = pd.DataFrame(
        {PERIODS[0]: [120.0 * base, -10.0]}, index=["Free Cash Flow", "Repurchase Of Capital Stock"]
    )
    return info, income, balance, cashflow


def _fake_consensus(symbol: str) -> dict[str, ConsensusEntry]:
    """BBB.DE: Yahoo drosselt den Abruf - der Titel darf dadurch nicht verloren gehen."""
    if symbol == "BBB.DE":
        return {"eps_trend": ConsensusEntry("error", None, "RuntimeError: Too Many Requests")}
    return {
        "eps_trend": ConsensusEntry("ok", {"+1y": {"current": 4.5, "90daysAgo": 4.7}}, None),
        "growth_estimates": ConsensusEntry("empty", None, None),
    }


@pytest.fixture
def db_settings(tmp_path, monkeypatch, db_url):
    monkeypatch.setenv("SMTP_USER", "test@gmail.com")
    monkeypatch.setenv("SMTP_PASSWORD", "dummy-app-pw")
    monkeypatch.setenv("MAIL_TO", "recipient@example.com")
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.chdir(tmp_path)
    from src.config import Settings

    s = Settings()  # type: ignore[call-arg]
    return s.model_copy(update={"data_dir": tmp_path / "data", "logs_dir": tmp_path / "logs"})


def _patched_run(settings, *, force_refresh=False, dry_run=False):
    with (
        patch("src.main.load_universe", return_value=UNIVERSE),
        patch("src.data_fetcher._ticker_data", side_effect=_fake_ticker_data) as ticker_data,
        patch("src.data_fetcher.fetch_consensus", side_effect=_fake_consensus),
        patch("src.data_fetcher.time.sleep"),
        patch("src.main.send_report") as send,
        patch("src.main.ping", return_value=None),
    ):
        rc = _run(settings, force_refresh=force_refresh, dry_run=dry_run)
    return rc, ticker_data, send


class TestFullRun:
    def test_everything_is_persisted(self, db_settings, engine):
        rc, _, send = _patched_run(db_settings)
        assert rc == 0
        send.assert_called_once()
        filename, payload = send.call_args.kwargs["attachment"]
        assert filename.startswith("value_ranking_")
        assert payload.startswith(b"\xef\xbb\xbf")

        with session_scope(engine) as s:
            run = RunRepository(s).get_latest_run()
            assert run is not None
            assert run.status == "partial"  # TINY.DE faellt durch den Groessenfilter
            assert run.exit_code == 0
            assert run.settings is not None
            assert "smtp_password" not in run.settings
            assert "database_url" not in run.settings

            md = MarketDataRepository(s)
            assert run.fetch_run_id is not None
            snapshots = md.get_snapshots_df(run.fetch_run_id)
            assert set(snapshots["symbol"]) == {t.symbol for t in TICKERS}
            assert set(md.get_universe(run.fetch_run_id)["symbol"]) == {t.symbol for t in TICKERS}
            assert md.get_raw_info(run.fetch_run_id, "AAA.DE")["beta"] is None  # type: ignore[index]
            consensus = md.get_consensus(run.fetch_run_id, "AAA.DE")
            assert consensus == _fake_consensus("AAA.DE")
            assert md.get_consensus(run.fetch_run_id, "BBB.DE")["eps_trend"].status == "error"
            # Konsens-Fehler landen nicht in der Snapshot-Spalte errors - die CSV bleibt gleich
            assert snapshots.set_index("symbol").loc["BBB.DE", "errors"] == ""
            assert len(md.get_statements_as_of("AAA.DE", pd.Timestamp.now(tz="UTC"))) > 5
            fetch_run = md.get_fetch_run(run.fetch_run_id)
            assert fetch_run is not None
            assert fetch_run.success_share == 1.0
            assert (fetch_run.universe_source, fetch_run.universe_as_of) == (
                "iShares",
                date(2026, 9, 29),
            )
            assert md.get_instrument("AAA.DE").isin == "DE000AAA0001"  # type: ignore[union-attr]
            assert md.get_instrument("BBB.DE").isin is None  # type: ignore[union-attr]

            sc = ScoringRepository(s)
            assert run.scoring_run_id is not None
            scores = sc.get_scores_df(run.scoring_run_id).set_index("symbol")
            assert not scores.loc["TINY.DE", "passed_filter"]
            assert scores["passed_filter"].sum() == 3
            assert len(sc.get_factor_scores_df(run.scoring_run_id)) > 0

            rep = ReportingRepository(s)
            report = rep.get_report_for_run(run.id)
            assert report is not None
            assert report.html.startswith("<!DOCTYPE")
            deliveries = rep.get_deliveries(run.id)
            assert [(d.channel, d.kind, d.success) for d in deliveries] == [
                ("mail", "report", True)
            ]

            logs = RunRepository(s).get_logs(run.id)
            assert any("START" in entry.message for entry in logs)

    def test_second_run_same_day_reuses_fetch(self, db_settings, engine):
        _patched_run(db_settings)
        rc, ticker_data, _ = _patched_run(db_settings)
        assert rc == 0
        ticker_data.assert_not_called()
        with engine.connect() as conn:
            assert conn.execute(text("SELECT count(*) FROM market_data.fetch_run")).scalar() == 1
            assert conn.execute(text("SELECT count(*) FROM batch.run")).scalar() == 2
            assert conn.execute(text("SELECT count(*) FROM scoring.scoring_run")).scalar() == 2

    def test_dax_only_after_full_run_reuses_but_filters(self, db_settings, engine):
        _patched_run(db_settings)
        dax_only = db_settings.model_copy(update={"universe": "DAX_ONLY"})
        rc, ticker_data, send = _patched_run(dax_only)
        assert rc == 0
        ticker_data.assert_not_called()
        with session_scope(engine) as s:
            run = RunRepository(s).get_latest_run()
            assert run is not None
            assert run.universe_size == 2
            assert run.scoring_run_id is not None
            scores = ScoringRepository(s).get_scores_df(run.scoring_run_id)
        assert set(scores["symbol"]) == {"AAA.DE", "BBB.DE"}
        assert "Gamma" not in send.call_args.args[2]

    def test_full_run_after_dax_only_fetches_again(self, db_settings, engine):
        _patched_run(db_settings.model_copy(update={"universe": "DAX_ONLY"}))
        _, ticker_data, _ = _patched_run(db_settings)
        assert ticker_data.call_count == len(TICKERS)

    def test_transient_db_error_per_ticker_is_retried(self, db_settings, engine):
        original = MarketDataRepository.write_snapshot
        calls = {"n": 0}

        def flaky(self, *args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 2:
                raise OperationalError("insert", {}, Exception("connection reset"))
            return original(self, *args, **kwargs)

        # time.sleep ist in _patched_run global gepatcht - auch die Retry-Wartezeit
        with patch.object(MarketDataRepository, "write_snapshot", flaky):
            rc, _, _ = _patched_run(db_settings)
        assert rc == 0
        with session_scope(engine) as s:
            run = RunRepository(s).get_latest_run()
            assert run is not None
            assert run.fetch_run_id is not None
            snapshots = MarketDataRepository(s).get_snapshots_df(run.fetch_run_id)
        assert len(snapshots) == len(TICKERS)

    def test_force_refresh_fetches_again_without_duplicating_statements(self, db_settings, engine):
        _patched_run(db_settings)
        with engine.connect() as conn:
            statements = conn.execute(
                text("SELECT count(*) FROM market_data.statement_value")
            ).scalar()
        rc, ticker_data, _ = _patched_run(db_settings, force_refresh=True)
        assert rc == 0
        assert ticker_data.call_count == len(TICKERS)
        with engine.connect() as conn:
            assert conn.execute(text("SELECT count(*) FROM market_data.fetch_run")).scalar() == 2
            again = conn.execute(text("SELECT count(*) FROM market_data.statement_value")).scalar()
        assert again == statements

    def test_dry_run_writes_preview_and_records_no_delivery(self, db_settings, engine):
        rc, _, send = _patched_run(db_settings, dry_run=True)
        assert rc == 0
        send.assert_not_called()
        assert (db_settings.data_dir / "preview_latest.html").exists()
        # Vorschau-CSV traegt ein Praefix, damit der Altdaten-Import sie nicht aufgreift
        assert list(db_settings.data_dir.glob("preview_value_ranking_*.csv"))
        assert not list(db_settings.data_dir.glob("value_ranking_*.csv"))
        with session_scope(engine) as s:
            run = RunRepository(s).get_latest_run()
            assert run is not None
            assert run.dry_run
            assert ReportingRepository(s).get_deliveries(run.id) == []

    def test_failure_is_recorded_with_traceback(self, db_settings, engine):
        with (
            patch("src.main.load_universe", return_value=UNIVERSE),
            patch("src.main.fetch_all", side_effect=RuntimeError("yfinance down")),
            patch("src.main.ping", return_value=None),
            patch("src.main.send_report"),
        ):
            rc = _run(db_settings, force_refresh=False, dry_run=False)
        assert rc == 1
        with session_scope(engine) as s:
            run = RunRepository(s).get_latest_run()
            assert run is not None
            assert run.status == "failed"
            assert run.error is not None
            assert "yfinance down" in run.error
            kinds = [(d.kind, d.success) for d in ReportingRepository(s).get_deliveries(run.id)]
            assert kinds == [("error", True)]
