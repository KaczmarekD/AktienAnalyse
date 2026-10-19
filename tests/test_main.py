"""Integrationstests fuer den Batch (src/main.py) ueber den Bus im Prozess.

``_run`` bekommt die Adapter von aussen (``src.composition.Adapters``):
- FakeRecorder        -> alle Speicher (batch, market_data, scoring, reporting)
- load_universe       -> festes Universe (Quelle iShares)
- fetch               -> Mock, liefert mock_universe_df (kein yfinance-Netz)
- sender / heartbeat  -> Mocks statt SMTP und Healthchecks.io

Damit laeuft der komplette Pfad durch: Handler aller Module, Events, RunTracker, Abschluss
des Laufs. Der gleiche Pfad gegen ein echtes PostgreSQL steht in tests/db/test_pipeline_db.py.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime
from typing import Any
from unittest.mock import Mock, patch

import pandas as pd
import pytest

from src.composition import Adapters
from src.main import _run, run
from va_market_data.domain.fundamentals import Fundamentals, Identity
from va_market_data.domain.history import HistoryState
from va_market_data.domain.universe import Ticker, Universe
from va_notification.domain.errors import ERROR_SUBJECT


def _universe(tickers, **kwargs):
    return Universe(tickers=tickers, source="iShares", as_of=date(2026, 9, 29), **kwargs)


class FakeRecorder:
    """Merkt sich alle Aufrufe - alle Speicher-Ports in einem."""

    def __init__(
        self,
        reusable: int | None = None,
        snapshots: pd.DataFrame | None = None,
        fail_start: bool = False,
        fail_finish: bool = False,
        failing_symbols: frozenset[str] = frozenset(),
        history: dict[str, HistoryState] | None = None,
        fail_history: bool = False,
    ) -> None:
        self.calls: list[tuple[str, Any]] = []
        self.reusable = reusable
        self.snapshots = snapshots
        self.fail_start = fail_start
        self.fail_finish = fail_finish
        self.failing_symbols = failing_symbols
        self.history = history or {}
        self.fail_history = fail_history

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

    def history_state(self, symbols):
        self.calls.append(("history_state", list(symbols)))
        if self.fail_history:
            raise ConnectionError("db hiccup")
        return self.history

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


def _heartbeat(result: bool | None) -> Mock:
    heartbeat = Mock()
    heartbeat.ping.return_value = result
    return heartbeat


def _adapters(recorder, universe, fetch, *, ping_result=None, sender=None) -> Adapters:
    return Adapters(
        batch=recorder,
        market_data=recorder,
        scoring=recorder,
        reporting=recorder,
        load_universe=lambda: universe,
        fetch=fetch,
        sender=sender or Mock(),
        heartbeat=_heartbeat(ping_result),
        clock=datetime.now,
    )


def _run_with(
    settings,
    recorder,
    mock_tickers,
    fetch: Any,
    *,
    dry_run=False,
    force_refresh=False,
    ping_result=None,
    sender=None,
    universe=None,
):
    """``fetch``: Mock-Argumente (return_value/side_effect) oder eine fertige Funktion."""
    fetch_mock = Mock(**fetch) if isinstance(fetch, dict) else Mock(side_effect=fetch)
    adapters = _adapters(
        recorder,
        universe or _universe(mock_tickers),
        fetch_mock,
        ping_result=ping_result,
        sender=sender,
    )
    rc = _run(settings, force_refresh=force_refresh, dry_run=dry_run, adapters=adapters)
    return rc, adapters, fetch_mock


def _mails(adapters: Adapters, subject: str | None = None) -> list[Any]:
    calls = adapters.sender.send.call_args_list  # type: ignore[attr-defined]
    return [c for c in calls if subject is None or c.args[0] == subject]


def _pings(adapters: Adapters) -> list[Any]:
    return adapters.heartbeat.ping.call_args_list  # type: ignore[attr-defined]


def _stores_each(tickers, *, on_result, history):
    for t in tickers:
        on_result(Fundamentals(identity=Identity(t.symbol, t.name, t.index)))


# ---------------------------------------------------------------------------
# Dry-Run
# ---------------------------------------------------------------------------


class TestRunDryRun:
    def test_dry_run_returns_zero_without_mail_and_ping(
        self, settings, recorder, mock_tickers, mock_universe_df
    ):
        rc, adapters, _ = _run_with(
            settings, recorder, mock_tickers, {"return_value": mock_universe_df}, dry_run=True
        )
        assert rc == 0
        assert _mails(adapters) == []
        assert _pings(adapters) == []
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
        assert (finish["fetch_run_id"], finish["scoring_run_id"], finish["report_id"]) == (
            10,
            20,
            30,
        )


# ---------------------------------------------------------------------------
# Echter Lauf mit Mail
# ---------------------------------------------------------------------------


class TestRunWithMail:
    def test_real_run_sends_csv_as_bytes(self, settings, recorder, mock_tickers, mock_universe_df):
        rc, adapters, _ = _run_with(
            settings, recorder, mock_tickers, {"return_value": mock_universe_df}
        )
        assert rc == 0
        call = _mails(adapters)[0]
        assert "/" in call.args[0]  # Betreff mit Statistik
        filename, payload = call.kwargs["attachment"]
        assert filename.startswith("value_ranking_")
        assert isinstance(payload, bytes)

    def test_finish_failure_after_mail_sends_no_error_mail(
        self, settings, mock_tickers, mock_universe_df
    ):
        recorder = FakeRecorder(fail_finish=True)
        rc, adapters, _ = _run_with(
            settings, recorder, mock_tickers, {"return_value": mock_universe_df}, ping_result=True
        )
        assert rc == 0
        assert _mails(adapters, ERROR_SUBJECT) == []
        assert _pings(adapters)[-1].args[0] is True

    def test_ticker_that_cannot_be_stored_is_dropped_not_the_batch(
        self, settings, mock_tickers, mock_universe_df
    ):
        recorder = FakeRecorder(failing_symbols=frozenset({"TRAP.DE"}))

        def fetch(tickers, *, on_result, history):
            _stores_each(tickers, on_result=on_result, history=history)
            return mock_universe_df

        rc, _, _ = _run_with(settings, recorder, mock_tickers, fetch)
        assert rc == 0
        assert "TRAP.DE" not in recorder.scored_symbols  # Report == Datenbankinhalt
        assert "VAL.DE" in recorder.scored_symbols
        entries = recorder.get("record_logs")[0]
        assert any("TRAP.DE" in e.message and e.level == "ERROR" for e in entries)

    def test_real_run_pings_and_records_both_deliveries(
        self, settings, recorder, mock_tickers, mock_universe_df
    ):
        rc, adapters, _ = _run_with(
            settings, recorder, mock_tickers, {"return_value": mock_universe_df}, ping_result=True
        )
        assert rc == 0
        assert _pings(adapters)[-1].args[0] is True
        deliveries = recorder.get("record_delivery")
        assert [(d["channel"], d["kind"], d["success"]) for d in deliveries] == [
            ("mail", "report", True),
            ("healthcheck", "ping_ok", True),
        ]
        assert deliveries[0]["report_id"] == 30
        assert deliveries[0]["recipient"] == "recipient@example.com"

    def test_every_fetched_ticker_goes_through_recorder(
        self, settings, recorder, mock_tickers, mock_universe_df
    ):
        def fetch(tickers, *, on_result, history):
            _stores_each(tickers, on_result=on_result, history=history)
            return mock_universe_df

        _run_with(settings, recorder, mock_tickers, fetch)
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
        sender = Mock()
        sender.send.side_effect = OSError("smtp down")
        rc, _, _ = _run_with(
            settings, recorder, mock_tickers, {"return_value": mock_universe_df}, sender=sender
        )
        assert rc == 1
        mail = recorder.get("record_delivery")[0]
        assert (mail["kind"], mail["success"]) == ("report", False)
        assert "smtp down" in mail["error"]
        finish = recorder.get("finish_run")[0]
        assert finish["status"] == "failed"
        assert "smtp down" in finish["error"]


# ---------------------------------------------------------------------------
# Wiederverwendung des Tagesabrufs / force_refresh
# ---------------------------------------------------------------------------


class TestReuse:
    def test_reuses_todays_fetch(self, settings, mock_tickers, mock_universe_df):
        recorder = FakeRecorder(reusable=99, snapshots=mock_universe_df)
        rc, _, fetch = _run_with(settings, recorder, mock_tickers, {})
        assert rc == 0
        fetch.assert_not_called()
        symbols = [t.symbol for t in mock_tickers]
        assert recorder.get("find_reusable_fetch")[0][1] == symbols
        assert recorder.get("load_snapshots") == [(99, symbols)]
        assert recorder.get("record_scoring") == [99]
        assert recorder.get("start_fetch") == []

    def test_force_refresh_skips_reuse(self, settings, mock_tickers, mock_universe_df):
        recorder = FakeRecorder(reusable=99, snapshots=mock_universe_df)
        _, _, fetch = _run_with(
            settings, recorder, mock_tickers, {"return_value": mock_universe_df}, force_refresh=True
        )
        fetch.assert_called_once()
        assert recorder.get("find_reusable_fetch") == []
        assert recorder.get("start_run")[0]["force_refresh"] is True


class TestHistoryState:
    """F1.3: Vor dem Abruf liest der Lauf, bis wann die Historie schon gespeichert ist."""

    def test_stored_history_is_passed_to_the_fetch(self, settings, mock_tickers, mock_universe_df):
        state = {"VAL.DE": HistoryState(last_share_date=date(2026, 7, 29))}
        recorder = FakeRecorder(history=state)
        _, _, fetch = _run_with(
            settings, recorder, mock_tickers, {"return_value": mock_universe_df}
        )
        assert recorder.get("history_state") == [[t.symbol for t in mock_tickers]]
        assert fetch.call_args.kwargs["history"] == state

    def test_unreadable_history_means_full_history(self, settings, mock_tickers, mock_universe_df):
        recorder = FakeRecorder(fail_history=True)
        rc, _, fetch = _run_with(
            settings, recorder, mock_tickers, {"return_value": mock_universe_df}
        )
        assert rc == 0
        assert fetch.call_args.kwargs["history"] == {}

    def test_reused_fetch_needs_no_history(self, settings, mock_tickers, mock_universe_df):
        recorder = FakeRecorder(reusable=99, snapshots=mock_universe_df)
        _run_with(settings, recorder, mock_tickers, {})
        assert recorder.get("history_state") == []


# ---------------------------------------------------------------------------
# DAX_ONLY-Filter
# ---------------------------------------------------------------------------


class TestRunDaxOnly:
    def test_dax_only_filters_mdax_tickers(
        self, settings, recorder, mock_tickers, mock_universe_df
    ):
        dax_only = settings.model_copy(update={"universe": "DAX_ONLY"})
        captured: list[list[Ticker]] = []

        def fetch(tickers, **kwargs):
            captured.append(tickers)
            symbols = {t.symbol for t in tickers}
            return mock_universe_df[mock_universe_df["symbol"].isin(symbols)].copy()

        rc, _, _ = _run_with(dax_only, recorder, mock_tickers, fetch, dry_run=True)
        assert rc == 0
        assert all(t.index == "DAX" for t in captured[0])
        assert "TRAP.DE" not in {t.symbol for t in captured[0]}


# ---------------------------------------------------------------------------
# Fehlerbehandlung
# ---------------------------------------------------------------------------


class TestRunErrorHandling:
    def test_no_scoreable_data_returns_code_3(self, settings, recorder, mock_tickers):
        empty_df = pd.DataFrame(columns=["symbol", "name", "index", "market_cap"])
        rc, adapters, _ = _run_with(settings, recorder, mock_tickers, {"return_value": empty_df})
        assert rc == 3
        assert _pings(adapters)[-1].args[0] is False
        assert _mails(adapters) == []
        finish = recorder.get("finish_run")[0]
        assert (finish["status"], finish["exit_code"]) == ("no_data", 3)

    def test_exception_in_fetch_returns_code_1(self, settings, recorder, mock_tickers):
        rc, adapters, _ = _run_with(
            settings, recorder, mock_tickers, {"side_effect": RuntimeError("yfinance down")}
        )
        assert rc == 1
        assert _pings(adapters)[-1].args[0] is False
        error_mails = _mails(adapters, ERROR_SUBJECT)
        assert len(error_mails) == 1
        assert "RuntimeError" in error_mails[0].args[1]
        finish = recorder.get("finish_run")[0]
        assert finish["status"] == "failed"
        assert "yfinance down" in finish["error"]
        delivery = recorder.get("record_delivery")[-1]
        assert (delivery["kind"], delivery["success"], delivery["run_id"]) == ("error", True, 1)

    def test_exception_in_dry_run_does_not_send_error_mail(self, settings, recorder, mock_tickers):
        rc, adapters, _ = _run_with(
            settings, recorder, mock_tickers, {"side_effect": RuntimeError("boom")}, dry_run=True
        )
        assert rc == 1
        assert _mails(adapters) == []

    def test_database_unreachable_returns_code_4(self, settings, mock_tickers, mock_universe_df):
        recorder = FakeRecorder(fail_start=True)
        rc, adapters, fetch = _run_with(
            settings, recorder, mock_tickers, {"return_value": mock_universe_df}
        )
        assert rc == 4
        fetch.assert_not_called()
        assert _pings(adapters)[-1].args == (False, "database unreachable")
        assert len(_mails(adapters, ERROR_SUBJECT)) == 1
        assert len(_mails(adapters)) == 1
        assert recorder.get("record_delivery") == []

    def test_unknown_end_of_run_fails_and_alerts(
        self, settings, recorder, mock_tickers, mock_universe_df
    ):
        """Endet die Kette ohne Abschluss-Event (Bug), darf der Lauf nicht als ok gelten."""
        with patch("src.main.wire"):  # niemand reagiert auf den Start
            rc, adapters, _ = _run_with(
                settings, recorder, mock_tickers, {"return_value": mock_universe_df}
            )
        assert rc == 1
        assert recorder.get("finish_run")[0]["status"] == "failed"
        assert _pings(adapters)[-1].args[0] is False
        assert len(_mails(adapters, ERROR_SUBJECT)) == 1

    def test_handler_bug_becomes_a_dead_letter_and_fails_the_run(
        self, settings, recorder, mock_tickers, mock_universe_df
    ):
        """Ein Handler, der wirft (statt run.failed zu melden): Lauf scheitert mit Alarm."""
        with patch(
            "va_scoring.entrypoints.handlers.SnapshotCompletedHandler.__call__",
            side_effect=RuntimeError("Bug im Handler"),
        ):
            rc, adapters, _ = _run_with(
                settings, recorder, mock_tickers, {"return_value": mock_universe_df}
            )
        assert rc == 1
        finish = recorder.get("finish_run")[0]
        assert finish["status"] == "failed"
        assert "scoring" in finish["error"]
        assert "Bug im Handler" in finish["error"]
        assert _pings(adapters)[-1].args[0] is False
        assert len(_mails(adapters, ERROR_SUBJECT)) == 1

    def test_error_escaping_the_bus_fails_the_run_with_alarm(
        self, settings, recorder, mock_tickers, mock_universe_df
    ):
        with patch("src.main.InProcessBus.publish", side_effect=RuntimeError("Bus kaputt")):
            rc, adapters, _ = _run_with(
                settings, recorder, mock_tickers, {"return_value": mock_universe_df}
            )
        assert rc == 1
        finish = recorder.get("finish_run")[0]
        assert finish["status"] == "failed"
        assert "Bus kaputt" in finish["error"]
        assert _pings(adapters)[-1].args[0] is False
        assert len(_mails(adapters, ERROR_SUBJECT)) == 1
        assert recorder.get("record_logs")  # Log-Zeilen trotzdem gespeichert


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
        monkeypatch.setenv("LOGS_DIR", str(tmp_path / "logs"))
        monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
        monkeypatch.chdir(tmp_path)
        empty = pd.DataFrame(columns=["symbol", "market_cap"])
        adapters = _adapters(FakeRecorder(), _universe([]), Mock(return_value=empty))
        with patch("src.main.build_adapters", return_value=adapters):
            rc = run(dry_run=True)
        assert rc != 2
        # Nichts ausserhalb von tmp_path: /app ist nur im Container beschreibbar
        assert (tmp_path / "logs" / "value-analyzer.log").exists()


# ---------------------------------------------------------------------------
# Indexquelle im Report
# ---------------------------------------------------------------------------


class TestUniverseSourceInReport:
    def _preview(self, settings, universe, mock_universe_df) -> str:
        adapters = _adapters(FakeRecorder(), universe, Mock(return_value=mock_universe_df))
        _run(settings, force_refresh=False, dry_run=True, adapters=adapters)
        return (settings.data_dir / "preview_latest.html").read_text(encoding="utf-8")

    def test_shows_source_with_as_of(self, settings, mock_tickers, mock_universe_df):
        html = self._preview(settings, _universe(mock_tickers), mock_universe_df)
        assert "iShares" in html
        assert "Stand 2026-09-29" in html

    def test_shows_csv_drift(self, settings, mock_tickers, mock_universe_df):
        uni = _universe(
            mock_tickers,
            added=[Ticker("SAX.DE", "Ströer", "MDAX")],
            removed=[Ticker("BOSS.DE", "Hugo Boss", "MDAX")],
        )
        html = self._preview(settings, uni, mock_universe_df)
        assert "Ströer (SAX.DE, MDAX)" in html
        assert "Hugo Boss (BOSS.DE, MDAX)" in html


def test_adapters_can_be_replaced_individually(recorder, mock_tickers):
    """Die DB-Tests tauschen nur Universum, Versand und Heartbeat - das muss gehen."""
    adapters = _adapters(recorder, _universe(mock_tickers), Mock())
    assert replace(adapters, sender=Mock()).batch is recorder
