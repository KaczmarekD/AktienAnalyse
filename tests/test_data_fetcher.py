"""Tests fuer Helper-Funktionen in data_fetcher (ohne yfinance-Netzcalls)."""

from __future__ import annotations

from unittest.mock import patch

import pandas as pd
import pytest

from src.data_fetcher import (
    FIELD_MAP,
    FetcherConfig,
    _cagr,
    _dividend_yield,
    _earnings_stability,
    _f,
    _latest,
    _pick,
    _roic,
    _safe_div,
    _statement_fx,
    fetch_all,
    fetch_one,
)
from src.fundamentals import Fundamentals, Identity, MarketData
from src.universe import Ticker


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
        ],
    )
    def test_cases(self, num, den, expected):
        result = _safe_div(num, den)
        assert result == expected


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


class TestFetchAllCache:
    """fetch_one wird gepatcht - kein yfinance-Netzcall."""

    TICKERS = tuple(Ticker(f"T{i}.DE", f"T{i}", "DAX") for i in range(5))
    CFG = FetcherConfig(sleep_between=0)

    @staticmethod
    def _fake_fetch(failing: set[str]):
        def fake(ticker, cfg=None):
            fund = Fundamentals(identity=Identity(ticker.symbol, ticker.name, ticker.index))
            if ticker.symbol in failing:
                fund.errors.append("fetch failed: down")
            else:
                fund.market = MarketData(market_cap=1e9)
            return fund

        return fake

    def test_caches_when_enough_succeed(self, tmp_path):
        with patch("src.data_fetcher.fetch_one", side_effect=self._fake_fetch({"T0.DE"})):
            df = fetch_all(self.TICKERS, cache_dir=tmp_path, cfg=self.CFG)
        assert len(df) == 5
        assert len(list(tmp_path.glob("fundamentals_*.parquet"))) == 1

    def test_no_cache_on_mass_failure(self, tmp_path):
        failing = {t.symbol for t in self.TICKERS[:4]}
        with patch("src.data_fetcher.fetch_one", side_effect=self._fake_fetch(failing)):
            df = fetch_all(self.TICKERS, cache_dir=tmp_path, cfg=self.CFG)
        assert len(df) == 5  # Daten werden trotzdem zurueckgegeben
        assert list(tmp_path.glob("fundamentals_*.parquet")) == []

    def test_uses_cache_on_second_run(self, tmp_path):
        with patch("src.data_fetcher.fetch_one", side_effect=self._fake_fetch(set())):
            fetch_all(self.TICKERS, cache_dir=tmp_path, cfg=self.CFG)
        with patch("src.data_fetcher.fetch_one") as fetch_one:
            df = fetch_all(self.TICKERS, cache_dir=tmp_path, cfg=self.CFG)
        fetch_one.assert_not_called()
        assert len(df) == 5


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
