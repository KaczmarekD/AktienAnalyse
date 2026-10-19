"""Yahoo-Adapter (``va_market_data.adapters.yahoo``), ohne yfinance-Netzcalls.

Die Abrufschleife testet test_fetch.py, die Kennzahlen test_metrics.py.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import date
from typing import Any
from unittest.mock import patch

import pandas as pd
import pytest
import yfinance as yf
from tenacity import wait_none
from yfinance._http import HTTPError
from yfinance.data import YfData
from yfinance.exceptions import YFRateLimitError

from va_market_data.adapters.yahoo import (
    CONSENSUS_FIELDS,
    FIELD_MAP,
    PRICE_FIELDS,
    QUARTERLY_FIELDS,
    YahooResponseError,
    _consensus_value,
    _dividend_yield,
    _fiscal_period_end,
    _latest,
    _pick,
    _statement_fx,
    _to_float,
    fetch_consensus,
    fetch_one,
    normalize_prices,
    note_rate_limit,
    price_frames,
    provider_version,
    quarterly_frames,
    share_count_series,
)
from va_market_data.domain.consensus import CONSENSUS_KINDS, ConsensusEntry
from va_market_data.domain.history import HistoryState
from va_market_data.domain.universe import Ticker

# Vor dem Patchen der Fixture gemerkt: einige Tests brauchen den echten Ablauf
REAL_FETCH_CONSENSUS = fetch_consensus


@pytest.fixture(autouse=True)
def no_consensus_network():
    """fetch_one holt zusaetzlich Konsensdaten (F1.1) - in Tests nie ueber das Netz."""
    with patch("va_market_data.adapters.yahoo.fetch_consensus", return_value={}) as fake:
        yield fake


@pytest.fixture(autouse=True)
def no_quarterly_network():
    """fetch_one holt zusaetzlich Quartalsabschluesse (F1.2) - in Tests nie ueber das Netz."""
    with patch("va_market_data.adapters.yahoo.fetch_quarterly", return_value={}) as fake:
        yield fake


@pytest.fixture(autouse=True)
def no_shares_network():
    """fetch_one holt zusaetzlich die Aktienanzahl (F1.3) - in Tests nie ueber das Netz."""
    with patch("va_market_data.adapters.yahoo.fetch_share_counts", return_value=None) as fake:
        yield fake


@pytest.fixture(autouse=True)
def no_prices_network():
    """fetch_one holt zusaetzlich die Kurshistorie (F1.4) - in Tests nie ueber das Netz."""
    with patch("va_market_data.adapters.yahoo.fetch_prices", return_value=None) as fake:
        yield fake


class _FakeQuarterlyTicker:
    """Steht fuer ``yf.Ticker`` mit Quartals-Attributen, ganz ohne Netz."""

    def __init__(self, **behaviour: Callable[[], Any]) -> None:
        self.calls: list[str] = []
        self._behaviour = behaviour

    def __getattr__(self, attr: str) -> Any:
        if attr.startswith("_"):
            raise AttributeError(attr)
        self.calls.append(attr)
        return self._behaviour[attr]()


QUARTER = pd.DataFrame({pd.Timestamp("2026-06-30"): [9_878.0]}, index=["Total Revenue"])


class TestQuarterlyFrames:
    """Der yfinance-Adapter fuer die Quartalsabschluesse (F1.2)."""

    def test_every_statement_has_a_quarterly_attribute(self):
        assert set(QUARTERLY_FIELDS) == {"income", "balance", "cashflow"}

    def test_frames_come_back_per_statement(self):
        fake = _FakeQuarterlyTicker(
            quarterly_income_stmt=lambda: QUARTER,
            quarterly_balance_sheet=pd.DataFrame,
            quarterly_cashflow=lambda: None,
        )
        frames = quarterly_frames(fake, "SAP.DE")
        assert frames["income"] is QUARTER
        assert frames["balance"] is not None
        assert frames["balance"].empty
        assert frames["cashflow"] is None

    def test_failure_costs_only_that_statement(self, caplog):
        def broken() -> Any:
            msg = "connection reset"
            raise ConnectionError(msg)

        fake = _FakeQuarterlyTicker(
            quarterly_income_stmt=broken,
            quarterly_balance_sheet=lambda: QUARTER,
            quarterly_cashflow=lambda: QUARTER,
        )
        with patch("time.sleep"):
            frames = quarterly_frames(fake, "SAP.DE")
        assert frames == {"income": None, "balance": QUARTER, "cashflow": QUARTER}
        assert fake.calls.count("quarterly_income_stmt") == 2  # ein Retry
        assert "SAP.DE" in caplog.text
        assert "income" in caplog.text

    def test_rate_limit_stops_the_remaining_statements(self):
        def throttled() -> Any:
            raise YFRateLimitError

        fake = _FakeQuarterlyTicker(
            quarterly_income_stmt=throttled,
            quarterly_balance_sheet=lambda: QUARTER,
            quarterly_cashflow=lambda: QUARTER,
        )
        assert quarterly_frames(fake, "SAP.DE") == {"income": None}
        assert fake.calls == ["quarterly_income_stmt"]  # kein Retry, nichts weiter


class _FakeTicker:
    """Steht fuer ``yf.Ticker``: verhaelt sich wie yfinance, ganz ohne Netz."""

    def __init__(self, behaviour: Callable[[], Any]) -> None:
        self.calls = 0
        self._behaviour = behaviour

    @property
    def eps_trend(self) -> Any:
        self.calls += 1
        return self._behaviour()


SHARES = pd.Series(
    [1_167_559_048, 1_154_204_232],
    index=pd.DatetimeIndex(["2026-03-11", "2026-07-29"]).tz_localize("Europe/Berlin"),
)


class _FakeSharesTicker:
    """Steht fuer ``yf.Ticker.get_shares_full``, ganz ohne Netz."""

    def __init__(self, *results: Any) -> None:
        self.starts: list[Any] = []
        self._results = list(results)

    def get_shares_full(self, start=None, end=None):
        self.starts.append(start)
        result = self._results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


class TestShareCountSeries:
    """Der yfinance-Adapter fuer die Historie der Aktienanzahl (F1.3)."""

    def test_series_comes_back_from_the_start_date(self):
        fake = _FakeSharesTicker(SHARES)
        assert share_count_series(fake, "SAP.DE", date(2000, 1, 1)) is SHARES
        assert fake.starts == [date(2000, 1, 1)]

    def test_no_series_means_no_data(self):
        assert share_count_series(_FakeSharesTicker(None), "SAP.DE", date(2000, 1, 1)) is None

    def test_failure_is_retried_once_then_logged(self, caplog):
        fake = _FakeSharesTicker(ConnectionError("reset"), ConnectionError("reset"))
        with patch("time.sleep"):
            assert share_count_series(fake, "SAP.DE", date(2000, 1, 1)) is None
        assert len(fake.starts) == 2
        assert "SAP.DE" in caplog.text

    def test_transient_failure_recovers(self):
        fake = _FakeSharesTicker(ConnectionError("reset"), SHARES)
        with patch("time.sleep"):
            assert share_count_series(fake, "SAP.DE", date(2000, 1, 1)) is SHARES

    def test_rate_limit_is_not_retried(self):
        fake = _FakeSharesTicker(YFRateLimitError(), SHARES)
        assert share_count_series(fake, "SAP.DE", date(2000, 1, 1)) is None
        assert len(fake.starts) == 1


def _bars(*days: str, split_on: str | None = None) -> pd.DataFrame:
    index = pd.DatetimeIndex(list(days)).tz_localize("Europe/Berlin")
    return pd.DataFrame(
        {
            "Close": [100.0] * len(days),
            "Adj Close": [99.0] * len(days),
            "Dividends": [0.0] * len(days),
            "Stock Splits": [3.0 if d == split_on else 0.0 for d in days],
        },
        index=index,
    )


class _FakeHistoryTicker:
    """Steht fuer ``yf.Ticker.history``, ganz ohne Netz."""

    def __init__(self, *results: Any) -> None:
        self.calls: list[dict[str, Any]] = []
        self._results = list(results)

    def history(self, **kwargs):
        self.calls.append(kwargs)
        result = self._results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


FULL = {"period": "max", "auto_adjust": False, "actions": True}


class TestNormalizePrices:
    """Die yfinance-Spaltennamen der Kurshistorie stehen nur in PRICE_FIELDS (CLAUDE.md)."""

    def test_columns_get_own_names(self):
        frame = normalize_prices(_bars("2026-07-30", split_on="2026-07-30"))
        assert frame is not None
        assert list(frame.columns) == list(PRICE_FIELDS)
        assert frame["split"].iloc[0] == 3.0

    def test_missing_column_stays_empty(self):
        frame = normalize_prices(_bars("2026-07-30").drop(columns="Adj Close"))
        assert frame is not None
        assert frame["adj_close"].isna().all()

    def test_no_data(self):
        assert normalize_prices(None) is None
        assert normalize_prices(pd.DataFrame()) is None


class TestPriceFrames:
    """Der yfinance-Adapter fuer die Kurshistorie (F1.4)."""

    def test_full_history_without_start(self):
        frame = _bars("2026-07-30", "2026-07-31")
        fake = _FakeHistoryTicker(frame)
        assert price_frames(fake, "SAP.DE", None, frozenset()) is frame
        assert fake.calls == [FULL]

    def test_window_from_start(self):
        frame = _bars("2026-07-30", "2026-07-31")
        fake = _FakeHistoryTicker(frame)
        assert price_frames(fake, "SAP.DE", date(2026, 6, 5), frozenset()) is frame
        assert fake.calls == [{"start": date(2026, 6, 5), "auto_adjust": False, "actions": True}]

    def test_new_split_in_the_window_reloads_the_full_history(self):
        """Ein Split passt alle aelteren Kurse an - die neuen Versionen sollen vollstaendig sein."""
        window = _bars("2026-07-30", "2026-07-31", split_on="2026-07-31")
        full = _bars("1998-04-09", "2026-07-30", "2026-07-31", split_on="2026-07-31")
        fake = _FakeHistoryTicker(window, full)
        assert price_frames(fake, "SAP.DE", date(2026, 6, 5), frozenset()) is full
        assert fake.calls[1] == FULL

    def test_known_split_does_not_reload(self):
        window = _bars("2026-07-30", "2026-07-31", split_on="2026-07-31")
        fake = _FakeHistoryTicker(window)
        known = frozenset({date(2026, 7, 31)})
        assert price_frames(fake, "SAP.DE", date(2026, 6, 5), known) is window
        assert len(fake.calls) == 1

    def test_failed_reload_stores_no_prices_this_week(self, caplog):
        """Sonst gaelte der Split als gespeichert, und die Altkurse blieben unbereinigt:
        Ohne Kurse bleibt der Split im naechsten Fenster und loest den Vollabruf erneut aus."""
        window = _bars("2026-07-30", "2026-07-31", split_on="2026-07-31")
        fake = _FakeHistoryTicker(window, ConnectionError("reset"), ConnectionError("reset"))
        with patch("time.sleep"):
            assert price_frames(fake, "SAP.DE", date(2026, 6, 5), frozenset()) is None
        assert "SAP.DE" in caplog.text

    def test_empty_answer_means_no_data(self):
        fake = _FakeHistoryTicker(pd.DataFrame())
        assert price_frames(fake, "SAP.DE", None, frozenset()) is None

    def test_failure_is_retried_once_then_logged(self, caplog):
        fake = _FakeHistoryTicker(ConnectionError("reset"), ConnectionError("reset"))
        with patch("time.sleep"):
            assert price_frames(fake, "SAP.DE", None, frozenset()) is None
        assert len(fake.calls) == 2
        assert "SAP.DE" in caplog.text

    def test_rate_limit_is_not_retried(self):
        fake = _FakeHistoryTicker(YFRateLimitError(), _bars("2026-07-31"))
        assert price_frames(fake, "SAP.DE", None, frozenset()) is None
        assert len(fake.calls) == 1


class _SwallowingTicker:
    """Verhaelt sich bei Fehlern wie yfinance 1.7.

    Mit ``config.debug.hide_exceptions`` (Standard) wird ein Fehler verschluckt und es
    kommt eine leere Antwort, sonst wird er geworfen.
    """

    def __init__(self, error: Exception) -> None:
        self.calls = 0
        self._error = error

    def _fail(self, empty: Any) -> Any:
        self.calls += 1
        if yf.config.debug.hide_exceptions:
            return empty
        raise self._error

    def get_shares_full(self, start=None, end=None):
        return self._fail(None)

    def history(self, **kwargs):
        return self._fail(pd.DataFrame())

    @property
    def quarterly_income_stmt(self):
        return self._fail(pd.DataFrame())

    quarterly_balance_sheet = quarterly_income_stmt
    quarterly_cashflow = quarterly_income_stmt


class TestYahooErrorsReachTheAdapters:
    """Review F1.2-F1.4: Die Zusatzabrufe sehen Fehler, die yfinance sonst verschluckt.

    Gebraucht fuer Retry, Abbruch nach Rate-Limit und Log.
    """

    def test_rate_limit_stops_the_quarters_on_the_http_level(self, caplog):
        requests: list[str] = []

        def throttled(self, url, params=None, timeout=30, **kwargs):
            requests.append(url)
            raise YFRateLimitError

        with patch.object(YfData, "get", throttled), patch("time.sleep"):
            frames = quarterly_frames(yf.Ticker("SAP.DE"), "SAP.DE")
        assert frames == {"income": None}  # Bilanz und Cashflow nicht mehr angefragt
        assert "SAP.DE" in caplog.text
        assert yf.config.debug.hide_exceptions is True  # danach wieder Standard

    def test_quarter_failure_is_retried_and_logged(self, caplog):
        fake = _SwallowingTicker(ConnectionError("reset"))
        with patch("time.sleep"):
            frames = quarterly_frames(fake, "SAP.DE")
        assert frames == {"income": None, "balance": None, "cashflow": None}
        assert fake.calls == 6  # je Abschluss ein Retry
        assert "Quartalsabschluss SAP.DE" in caplog.text

    def test_share_count_failure_is_retried_and_logged(self, caplog):
        fake = _SwallowingTicker(ConnectionError("reset"))
        with patch("time.sleep"):
            assert share_count_series(fake, "SAP.DE", date(2000, 1, 1)) is None
        assert fake.calls == 2
        assert "Aktienanzahl SAP.DE" in caplog.text

    def test_price_failure_is_retried_and_logged(self, caplog):
        fake = _SwallowingTicker(ConnectionError("reset"))
        with patch("time.sleep"):
            assert price_frames(fake, "SAP.DE", None, frozenset()) is None
        assert fake.calls == 2
        assert "Kurshistorie SAP.DE" in caplog.text

    def test_hide_exceptions_is_restored_after_a_failure(self):
        with patch("time.sleep"):
            price_frames(_SwallowingTicker(ConnectionError("reset")), "SAP.DE", None, frozenset())
        assert yf.config.debug.hide_exceptions is True


class TestConsensusSharedSource:
    """yfinance holt eps_trend, eps_revisions, earnings_estimate, revenue_estimate und
    growth_estimates aus einem gemeinsamen Abruf (earningsTrend). Scheitert er, loggt
    yfinance den Fehler nur beim ersten Zugriff - die anderen kaemen still als "empty"."""

    def _unauthorized(self, requests: list[Any]):
        class Response:
            text = "Unauthorized"
            status_code = 401

        def raw_json(self, url, params=None, timeout=30):
            requests.append(params)
            error = HTTPError("401 Client Error: Unauthorized")
            error.response = Response()
            raise error

        return raw_json

    def test_failed_shared_fetch_marks_the_group_as_error(self):
        requests: list[Any] = []
        with (
            patch.object(YfData, "get_raw_json", self._unauthorized(requests)),
            patch("time.sleep"),
        ):
            entries = REAL_FETCH_CONSENSUS("SAP.DE")
        assert requests  # der Test laeuft wirklich durch yfinance
        assert {kind: e.status for kind, e in entries.items()} == dict.fromkeys(
            CONSENSUS_KINDS, "error"
        )
        assert "Folgefehler" in (entries["eps_revisions"].error or "")

    def test_real_empty_answer_stays_empty(self):
        """Ohne Abruffehler bleibt "empty" (keine Analystenabdeckung) erhalten."""

        class NoCoverage:
            def __getattr__(self, attr):
                return None

        with patch("va_market_data.adapters.yahoo.yf.Ticker", return_value=NoCoverage()):
            entries = REAL_FETCH_CONSENSUS("SAP.DE")
        assert {e.status for e in entries.values()} == {"empty"}

    def test_error_of_a_single_kind_is_no_follow_up_error(self):
        """Ein Fehler beim Parsen einer Art betrifft nicht die anderen der Gruppe."""

        class OneBroken:
            def __getattr__(self, attr):
                if attr == "eps_revisions":
                    raise KeyError("trend")

        with (
            patch("va_market_data.adapters.yahoo.yf.Ticker", return_value=OneBroken()),
            patch("time.sleep"),
        ):
            entries = REAL_FETCH_CONSENSUS("SAP.DE")
        assert entries["eps_revisions"].status == "error"
        assert entries["eps_trend"].status == "empty"


class TestConsensusValue:
    """Der yfinance-Adapter fuer die Konsens-Snapshots (F1.1)."""

    def test_every_stored_kind_has_a_yfinance_attribute(self):
        assert set(CONSENSUS_FIELDS) == set(CONSENSUS_KINDS)

    def test_http_error_swallowed_by_yfinance_becomes_an_error(self):
        """yfinance loggt 401/404/5xx nur und liefert leer - das ist kein 'keine Daten'."""

        def swallowed() -> pd.DataFrame:
            logging.getLogger("yfinance").error("HTTP Error 401: Invalid Crumb")
            return pd.DataFrame()

        fake = _FakeTicker(swallowed)
        with pytest.raises(YahooResponseError, match="Invalid Crumb"):
            _consensus_value(fake, "eps_trend")
        assert fake.calls == 1  # Wiederholen hilft nicht, yfinance hat das Ergebnis gecacht

    def test_logged_error_with_data_keeps_the_data(self):
        frame = pd.DataFrame({"current": [1.0]}, index=["0y"])

        def noisy_but_ok() -> pd.DataFrame:
            logging.getLogger("yfinance").error("irrelevant")
            return frame

        assert _consensus_value(_FakeTicker(noisy_but_ok), "eps_trend") is frame

    def test_rate_limit_is_not_retried(self):
        def throttled() -> Any:
            raise YFRateLimitError

        fake = _FakeTicker(throttled)
        with pytest.raises(YFRateLimitError):
            _consensus_value(fake, "eps_trend")
        assert fake.calls == 1

    def test_other_failures_are_retried_once(self):
        frame = pd.DataFrame({"current": [1.0]}, index=["0y"])
        outcomes: list[Any] = [ConnectionError("reset"), frame]

        def flaky() -> Any:
            outcome = outcomes.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        fake = _FakeTicker(flaky)
        no_wait = _consensus_value.retry_with(wait=wait_none())  # type: ignore[attr-defined]
        assert no_wait(fake, "eps_trend") is frame
        assert fake.calls == 2


class TestToFloat:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [(3.5, 3.5), (5, 5.0), (None, None), (float("nan"), None), (float("inf"), None)],
    )
    def test_cases(self, value, expected):
        assert _to_float(value) == expected

    def test_garbage_returns_none(self):
        assert _to_float("not a number") is None


class TestDividendYield:
    """Eigenheit von yfinance: dividendYield in Prozent, trailingAnnualDividendYield dezimal."""

    def test_prefers_trailing_decimal(self):
        info = {"trailingAnnualDividendYield": 0.0136, "dividendYield": 1.36}
        assert _dividend_yield(info) == pytest.approx(0.0136)

    def test_percent_fallback_below_one_percent(self):
        # 0.8 bedeutet 0,8 % - nicht 80 %
        assert _dividend_yield({"dividendYield": 0.8}) == pytest.approx(0.008)

    def test_percent_fallback_above_one_percent(self):
        assert _dividend_yield({"dividendYield": 4.02}) == pytest.approx(0.0402)

    def test_zero_trailing_is_kept(self):
        assert _dividend_yield({"trailingAnnualDividendYield": 0.0}) == 0.0

    def test_missing_returns_none(self):
        assert _dividend_yield({}) is None


class TestFiscalPeriodEnd:
    # Die Regel, was ein Periodenende ist, testet test_serialization (period_end)
    @pytest.mark.parametrize("bad_label", [None, "NaT", "keine Periode", 0])
    def test_skips_invalid_label_of_latest_revenue(self, bad_label):
        income = pd.DataFrame(
            {
                bad_label: [3_000.0],
                pd.Timestamp("2025-12-31"): [2_000.0],
                pd.Timestamp("2024-12-31"): [1_900.0],
            },
            index=["Total Revenue"],
        )
        assert _fiscal_period_end(income) == date(2025, 12, 31)

    def test_fallback_without_revenue_skips_invalid_label(self):
        income = pd.DataFrame(
            {None: [100.0], pd.Timestamp("2025-12-31"): [80.0]},
            index=["Net Income"],
        )
        assert _fiscal_period_end(income) == date(2025, 12, 31)


class TestPick:
    def test_finds_first_match(self):
        df = pd.DataFrame({0: [100, 200]}, index=["Total Revenue", "Cost"])
        s = _pick(df, "revenue")
        assert s is not None
        assert s.iloc[0] == 100

    def test_case_insensitive(self):
        df = pd.DataFrame({0: [50]}, index=["total revenue"])
        s = _pick(df, "revenue")
        assert s is not None

    def test_returns_none_when_missing(self):
        df = pd.DataFrame({0: [1]}, index=["Something Else"])
        assert _pick(df, "revenue") is None

    def test_empty_df_returns_none(self):
        assert _pick(pd.DataFrame(), "revenue") is None
        assert _pick(None, "revenue") is None


class TestLatest:
    def test_returns_first_non_nan(self):
        s = pd.Series([100.0, 90.0, 80.0])
        assert _latest(s) == 100.0

    def test_skips_leading_nan(self):
        s = pd.Series([float("nan"), 90.0])
        assert _latest(s) == 90.0

    def test_empty(self):
        assert _latest(pd.Series([], dtype=float)) is None
        assert _latest(None) is None


class TestFieldMap:
    def test_all_keys_have_at_least_one_candidate(self):
        for key, candidates in FIELD_MAP.items():
            assert len(candidates) >= 1, f"Field {key} has no candidates"
            assert all(isinstance(c, str) for c in candidates)


def _statement(values: dict[str, float]) -> pd.DataFrame:
    return pd.DataFrame({"2025-12-31": values})


class TestStatementFx:
    def test_same_currency_is_one(self):
        assert _statement_fx({"currency": "EUR", "financialCurrency": "EUR"}, []) == 1.0

    def test_unknown_currency_is_one(self):
        assert _statement_fx({"currency": "EUR"}, []) == 1.0

    def test_mismatch_uses_fx_rate(self):
        with patch("va_market_data.adapters.yahoo._fx_rate", return_value=0.9) as fx_rate:
            fx = _statement_fx({"currency": "EUR", "financialCurrency": "USD"}, [])
        assert fx == 0.9
        fx_rate.assert_called_once_with("USD", "EUR")

    def test_fx_failure_returns_none_and_logs_error(self):
        errors: list[str] = []
        with patch("va_market_data.adapters.yahoo._fx_rate", side_effect=ValueError("down")):
            fx = _statement_fx({"currency": "EUR", "financialCurrency": "USD"}, errors)
        assert fx is None
        assert errors
        assert "USD->EUR" in errors[0]


# Qiagen-Fall: Kurs/Marktkapitalisierung in EUR, Abschluss in USD.
QIAGEN_INFO = {
    "currency": "EUR",
    "financialCurrency": "USD",
    "marketCap": 8_000.0,
    "enterpriseValue": 9_000.0,  # von Yahoo unkonvertiert gemischt
    "priceToBook": 2.76,  # EUR-Kurs / USD-Buchwert
    "trailingPE": 99.0,
}


class TestFetchOneCurrencyMismatch:
    """Qiagen-Fall: Kurs/Marktkapitalisierung in EUR, Abschluss in USD."""

    INCOME = _statement({"Total Revenue": 2_000.0, "EBIT": 500.0, "Net Income": 400.0})
    BALANCE = _statement(
        {"Stockholders Equity": 3_000.0, "Total Debt": 1_600.0, "Cash And Cash Equivalents": 600.0}
    )
    CASHFLOW = _statement({"Free Cash Flow": 400.0, "Repurchase Of Capital Stock": -200.0})

    def _fetch(self, fx_rate):
        data = (QIAGEN_INFO, self.INCOME, self.BALANCE, self.CASHFLOW)
        with (
            patch("va_market_data.adapters.yahoo._ticker_data", return_value=data),
            patch("va_market_data.adapters.yahoo._fx_rate", **fx_rate),
        ):
            return fetch_one(Ticker("QIA.DE", "Qiagen", "MDAX"))

    def test_value_multiples_use_converted_statements(self):
        f = self._fetch({"return_value": 0.8})
        assert f.identity.financial_currency == "USD"
        # EV = 8000 + (1600 - 600) * 0.8 = 8800, EBIT = 500 * 0.8 = 400
        assert f.market.enterprise_value == pytest.approx(8_800.0)
        assert f.value.ev_ebit == pytest.approx(22.0)
        assert f.value.pb_ratio == pytest.approx(8_000.0 / 2_400.0)
        assert f.value.p_fcf == pytest.approx(8_000.0 / 320.0)
        assert f.value.pe_ratio == pytest.approx(8_000.0 / 320.0)
        assert f.value.buyback_yield == pytest.approx(160.0 / 8_000.0)

    def test_quality_ratios_unaffected_by_fx(self):
        f = self._fetch({"return_value": 0.8})
        assert f.quality.fcf_margin == pytest.approx(0.2)
        assert f.quality.debt_to_equity == pytest.approx(1_600.0 / 3_000.0)

    def test_fx_failure_drops_mixed_multiples(self):
        f = self._fetch({"side_effect": ValueError("down")})
        assert f.value.ev_ebit is None
        assert f.value.pb_ratio is None
        assert f.value.p_fcf is None
        assert f.quality.fcf_margin == pytest.approx(0.2)
        assert any("fx" in e for e in f.errors)


class TestFetchOneShareholderYield:
    INCOME = _statement({"Total Revenue": 1_000.0, "EBIT": 100.0})

    def _fetch(self, info, cashflow):
        data = (
            {"currency": "EUR", "financialCurrency": "EUR", **info},
            self.INCOME,
            None,
            cashflow,
        )
        with patch("va_market_data.adapters.yahoo._ticker_data", return_value=data):
            return fetch_one(Ticker("X.DE", "X", "MDAX"))

    def test_zero_yield_is_kept(self):
        f = self._fetch(
            {"marketCap": 1_000.0, "trailingAnnualDividendYield": 0.0},
            _statement({"Free Cash Flow": 50.0}),
        )
        assert f.value.shareholder_yield == 0.0

    def test_missing_components_give_none(self):
        f = self._fetch({"marketCap": 1_000.0}, _statement({"Free Cash Flow": 50.0}))
        assert f.value.shareholder_yield is None


class TestFetchOneProvenanceAndRaw:
    INCOME = pd.DataFrame(
        {
            pd.Timestamp("2025-12-31"): [2_000.0, 500.0],
            pd.Timestamp("2024-12-31"): [1_900.0, 450.0],
        },
        index=["Total Revenue", "EBIT"],
    )

    def _fetch(self, income=None, side_effect=None, history=None):
        data = (
            {"currency": "EUR", "financialCurrency": "EUR", "marketCap": 1_000.0},
            self.INCOME if income is None else income,
            None,
            None,
        )
        kwargs: dict[str, Any] = (
            {"side_effect": side_effect} if side_effect else {"return_value": data}
        )
        with patch("va_market_data.adapters.yahoo._ticker_data", **kwargs):
            return fetch_one(Ticker("X.DE", "X", "DAX"), history=history)

    def test_raw_data_is_kept(self):
        f = self._fetch()
        assert f.raw is not None
        assert f.raw.provider == "yfinance"
        assert f.raw.provider_version == provider_version()
        assert f.raw.info["marketCap"] == 1_000.0
        assert f.raw.statements["income"] is self.INCOME
        assert set(f.raw.statements) == {"income", "balance", "cashflow"}

    def test_provenance_is_set(self):
        f = self._fetch()
        assert f.provenance.fetched_at is not None
        assert f.provenance.fetched_at.tzinfo is not None
        assert f.provenance.fiscal_period_end == date(2025, 12, 31)
        assert f.provenance.statement_fx == 1.0

    def test_fiscal_period_skips_empty_latest_column(self):
        income = pd.DataFrame(
            {pd.Timestamp("2026-12-31"): [float("nan")], pd.Timestamp("2025-12-31"): [2_000.0]},
            index=["Total Revenue"],
        )
        assert self._fetch(income).provenance.fiscal_period_end == date(2025, 12, 31)

    def test_string_period_labels_are_parsed(self):
        income = _statement({"Total Revenue": 2_000.0})
        assert self._fetch(income).provenance.fiscal_period_end == date(2025, 12, 31)

    def test_failed_fetch_has_timestamp_but_no_raw(self, no_consensus_network):
        f = self._fetch(side_effect=RuntimeError("down"))
        assert f.raw is None
        assert f.provenance.fetched_at is not None
        assert f.errors
        no_consensus_network.assert_not_called()

    def test_consensus_is_kept_without_touching_errors(self, no_consensus_network):
        """ADR-0010: Zusatzdaten nur speichern - Snapshot-Fehler und CSV bleiben gleich."""
        entries = {"eps_trend": ConsensusEntry("error", None, "RuntimeError: 429")}
        no_consensus_network.return_value = entries
        f = self._fetch()
        no_consensus_network.assert_called_once_with("X.DE")
        assert f.raw is not None
        assert f.raw.consensus == entries
        assert f.errors == []

    def test_quarterly_statements_are_kept_raw(self, no_quarterly_network):
        """F1.2: Quartale werden nur gespeichert - Kennzahlen und CSV bleiben gleich."""
        no_quarterly_network.return_value = {"income": QUARTER, "cashflow": None}
        f = self._fetch()
        no_quarterly_network.assert_called_once_with("X.DE")
        assert f.raw is not None
        assert f.raw.quarterly == {"income": QUARTER, "cashflow": None}
        assert f.errors == []

    def test_failed_base_fetch_skips_the_quarters(self, no_quarterly_network):
        self._fetch(side_effect=RuntimeError("down"))
        no_quarterly_network.assert_not_called()

    def test_share_counts_start_in_2000_without_history(self, no_shares_network):
        """F1.3: Beim ersten Abruf die ganze Historie - nur gespeichert, nicht ausgewertet."""
        no_shares_network.return_value = SHARES
        f = self._fetch()
        no_shares_network.assert_called_once_with("X.DE", date(2000, 1, 1))
        assert f.raw is not None
        assert f.raw.shares is SHARES
        assert f.errors == []

    def test_share_counts_continue_from_the_last_stored_day(self, no_shares_network):
        self._fetch(history=HistoryState(last_share_date=date(2026, 7, 29)))
        no_shares_network.assert_called_once_with("X.DE", date(2026, 7, 29))

    def test_missing_share_counts_cost_nothing(self, no_shares_network):
        no_shares_network.return_value = None
        f = self._fetch()
        assert f.raw is not None
        assert f.raw.shares is None
        assert f.errors == []

    def test_failed_base_fetch_skips_the_share_counts(self, no_shares_network):
        self._fetch(side_effect=RuntimeError("down"))
        no_shares_network.assert_not_called()

    def test_prices_start_with_the_full_history(self, no_prices_network):
        """F1.4: Beim ersten Abruf die ganze Kurshistorie - nur gespeichert, nicht ausgewertet."""
        frame = _bars("2026-07-30", "2026-07-31")
        no_prices_network.return_value = frame
        f = self._fetch()
        no_prices_network.assert_called_once_with("X.DE", None, frozenset())
        assert f.raw is not None
        assert f.raw.prices is frame
        assert f.errors == []

    def test_prices_overlap_eight_weeks_with_the_stored_history(self, no_prices_network):
        """Ab dem letzten Tag minus 8 Wochen (~40 Handelstage): Korrekturen und Luecken."""
        splits = frozenset({date(2000, 6, 26)})
        state = HistoryState(last_price_date=date(2026, 7, 31), price_split_days=splits)
        self._fetch(history=state)
        no_prices_network.assert_called_once_with("X.DE", date(2026, 6, 5), splits)

    def test_failed_base_fetch_skips_the_prices(self, no_prices_network):
        self._fetch(side_effect=RuntimeError("down"))
        no_prices_network.assert_not_called()


class TestRateLimitPerTicker:
    """Review F1.2-F1.4: Nach einem Rate-Limit bleibt der Rest des Titels aus.

    Sonst liefen die uebrigen Zusatzabrufe weiter in die Drosselung.
    """

    def _fetch(self, symbol="X.DE"):
        info = {"currency": "EUR", "financialCurrency": "EUR", "marketCap": 1_000.0}
        with patch(
            "va_market_data.adapters.yahoo._ticker_data", return_value=(info, None, None, None)
        ):
            return fetch_one(Ticker(symbol, "X", "DAX"))

    def test_rate_limit_in_the_consensus_skips_the_rest(
        self, no_consensus_network, no_quarterly_network, no_shares_network, no_prices_network
    ):
        def throttled(symbol):
            note_rate_limit(YFRateLimitError())
            return {}

        no_consensus_network.side_effect = throttled
        f = self._fetch()
        no_quarterly_network.assert_not_called()
        no_shares_network.assert_not_called()
        no_prices_network.assert_not_called()
        assert f.raw is not None
        assert (f.raw.quarterly, f.raw.shares, f.raw.prices) == ({}, None, None)
        assert f.errors == []  # die CSV bleibt gleich

    def test_rate_limit_in_the_consensus_is_noticed(
        self, no_consensus_network, no_quarterly_network, no_prices_network
    ):
        """Verdrahtung: fetch_consensus meldet das Rate-Limit an den Waechter."""

        class Throttled:
            def __getattr__(self, attr):
                raise YFRateLimitError

        no_consensus_network.side_effect = REAL_FETCH_CONSENSUS
        with patch("va_market_data.adapters.yahoo.yf.Ticker", return_value=Throttled()):
            self._fetch()
        no_quarterly_network.assert_not_called()
        no_prices_network.assert_not_called()

    def test_rate_limit_in_the_share_counts_skips_the_prices(
        self, no_shares_network, no_prices_network
    ):
        def throttled(symbol, start):
            note_rate_limit(YFRateLimitError())

        no_shares_network.side_effect = throttled
        self._fetch()
        no_prices_network.assert_not_called()

    @pytest.mark.parametrize(
        "fetcher",
        ["no_consensus_network", "no_quarterly_network", "no_shares_network", "no_prices_network"],
    )
    def test_unexpected_error_in_additional_data_keeps_the_ticker(self, request, fetcher):
        """ADR-0010: Wegen Zusatzdaten geht kein Titel verloren - auch nicht bei einem Bug."""
        request.getfixturevalue(fetcher).side_effect = KeyError("unerwartet")
        f = self._fetch()
        assert f.raw is not None
        assert f.market.market_cap == 1_000.0
        assert f.errors == []

    def test_rate_limit_in_the_quarters_skips_shares_and_prices(
        self, no_quarterly_network, no_shares_network, no_prices_network
    ):
        throttled = _FakeQuarterlyTicker(quarterly_income_stmt=_raise(YFRateLimitError()))
        no_quarterly_network.side_effect = lambda symbol: quarterly_frames(throttled, symbol)
        self._fetch()
        no_shares_network.assert_not_called()
        no_prices_network.assert_not_called()

    def test_next_ticker_starts_fresh(self, no_consensus_network, no_quarterly_network):
        def throttled(symbol):
            note_rate_limit(YFRateLimitError())
            return {}

        no_consensus_network.side_effect = throttled
        self._fetch("A.DE")
        no_consensus_network.side_effect = None
        self._fetch("B.DE")
        no_quarterly_network.assert_called_once_with("B.DE")

    def test_other_errors_do_not_count(self):
        assert note_rate_limit(ConnectionError("reset")) is False
        assert note_rate_limit(YFRateLimitError()) is True


def _raise(error: Exception) -> Callable[[], Any]:
    def fail() -> Any:
        raise error

    return fail


class TestFetchOneInvalidPeriods:
    """Spalten ohne Periodenende zaehlen fuer keine Kennzahl - wie in statement_value.

    Sonst stuenden im Snapshot Kennzahlen aus Werten, die nicht gespeichert werden
    und sich aus der Historie nicht nachrechnen lassen.
    """

    # Die undatierte Spalte steht vorn und haette sonst Vorrang als juengste Periode
    INCOME = pd.DataFrame(
        {
            None: [9_000.0, 9_000.0],
            pd.Timestamp("2025-12-31"): [2_000.0, 500.0],
            pd.Timestamp("2024-12-31"): [1_900.0, 450.0],
        },
        index=["Total Revenue", "Operating Income"],
    )

    def _fetch(self, income):
        info = {"currency": "EUR", "financialCurrency": "EUR", "marketCap": 1_000.0}
        with patch(
            "va_market_data.adapters.yahoo._ticker_data", return_value=(info, income, None, None)
        ):
            return fetch_one(Ticker("X.DE", "X", "DAX"))

    def test_metrics_ignore_undated_columns(self):
        f = self._fetch(self.INCOME)
        assert f.quality.operating_margin == pytest.approx(0.25)
        assert f.provenance.fiscal_period_end == date(2025, 12, 31)

    def test_raw_statements_stay_unchanged(self):
        f = self._fetch(self.INCOME)
        assert f.raw is not None
        assert f.raw.statements["income"] is self.INCOME

    def test_numeric_column_labels_give_no_metrics_but_an_error(self):
        # z. B. RangeIndex nach einem Formatwechsel bei yfinance: keine Periode, keine Werte
        income = pd.DataFrame(
            {0: [2_000.0, 500.0], 1: [1_900.0, 450.0]},
            index=["Total Revenue", "Operating Income"],
        )
        f = self._fetch(income)
        assert f.quality.operating_margin is None
        assert f.provenance.fiscal_period_end is None
        assert any("income" in e and "Periodenende" in e for e in f.errors)
