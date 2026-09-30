"""Integrationstests fuer den Batch-Orchestrator (src/main.py).

Alle externen Grenzen werden gemockt:
- fetch_all                 → gibt mock_universe_df zurueck (kein yfinance-Netz)
- load_universe             → gibt ein festes Universe (Quelle iShares) zurueck
- _open_recorder            → FakeRecorder statt PostgreSQL
- send_report / ping        → pruefen Aufrufe ohne echten SMTP/HTTP

Damit laeuft der komplette _run()-Pfad durch, einschliesslich
Scoring, Report-Bau, Dry-Run-Modus und Fehlerbehandlung. Der gleiche Pfad
gegen ein echtes PostgreSQL steht in tests/db/test_pipeline_db.py.
"""

from __future__ import annotations

from datetime import date
from typing import Any
from unittest.mock import patch

import pandas as pd
import pytest

from src.main import _run, _try_send_error_mail, run
from src.reporting import build_report
from src.universe import Ticker, Universe


def _universe(tickers, **kwargs):
    return Universe(tickers=tickers, source="iShares", as_of=date(2026, 9, 29), **kwargs)


class FakeRecorder:
    """Merkt sich alle Aufrufe - gleiche Schnittstelle wie BatchRecorder."""

    def __init__(
        self,
        reusable: int | None = None,
        snapshots: pd.DataFrame | None = None,
        fail_start: bool = False,
        fail_finish: bool = False,
        failing_symbols: frozenset[str] = frozenset(),
    ) -> None:
        self.calls: list[tuple[str, Any]] = []
        self.reusable = reusable
        self.snapshots = snapshots
        self.fail_start = fail_start
        self.fail_finish = fail_finish
        self.failing_symbols = failing_symbols

    def _names(self) -> list[str]:
        return [name for name, _ in self.calls]

    def get(self, name: str) -> list[Any]:
        return [args for n, args in self.calls if n == name]

    def start_run(self, **kwargs):
        if self.fail_start:
            raise ConnectionError("db down")
        self.calls.append(("start_run", kwargs))
        return 1

    def find_reusable_fetch(self, day, symbols):
        self.calls.append(("find_reusable_fetch", (day, list(symbols))))
        return self.reusable

    def load_snapshots(self, fetch_run_id, symbols):
        self.calls.append(("load_snapshots", (fetch_run_id, list(symbols))))
        return self.snapshots

    def start_fetch(self, tickers, source, as_of=None):
        self.calls.append(("start_fetch", (list(tickers), source, as_of)))
        return 10

    def record_fundamentals(self, fetch_run_id, fund):
        if fund.symbol in self.failing_symbols:
            raise ConnectionError("db hiccup")
        self.calls.append(("record_fundamentals", (fetch_run_id, fund)))

    def finish_fetch(self, fetch_run_id, df):
        self.calls.append(("finish_fetch", fetch_run_id))

    def record_scoring(self, fetch_run_id, df_all, scored, cfg):
        self.calls.append(("record_scoring", fetch_run_id))
        self.scored_symbols = set(df_all["symbol"])
        return 20

    def record_report(self, run_id, scoring_run_id, report):
        self.calls.append(("record_report", (run_id, scoring_run_id)))
        return 30

    def record_delivery(self, **kwargs):
        self.calls.append(("record_delivery", kwargs))

    def finish_run(self, run_id, **kwargs):
        self.calls.append(("finish_run", kwargs))
        if self.fail_finish:
            raise ConnectionError("db gone")

    def record_logs(self, run_id, entries):
        self.calls.append(("record_logs", list(entries)))


@pytest.fixture
def settings(tmp_path, monkeypatch):
    monkeypatch.setenv("SMTP_USER", "test@gmail.com")
    monkeypatch.setenv("SMTP_PASSWORD", "dummy-app-pw")
    monkeypatch.setenv("MAIL_TO", "recipient@example.com")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://va_app:x@localhost/value_analyzer")
    monkeypatch.chdir(tmp_path)

    from src.config import Settings

    s = Settings()  # type: ignore[call-arg]
    return s.model_copy(update={"data_dir": tmp_path / "data", "logs_dir": tmp_path / "logs"})


