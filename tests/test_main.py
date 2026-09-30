"""Integrationstests fuer den Batch-Orchestrator (src/main.py).

Alle externen Grenzen werden gemockt:
- fetch_all   → gibt mock_universe_df zurueck (kein yfinance-Netz)
- load_universe → gibt ein festes Universe (Quelle iShares) zurueck
- send_report → prueft Aufruf ohne echten SMTP
- ping        → prueft Healthcheck-Aufruf

Damit laeuft der komplette _run()-Pfad durch, einschliesslich
Scoring, Report-Bau, Dry-Run-Modus und Fehlerbehandlung.
"""

from __future__ import annotations

from datetime import date
from unittest.mock import patch

import pandas as pd
import pytest

from src.main import _run, _try_send_error_mail, run
from src.reporting import build_report
from src.universe import Ticker, Universe


def _universe(tickers, **kwargs):
    return Universe(tickers=tickers, source="iShares", as_of=date(2026, 9, 29), **kwargs)


# ---------------------------------------------------------------------------
# Hilfs-Fixture: minimale Settings ohne .env-Datei
# ---------------------------------------------------------------------------


@pytest.fixture
def settings(tmp_path, monkeypatch):
    monkeypatch.setenv("SMTP_USER", "test@gmail.com")
    monkeypatch.setenv("SMTP_PASSWORD", "dummy-app-pw")
    monkeypatch.setenv("MAIL_TO", "recipient@example.com")
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


# ---------------------------------------------------------------------------
# _run() - Happy Path: Dry-Run
# ---------------------------------------------------------------------------


class TestRunDryRun:
    def test_dry_run_returns_zero(self, settings, mock_tickers, mock_universe_df):
        with (
            patch("src.main.load_universe", return_value=_universe(mock_tickers)),
            patch("src.main.fetch_all", return_value=mock_universe_df),
            patch("src.main.send_report") as mock_send,
            patch("src.main.ping") as mock_ping,
        ):
            rc = _run(settings, force_refresh=False, dry_run=True)

        assert rc == 0
        mock_send.assert_not_called()  # Dry-Run versendet keine Mail
        mock_ping.assert_not_called()  # Dry-Run pingt nicht

    def test_dry_run_writes_html_preview(self, settings, mock_tickers, mock_universe_df):
        with (
            patch("src.main.load_universe", return_value=_universe(mock_tickers)),
            patch("src.main.fetch_all", return_value=mock_universe_df),
            patch("src.main.send_report"),
            patch("src.main.ping"),
        ):
            _run(settings, force_refresh=False, dry_run=True)

        preview = settings.data_dir / "preview_latest.html"
        assert preview.exists()
        content = preview.read_text(encoding="utf-8")
        assert "<!DOCTYPE" in content
        assert "Value-Screening" in content

    def test_dry_run_writes_csv(self, settings, mock_tickers, mock_universe_df):
        with (
            patch("src.main.load_universe", return_value=_universe(mock_tickers)),
            patch("src.main.fetch_all", return_value=mock_universe_df),
            patch("src.main.send_report"),
            patch("src.main.ping"),
        ):
            _run(settings, force_refresh=False, dry_run=True)

        csv_files = list(settings.data_dir.glob("value_ranking_*.csv"))
        assert len(csv_files) == 1


# ---------------------------------------------------------------------------
# _run() - Happy Path: echter Lauf mit Mail
# ---------------------------------------------------------------------------


