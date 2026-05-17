"""Tests fuer Helper-Funktionen in data_fetcher (ohne yfinance-Netzcalls)."""

from __future__ import annotations

import pandas as pd
import pytest

from src.data_fetcher import (
    FIELD_MAP,
    _cagr,
    _earnings_stability,
    _f,
    _latest,
    _pick,
    _roic,
    _safe_div,
)


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