@pytest.fixture
def mock_tickers():
    return [
        Ticker("VAL.DE", "Value Co", "DAX"),
        Ticker("QUAL.DE", "Quality Co", "DAX"),
        Ticker("TRAP.DE", "Trap Co", "MDAX"),
        Ticker("MID.DE", "Mid Co", "MDAX"),
        Ticker("OK.DE", "OK Co", "DAX"),
        Ticker("LEV.DE", "Leverage Co", "MDAX"),
        Ticker("LOSS.DE", "Loss Co", "MDAX"),
    ]


@pytest.fixture
def recorder():
    return FakeRecorder()


def _run_with(
    settings,
    recorder,
    mock_tickers,
    fetch_all_result,
    *,
    dry_run=False,
    force_refresh=False,
    ping_result=None,
    extra_patches: dict[str, dict[str, Any]] | None = None,
):
    patches = {
        "src.main._open_recorder": {"return_value": recorder},
        "src.main.load_universe": {"return_value": _universe(mock_tickers)},
        "src.main.fetch_all": fetch_all_result,
        "src.main.send_report": {},
        "src.main.ping": {"return_value": ping_result},
        **(extra_patches or {}),
    }
    mocks = {}
    active = []
    for target, kwargs in patches.items():
        p = patch(target, **kwargs)
        mocks[target.rsplit(".", 1)[1]] = p.start()
        active.append(p)
    try:
        rc = _run(settings, force_refresh=force_refresh, dry_run=dry_run)
    finally:
        for p in active:
            p.stop()
    return rc, mocks


# ---------------------------------------------------------------------------
# Dry-Run
# ---------------------------------------------------------------------------


class TestRunDryRun:
    def test_dry_run_returns_zero_without_mail_and_ping(
        self, settings, recorder, mock_tickers, mock_universe_df
    ):
        rc, m = _run_with(
            settings, recorder, mock_tickers, {"return_value": mock_universe_df}, dry_run=True
        )
        assert rc == 0
        m["send_report"].assert_not_called()
        m["ping"].assert_not_called()
        assert recorder.get("record_delivery") == []

    def test_dry_run_writes_preview_and_csv(
        self, settings, recorder, mock_tickers, mock_universe_df
    ):
        _run_with(
            settings, recorder, mock_tickers, {"return_value": mock_universe_df}, dry_run=True
        )
        preview = settings.data_dir / "preview_latest.html"
        assert "Value-Screening" in preview.read_text(encoding="utf-8")
        assert len(list(settings.data_dir.glob("preview_value_ranking_*.csv"))) == 1
        assert not list(settings.data_dir.glob("value_ranking_*.csv"))

    def test_dry_run_is_recorded(self, settings, recorder, mock_tickers, mock_universe_df):
        _run_with(
            settings, recorder, mock_tickers, {"return_value": mock_universe_df}, dry_run=True
        )
        start = recorder.get("start_run")[0]
        assert start["dry_run"] is True
        assert start["kind"] == "batch"
        assert recorder.get("record_report") == [(1, 20)]
        finish = recorder.get("finish_run")[0]
        assert finish["exit_code"] == 0
        assert finish["status"] in {"success", "partial"}


# ---------------------------------------------------------------------------
# Echter Lauf mit Mail
# ---------------------------------------------------------------------------