class TestRunWithMail:
    def test_real_run_calls_send_report(self, settings, mock_tickers, mock_universe_df):
        with (
            patch("src.main.load_universe", return_value=_universe(mock_tickers)),
            patch("src.main.fetch_all", return_value=mock_universe_df),
            patch("src.main.send_report") as mock_send,
            patch("src.main.ping"),
        ):
            rc = _run(settings, force_refresh=False, dry_run=False)

        assert rc == 0
        mock_send.assert_called_once()
        call_kwargs = mock_send.call_args
        # Erstes Argument ist das Settings-Objekt
        assert call_kwargs.args[0] is settings

    def test_real_run_pings_success(self, settings, mock_tickers, mock_universe_df):
        with (
            patch("src.main.load_universe", return_value=_universe(mock_tickers)),
            patch("src.main.fetch_all", return_value=mock_universe_df),
            patch("src.main.send_report"),
            patch("src.main.ping") as mock_ping,
        ):
            _run(settings, force_refresh=False, dry_run=False)

        mock_ping.assert_called_once()
        _, kwargs = mock_ping.call_args
        assert kwargs["success"] is True

    def test_subject_contains_stats(self, settings, mock_tickers, mock_universe_df):
        with (
            patch("src.main.load_universe", return_value=_universe(mock_tickers)),
            patch("src.main.fetch_all", return_value=mock_universe_df),
            patch("src.main.send_report") as mock_send,
            patch("src.main.ping"),
        ):
            _run(settings, force_refresh=False, dry_run=False)

        subject_arg = mock_send.call_args.args[1]
        # Betreff muss Score/Universum-Statistik enthalten
        assert "/" in subject_arg


# ---------------------------------------------------------------------------
# _run() - DAX_ONLY-Filter
# ---------------------------------------------------------------------------


class TestRunDaxOnly:
    def test_dax_only_filters_mdax_tickers(self, settings, mock_tickers, mock_universe_df):
        dax_only_settings = settings.model_copy(update={"universe": "DAX_ONLY"})

        captured: list[list[Ticker]] = []

        def fake_fetch_all(tickers, **kwargs):
            captured.append(tickers)
            # Nur DAX-Ticker aus dem mock_universe_df zurueckgeben
            dax_symbols = {t.symbol for t in tickers}
            return mock_universe_df[mock_universe_df["symbol"].isin(dax_symbols)].copy()

        with (
            patch("src.main.load_universe", return_value=_universe(mock_tickers)),
            patch("src.main.fetch_all", side_effect=fake_fetch_all),
            patch("src.main.send_report"),
            patch("src.main.ping"),
        ):
            rc = _run(dax_only_settings, force_refresh=False, dry_run=True)

        assert rc == 0
        passed_tickers = captured[0]
        assert all(t.index == "DAX" for t in passed_tickers)
        # MDAX-Ticker duerfen nicht dabei sein
        passed_symbols = {t.symbol for t in passed_tickers}
        assert "TRAP.DE" not in passed_symbols  # MDAX
        assert "VAL.DE" in passed_symbols  # DAX


# ---------------------------------------------------------------------------
# _run() - Fehlerbehandlung
# ---------------------------------------------------------------------------


