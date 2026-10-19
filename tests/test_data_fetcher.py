"""Tests fuer Helper-Funktionen in data_fetcher (ohne yfinance-Netzcalls)."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import date
from typing import Any
from unittest.mock import patch

import pandas as pd
import pytest
from src.history import HistoryState
from tenacity import wait_none
from yfinance.exceptions import YFRateLimitError

from src.consensus import CONSENSUS_KINDS, ConsensusEntry
from src.data_fetcher import (
    CONSENSUS_FIELDS,
    FIELD_MAP,
    QUARTERLY_FIELDS,
    FetcherConfig,
    YahooResponseError,
    _cagr,
    _consensus_value,
    _dividend_yield,
    _earnings_stability,
    _f,
    _fiscal_period_end,
    _latest,
    _pick,
    _roic,
    _safe_div,
    _statement_fx,
    fetch_all,
    fetch_one,
    provider_version,
    quarterly_frames,
    share_count_series,
    success_share,
)
from src.fundamentals import Fundamentals, Identity, MarketData
from src.universe import Ticker


@pytest.fixture(autouse=True)
def no_consensus_network():
    """fetch_one holt zusaetzlich Konsensdaten (F1.1) - in Tests nie ueber das Netz."""
    with patch("src.data_fetcher.fetch_consensus", return_value={}) as fake:
        yield fake


@pytest.fixture(autouse=True)
def no_quarterly_network():
    """fetch_one holt zusaetzlich Quartalsabschluesse (F1.2) - in Tests nie ueber das Netz."""
    with patch("src.data_fetcher.fetch_quarterly", return_value={}) as fake:
        yield fake


@pytest.fixture(autouse=True)
def no_shares_network():
    """fetch_one holt zusaetzlich die Aktienanzahl (F1.3) - in Tests nie ueber das Netz."""
    with patch("src.data_fetcher.fetch_share_counts", return_value=None) as fake:
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


class TestSafeDiv:
    @pytest.mark.parametrize(
        ("num", "den", "expected"),
        [
            (10.0, 2.0, 5.0),
            (None, 5.0, None),
            (5.0, None, None),
            (5.0, 0.0, None),
            (float("inf"), 1.0, None),
            (1.0, float("nan"), None),
            # Ueberlauf: endliche Eingaben, Ergebnis inf - darf nicht ins Ranking
            (1e308, 1e-10, None),
        ],
    )
    def test_cases(self, num, den, expected):
        result = _safe_div(num, den)
        assert result == expected


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


class TestF:
    def test_passes_through_floats(self):
        assert _f(3.5) == 3.5

    def test_handles_int(self):
        assert _f(5) == 5.0

    def test_none_returns_none(self):
        assert _f(None) is None

    def test_nan_returns_none(self):
        assert _f(float("nan")) is None

    def test_inf_returns_none(self):
        assert _f(float("inf")) is None

    def test_garbage_returns_none(self):
        assert _f("not a number") is None


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


class TestCagr:
    def test_basic(self):
        # 100 -> 90 -> 80 -> 70 -> 60 (juengstes zuerst)
        # 5 Jahre Wachstum von 60 auf 100: (100/60)^(1/4)-1 ~ 0.1362
        result = _cagr([100, 90, 80, 70, 60])
        assert result is not None
        assert 0.13 < result < 0.14

    def test_sign_change_returns_none(self):
        # Vorzeichenwechsel -> CAGR ist mathematisch undefiniert
        assert _cagr([100, 50, 0, -50, -100]) is None

    def test_too_short(self):
        assert _cagr([100]) is None
        assert _cagr([]) is None

    def test_overflow_returns_none(self):
        # Aeltester Wert fast 0: first/last laeuft ueber (inf) - kein Wachstumswert
        assert _cagr([5e9, 4e9, 3e9, 2e9, 1e-300]) is None


class TestDividendYield:
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


class TestRoic:
    def test_with_effective_tax_rate(self):
        # EBIT=100, pretax=80, tax=20 -> effective_tax=0.25
        # NOPAT = 100 * 0.75 = 75; invested = 500+100 = 600; ROIC = 0.125
        result = _roic(ebit=100, equity=500, debt=100, pretax=80, tax=20, default_tax_rate=0.27)
        assert result is not None
        assert abs(result - 0.125) < 1e-9

    def test_fallback_to_default_tax(self):
        # Kein pretax / tax -> default
        # NOPAT = 100 * (1-0.27) = 73; invested = 600; ROIC ~ 0.1217
        result = _roic(ebit=100, equity=500, debt=100, pretax=None, tax=None, default_tax_rate=0.27)
        assert result is not None
        assert abs(result - 73 / 600) < 1e-9

    def test_no_equity_returns_none(self):
        assert (
            _roic(ebit=100, equity=None, debt=0, pretax=None, tax=None, default_tax_rate=0.27)
            is None
        )

    def test_caps_extreme_tax_rate(self):
        # Effective tax 90 % wuerde unrealistisch wenig NOPAT lassen -> Cap bei 60 %
        result = _roic(ebit=100, equity=500, debt=0, pretax=10, tax=9, default_tax_rate=0.27)
        # Cap auf 0.6: NOPAT = 100 * 0.4 = 40; invested = 500; ROIC = 0.08
        assert result is not None
        assert abs(result - 0.08) < 1e-9


class TestEarningsStability:
    def test_stable_series_high_score(self):
        df = pd.DataFrame({0: [100], 1: [102], 2: [99], 3: [101], 4: [100]}, index=["Net Income"])
        result = _earnings_stability(df)
        assert result is not None
        assert result > 0.9

    def test_volatile_series_low_score(self):
        df = pd.DataFrame(
            {0: [100], 1: [-50], 2: [200], 3: [-100], 4: [150]},
            index=["Net Income"],
        )
        result = _earnings_stability(df)
        assert result is not None
        assert result < 0.5

    def test_missing_series(self):
        assert _earnings_stability(None) is None


class TestFieldMap:
    def test_all_keys_have_at_least_one_candidate(self):
        for key, candidates in FIELD_MAP.items():
            assert len(candidates) >= 1, f"Field {key} has no candidates"
            assert all(isinstance(c, str) for c in candidates)


class TestFetchAll:
    """fetch_one wird gepatcht - kein yfinance-Netzcall, kein Datei-Cache mehr."""

    TICKERS = tuple(Ticker(f"T{i}.DE", f"T{i}", "DAX") for i in range(5))
    CFG = FetcherConfig(sleep_between=0)

    @staticmethod
    def _fake_fetch(failing: set[str]):
        def fake(ticker, cfg=None, history=None):
            fund = Fundamentals(identity=Identity(ticker.symbol, ticker.name, ticker.index))
            if ticker.symbol in failing:
                fund.errors.append("fetch failed: down")
            else:
                fund.market = MarketData(market_cap=1e9)
            return fund

        return fake

    def test_returns_flat_frame_and_writes_no_files(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        with patch("src.data_fetcher.fetch_one", side_effect=self._fake_fetch({"T0.DE"})):
            df = fetch_all(self.TICKERS, cfg=self.CFG)
        assert len(df) == 5
        assert "fetched_at" in df.columns
        assert list(tmp_path.iterdir()) == []

    def test_callback_receives_every_result_immediately(self):
        seen: list[str] = []
        with patch("src.data_fetcher.fetch_one", side_effect=self._fake_fetch({"T1.DE"})):
            fetch_all(self.TICKERS, cfg=self.CFG, on_result=lambda f: seen.append(f.symbol))
        assert seen == [t.symbol for t in self.TICKERS]

    def test_callback_error_aborts(self):
        def boom(_):
            raise RuntimeError("db down")

        with (
            patch("src.data_fetcher.fetch_one", side_effect=self._fake_fetch(set())),
            pytest.raises(RuntimeError, match="db down"),
        ):
            fetch_all(self.TICKERS, cfg=self.CFG, on_result=boom)

    def test_history_state_is_passed_per_symbol(self):
        state = HistoryState(last_share_date=date(2026, 7, 29))
        with patch("src.data_fetcher.fetch_one", side_effect=self._fake_fetch(set())) as one:
            fetch_all(self.TICKERS[:2], cfg=self.CFG, history={"T1.DE": state})
        assert [c.kwargs["history"] for c in one.call_args_list] == [None, state]

    def test_success_share(self):
        failing = {t.symbol for t in self.TICKERS[:4]}
        with patch("src.data_fetcher.fetch_one", side_effect=self._fake_fetch(failing)):
            df = fetch_all(self.TICKERS, cfg=self.CFG)
        assert success_share(df) == pytest.approx(0.2)
        assert success_share(pd.DataFrame()) == 0.0


def _statement(values: dict[str, float]) -> pd.DataFrame:
    return pd.DataFrame({"2025-12-31": values})


class TestStatementFx:
    def test_same_currency_is_one(self):
        assert _statement_fx({"currency": "EUR", "financialCurrency": "EUR"}, []) == 1.0

    def test_unknown_currency_is_one(self):
        assert _statement_fx({"currency": "EUR"}, []) == 1.0

    def test_mismatch_uses_fx_rate(self):
        with patch("src.data_fetcher._fx_rate", return_value=0.9) as fx_rate:
            fx = _statement_fx({"currency": "EUR", "financialCurrency": "USD"}, [])
        assert fx == 0.9
        fx_rate.assert_called_once_with("USD", "EUR")

    def test_fx_failure_returns_none_and_logs_error(self):
        errors: list[str] = []
        with patch("src.data_fetcher._fx_rate", side_effect=ValueError("down")):
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
            patch("src.data_fetcher._ticker_data", return_value=data),
            patch("src.data_fetcher._fx_rate", **fx_rate),
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
        with patch("src.data_fetcher._ticker_data", return_value=data):
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
        with patch("src.data_fetcher._ticker_data", **kwargs):
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
        with patch("src.data_fetcher._ticker_data", return_value=(info, income, None, None)):
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