class TestRunWithMail:
    def test_real_run_sends_csv_as_bytes(self, settings, recorder, mock_tickers, mock_universe_df):
        rc, m = _run_with(settings, recorder, mock_tickers, {"return_value": mock_universe_df})
        assert rc == 0
        call = m["send_report"].call_args
        assert call.args[0] is settings
        assert "/" in call.args[1]  # Betreff mit Statistik
        filename, payload = call.kwargs["attachment"]
        assert filename.startswith("value_ranking_")
        assert isinstance(payload, bytes)

    def test_finish_failure_after_mail_sends_no_error_mail(
        self, settings, mock_tickers, mock_universe_df
    ):
        recorder = FakeRecorder(fail_finish=True)
        rc, m = _run_with(
            settings,
            recorder,
            mock_tickers,
            {"return_value": mock_universe_df},
            ping_result=True,
            extra_patches={"src.main._try_send_error_mail": {}},
        )
        assert rc == 0
        m["_try_send_error_mail"].assert_not_called()
        assert m["ping"].call_args.kwargs["success"] is True

    def test_ticker_that_cannot_be_stored_is_dropped_not_the_batch(
        self, settings, mock_tickers, mock_universe_df
    ):
        recorder = FakeRecorder(failing_symbols=frozenset({"TRAP.DE"}))

        def fake_fetch_all(tickers, *, cfg, on_result):
            from src.fundamentals import Fundamentals, Identity

            for t in tickers:
                on_result(Fundamentals(identity=Identity(t.symbol, t.name, t.index)))
            return mock_universe_df

        rc, _ = _run_with(settings, recorder, mock_tickers, {"side_effect": fake_fetch_all})
        assert rc == 0
        assert "TRAP.DE" not in recorder.scored_symbols  # Report == Datenbankinhalt
        assert "VAL.DE" in recorder.scored_symbols
        entries = recorder.get("record_logs")[0]
        assert any("TRAP.DE" in e.message and e.level == "ERROR" for e in entries)

    def test_real_run_pings_and_records_both_deliveries(
        self, settings, recorder, mock_tickers, mock_universe_df
    ):
        rc, m = _run_with(
            settings, recorder, mock_tickers, {"return_value": mock_universe_df}, ping_result=True
        )
        assert rc == 0
        assert m["ping"].call_args.kwargs["success"] is True
        deliveries = recorder.get("record_delivery")
        assert [(d["channel"], d["kind"], d["success"]) for d in deliveries] == [
            ("mail", "report", True),
            ("healthcheck", "ping_ok", True),
        ]
        assert deliveries[0]["report_id"] == 30

    def test_every_fetched_ticker_goes_through_recorder(
        self, settings, recorder, mock_tickers, mock_universe_df
    ):
        def fake_fetch_all(tickers, *, cfg, on_result):
            from src.fundamentals import Fundamentals, Identity

            for t in tickers:
                on_result(Fundamentals(identity=Identity(t.symbol, t.name, t.index)))
            return mock_universe_df

        _run_with(settings, recorder, mock_tickers, {"side_effect": fake_fetch_all})
        recorded = [fund.symbol for _, fund in recorder.get("record_fundamentals")]
        assert recorded == [t.symbol for t in mock_tickers]
        assert recorder.get("start_fetch")[0] == (mock_tickers, "iShares", date(2026, 9, 29))
        assert recorder.get("finish_fetch") == [10]
        assert recorder.get("record_scoring") == [10]

    def test_logs_are_recorded(self, settings, recorder, mock_tickers, mock_universe_df):
        _run_with(settings, recorder, mock_tickers, {"return_value": mock_universe_df})
        entries = recorder.get("record_logs")[0]
        assert any("START" in e.message for e in entries)

    def test_mail_failure_is_recorded_and_fails_run(
        self, settings, recorder, mock_tickers, mock_universe_df
    ):
        rc, _ = _run_with(
            settings,
            recorder,
            mock_tickers,
            {"return_value": mock_universe_df},
            extra_patches={
                "src.main.send_report": {"side_effect": OSError("smtp down")},
                "src.main._try_send_error_mail": {},
            },
        )
        assert rc == 1
        mail = recorder.get("record_delivery")[0]
        assert (mail["kind"], mail["success"]) == ("report", False)
        assert "smtp down" in mail["error"]
        assert recorder.get("finish_run")[0]["status"] == "failed"


# ---------------------------------------------------------------------------
# Wiederverwendung des Tagesabrufs / force_refresh
# ---------------------------------------------------------------------------