class TestRunErrorHandling:
    def test_no_scoreable_data_returns_code_3(self, settings, mock_tickers):
        empty_df = pd.DataFrame(
            columns=["symbol", "name", "index", "market_cap", "composite_score"]
        )

        with (
            patch("src.main.load_universe", return_value=_universe(mock_tickers)),
            patch("src.main.fetch_all", return_value=empty_df),
            patch("src.main.score", return_value=empty_df),
            patch("src.main.ping") as mock_ping,
        ):
            rc = _run(settings, force_refresh=False, dry_run=False)

        assert rc == 3
        mock_ping.assert_called_once()
        _, kwargs = mock_ping.call_args
        assert kwargs["success"] is False

    def test_exception_in_fetch_returns_code_1(self, settings, mock_tickers):
        with (
            patch("src.main.load_universe", return_value=_universe(mock_tickers)),
            patch("src.main.fetch_all", side_effect=RuntimeError("yfinance down")),
            patch("src.main.ping") as mock_ping,
            patch("src.main._try_send_error_mail"),
        ):
            rc = _run(settings, force_refresh=False, dry_run=False)

        assert rc == 1
        mock_ping.assert_called_once()
        _, kwargs = mock_ping.call_args
        assert kwargs["success"] is False

    def test_exception_in_dry_run_does_not_send_error_mail(self, settings, mock_tickers):
        with (
            patch("src.main.load_universe", return_value=_universe(mock_tickers)),
            patch("src.main.fetch_all", side_effect=RuntimeError("boom")),
            patch("src.main.ping"),
            patch("src.main._try_send_error_mail") as mock_err_mail,
        ):
            _run(settings, force_refresh=False, dry_run=True)

        mock_err_mail.assert_not_called()

    def test_exception_in_real_run_sends_error_mail(self, settings, mock_tickers):
        with (
            patch("src.main.load_universe", return_value=_universe(mock_tickers)),
            patch("src.main.fetch_all", side_effect=RuntimeError("crash")),
            patch("src.main.ping"),
            patch("src.main._try_send_error_mail") as mock_err_mail,
        ):
            _run(settings, force_refresh=False, dry_run=False)

        mock_err_mail.assert_called_once()
        # Traceback muss uebergeben worden sein
        traceback_arg = mock_err_mail.call_args.args[1]
        assert "RuntimeError" in traceback_arg

    def test_error_mail_escapes_traceback(self, settings):
        trace = "ValueError: <b>kaputt</b> & mehr"
        with patch("src.main.send_report") as mock_send:
            _try_send_error_mail(settings, trace)

        body = mock_send.call_args.args[2]
        assert "&lt;b&gt;kaputt&lt;/b&gt; &amp; mehr" in body
        assert "<b>kaputt</b>" not in body


# ---------------------------------------------------------------------------
# run() - Config-Fehler (oeffentliche Einstiegsfunktion)
# ---------------------------------------------------------------------------


class TestRunConfigError:
    def test_missing_env_returns_code_2(self, monkeypatch, tmp_path):
        monkeypatch.delenv("SMTP_USER", raising=False)
        monkeypatch.delenv("SMTP_PASSWORD", raising=False)
        monkeypatch.delenv("MAIL_TO", raising=False)
        monkeypatch.chdir(tmp_path)

        rc = run()
        assert rc == 2

    def test_valid_env_does_not_return_code_2(self, monkeypatch, tmp_path, mock_universe_df):
        monkeypatch.setenv("SMTP_USER", "test@gmail.com")
        monkeypatch.setenv("SMTP_PASSWORD", "dummy")
        monkeypatch.setenv("MAIL_TO", "r@example.com")
        monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
        monkeypatch.setenv("LOGS_DIR", str(tmp_path / "logs"))
        monkeypatch.chdir(tmp_path)

        with (
            patch("src.main.load_universe", return_value=_universe([])),
            patch(
                "src.main.fetch_all",
                return_value=pd.DataFrame(columns=["symbol", "market_cap", "composite_score"]),
            ),
            patch(
                "src.main.score",
                return_value=pd.DataFrame(columns=["symbol", "market_cap", "composite_score"]),
            ),
            patch("src.main.ping"),
        ):
            rc = run(dry_run=True)

        assert rc == 3  # Config gueltig, aber leeres Universum -> "keine bewertbaren Daten"


# ---------------------------------------------------------------------------
# force_refresh wird durchgereicht
# ---------------------------------------------------------------------------


class TestForceRefresh:
    def test_force_refresh_passed_to_fetch_all(self, settings, mock_tickers, mock_universe_df):
        captured: dict = {}

        def fake_fetch_all(tickers, *, cache_dir, force_refresh, cfg):
            captured["force_refresh"] = force_refresh
            return mock_universe_df

        with (
            patch("src.main.load_universe", return_value=_universe(mock_tickers)),
            patch("src.main.fetch_all", side_effect=fake_fetch_all),
            patch("src.main.send_report"),
            patch("src.main.ping"),
        ):
            _run(settings, force_refresh=True, dry_run=True)

        assert captured["force_refresh"] is True


# ---------------------------------------------------------------------------
# Indexquelle im Report
# ---------------------------------------------------------------------------


class TestUniverseSourceInReport:
    def _build_report_kwargs(self, settings, universe, mock_universe_df):
        with (
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