class TestReuse:
    def test_reuses_todays_fetch(self, settings, mock_tickers, mock_universe_df):
        recorder = FakeRecorder(reusable=99, snapshots=mock_universe_df)
        rc, m = _run_with(settings, recorder, mock_tickers, {})
        assert rc == 0
        m["fetch_all"].assert_not_called()
        symbols = [t.symbol for t in mock_tickers]
        assert recorder.get("find_reusable_fetch")[0][1] == symbols
        assert recorder.get("load_snapshots") == [(99, symbols)]
        assert recorder.get("record_scoring") == [99]
        assert recorder.get("start_fetch") == []

    def test_force_refresh_skips_reuse(self, settings, mock_tickers, mock_universe_df):
        recorder = FakeRecorder(reusable=99, snapshots=mock_universe_df)
        _, m = _run_with(
            settings, recorder, mock_tickers, {"return_value": mock_universe_df}, force_refresh=True
        )
        m["fetch_all"].assert_called_once()
        assert recorder.get("find_reusable_fetch") == []
        assert recorder.get("start_run")[0]["force_refresh"] is True


# ---------------------------------------------------------------------------
# DAX_ONLY-Filter
# ---------------------------------------------------------------------------


class TestRunDaxOnly:
    def test_dax_only_filters_mdax_tickers(
        self, settings, recorder, mock_tickers, mock_universe_df
    ):
        dax_only = settings.model_copy(update={"universe": "DAX_ONLY"})
        captured: list[list[Ticker]] = []

        def fake_fetch_all(tickers, **kwargs):
            captured.append(tickers)
            symbols = {t.symbol for t in tickers}
            return mock_universe_df[mock_universe_df["symbol"].isin(symbols)].copy()

        rc, _ = _run_with(
            dax_only, recorder, mock_tickers, {"side_effect": fake_fetch_all}, dry_run=True
        )
        assert rc == 0
        assert all(t.index == "DAX" for t in captured[0])
        assert "TRAP.DE" not in {t.symbol for t in captured[0]}


# ---------------------------------------------------------------------------
# Fehlerbehandlung
# ---------------------------------------------------------------------------


class TestRunErrorHandling:
    def test_no_scoreable_data_returns_code_3(self, settings, recorder, mock_tickers):
        empty_df = pd.DataFrame(
            columns=["symbol", "name", "index", "market_cap", "composite_score"]
        )
        rc, m = _run_with(
            settings,
            recorder,
            mock_tickers,
            {"return_value": empty_df},
            extra_patches={"src.main.score": {"return_value": empty_df}},
        )
        assert rc == 3
        assert m["ping"].call_args.kwargs["success"] is False
        finish = recorder.get("finish_run")[0]
        assert (finish["status"], finish["exit_code"]) == ("no_data", 3)

    def test_exception_in_fetch_returns_code_1(self, settings, recorder, mock_tickers):
        rc, m = _run_with(
            settings,
            recorder,
            mock_tickers,
            {"side_effect": RuntimeError("yfinance down")},
            extra_patches={"src.main._try_send_error_mail": {}},
        )
        assert rc == 1
        assert m["ping"].call_args.kwargs["success"] is False
        m["_try_send_error_mail"].assert_called_once()
        assert "RuntimeError" in m["_try_send_error_mail"].call_args.args[1]
        finish = recorder.get("finish_run")[0]
        assert finish["status"] == "failed"
        assert "yfinance down" in finish["error"]

    def test_exception_in_dry_run_does_not_send_error_mail(self, settings, recorder, mock_tickers):
        _, m = _run_with(
            settings,
            recorder,
            mock_tickers,
            {"side_effect": RuntimeError("boom")},
            dry_run=True,
            extra_patches={"src.main._try_send_error_mail": {}},
        )
        m["_try_send_error_mail"].assert_not_called()

    def test_database_unreachable_returns_code_4(self, settings, mock_tickers, mock_universe_df):
        recorder = FakeRecorder(fail_start=True)
        rc, m = _run_with(
            settings,
            recorder,
            mock_tickers,
            {"return_value": mock_universe_df},
            extra_patches={"src.main._try_send_error_mail": {}},
        )
        assert rc == 4
        m["fetch_all"].assert_not_called()
        m["send_report"].assert_not_called()
        assert m["ping"].call_args.kwargs["success"] is False
        m["_try_send_error_mail"].assert_called_once()

    def test_error_mail_escapes_traceback(self, settings):
        trace = "ValueError: <b>kaputt</b> & mehr"
        with patch("src.main.send_report") as mock_send:
            _try_send_error_mail(settings, trace)
        body = mock_send.call_args.args[2]
        assert "&lt;b&gt;kaputt&lt;/b&gt; &amp; mehr" in body
        assert "<b>kaputt</b>" not in body

    def test_error_mail_is_recorded(self, settings, recorder):
        with patch("src.main.send_report"):
            _try_send_error_mail(settings, "trace", recorder=recorder, run_id=1)
        delivery = recorder.get("record_delivery")[0]
        assert (delivery["kind"], delivery["success"], delivery["run_id"]) == ("error", True, 1)


# ---------------------------------------------------------------------------
# run() - Config-Fehler (oeffentliche Einstiegsfunktion)
# ---------------------------------------------------------------------------


class TestRunConfigError:
    def test_missing_env_returns_code_2(self, monkeypatch, tmp_path):
        for var in ("SMTP_USER", "SMTP_PASSWORD", "MAIL_TO", "DATABASE_URL"):
            monkeypatch.delenv(var, raising=False)
        monkeypatch.chdir(tmp_path)
        assert run() == 2

    def test_missing_database_url_returns_code_2(self, monkeypatch, tmp_path):
        monkeypatch.setenv("SMTP_USER", "test@gmail.com")
        monkeypatch.setenv("SMTP_PASSWORD", "dummy")
        monkeypatch.setenv("MAIL_TO", "r@example.com")
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.chdir(tmp_path)
        assert run() == 2

    def test_valid_env_does_not_return_code_2(self, monkeypatch, tmp_path):
        monkeypatch.setenv("SMTP_USER", "test@gmail.com")
        monkeypatch.setenv("SMTP_PASSWORD", "dummy")
        monkeypatch.setenv("MAIL_TO", "r@example.com")
        monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://va_app:x@localhost/va")
        monkeypatch.chdir(tmp_path)
        empty = pd.DataFrame(columns=["symbol", "market_cap", "composite_score"])
        with (
            patch("src.main._open_recorder", return_value=FakeRecorder()),
            patch("src.main.load_universe", return_value=_universe([])),
            patch("src.main.fetch_all", return_value=empty),
            patch("src.main.score", return_value=empty),
            patch("src.main.ping"),
        ):
            rc = run(dry_run=True)
        assert rc != 2


# ---------------------------------------------------------------------------
# Indexquelle im Report
# ---------------------------------------------------------------------------


class TestUniverseSourceInReport:
    def _build_report_kwargs(self, settings, universe, mock_universe_df):
        with (
            patch("src.main._open_recorder", return_value=FakeRecorder()),
            patch("src.main.load_universe", return_value=universe),
            patch("src.main.fetch_all", return_value=mock_universe_df),
            patch("src.main.build_report", wraps=build_report) as br,
            patch("src.main.ping"),
        ):
            _run(settings, force_refresh=False, dry_run=True)
        return br.call_args.kwargs

    def test_passes_source_with_as_of(self, settings, mock_tickers, mock_universe_df):
        kwargs = self._build_report_kwargs(settings, _universe(mock_tickers), mock_universe_df)
        assert kwargs["universe_source"] == "iShares"
        assert kwargs["universe_as_of"] == date(2026, 9, 29)
        assert kwargs["universe_added"] == []
        assert kwargs["universe_removed"] == []

    def test_passes_csv_drift(self, settings, mock_tickers, mock_universe_df):
        uni = _universe(
            mock_tickers,
            added=[Ticker("SAX.DE", "Ströer", "MDAX")],
            removed=[Ticker("BOSS.DE", "Hugo Boss", "MDAX")],
        )
        kwargs = self._build_report_kwargs(settings, uni, mock_universe_df)
        assert kwargs["universe_added"] == ["Ströer (SAX.DE, MDAX)"]
        assert kwargs["universe_removed"] == ["Hugo Boss (BOSS.DE, MDAX)"]
