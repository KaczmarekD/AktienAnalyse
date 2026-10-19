"""Kennzahlen als reine Funktionen (P1.3): keine Ein-/Ausgabe, kein yfinance, kein pandas.

Die Hilfsfunktions-Tests stammen aus tests/test_data_fetcher.py. Dass die Kennzahlen echter
Titel beim Umbau gleich bleiben, prueft tests/test_metrics_snapshot.py.
"""

from __future__ import annotations

import pytest

from va_market_data.domain.metrics import (
    MarketFigures,
    StatementFigures,
    cagr,
    compute_metrics,
    dividend_yield,
    earnings_stability,
    roic,
    safe_div,
    to_float,
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
            # Ueberlauf: endliche Eingaben, Ergebnis inf - darf nicht ins Ranking
            (1e308, 1e-10, None),
        ],
    )
    def test_cases(self, num, den, expected):
        assert safe_div(num, den) == expected


class TestToFloat:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [(3.5, 3.5), (5, 5.0), (None, None), (float("nan"), None), (float("inf"), None)],
    )
    def test_cases(self, value, expected):
        assert to_float(value) == expected

    def test_garbage_returns_none(self):
        assert to_float("not a number") is None


class TestCagr:
    def test_basic(self):
        # 100 -> 90 -> 80 -> 70 -> 60 (juengstes zuerst): (100/60)^(1/4)-1 ~ 0.1362
        result = cagr([100, 90, 80, 70, 60])
        assert result is not None
        assert 0.13 < result < 0.14

    def test_sign_change_returns_none(self):
        assert cagr([100, 50, 0, -50, -100]) is None

    def test_too_short(self):
        assert cagr([100]) is None
        assert cagr([]) is None

    def test_overflow_returns_none(self):
        # Aeltester Wert fast 0: first/last laeuft ueber (inf) - kein Wachstumswert
        assert cagr([5e9, 4e9, 3e9, 2e9, 1e-300]) is None


class TestDividendYield:
    def test_prefers_trailing_decimal(self):
        assert dividend_yield(trailing=0.0136, percent=1.36) == pytest.approx(0.0136)

    def test_percent_fallback_below_one_percent(self):
        # 0.8 bedeutet 0,8 % - nicht 80 %
        assert dividend_yield(trailing=None, percent=0.8) == pytest.approx(0.008)

    def test_percent_fallback_above_one_percent(self):
        assert dividend_yield(trailing=None, percent=4.02) == pytest.approx(0.0402)

    def test_zero_trailing_is_kept(self):
        assert dividend_yield(trailing=0.0, percent=None) == 0.0

    def test_missing_returns_none(self):
        assert dividend_yield(trailing=None, percent=None) is None


class TestRoic:
    def test_with_effective_tax_rate(self):
        # EBIT=100, pretax=80, tax=20 -> Steuerquote 0.25; NOPAT 75 / (500+100)
        result = roic(ebit=100, equity=500, debt=100, pretax=80, tax=20, default_tax_rate=0.27)
        assert result == pytest.approx(0.125)

    def test_fallback_to_default_tax(self):
        result = roic(ebit=100, equity=500, debt=100, pretax=None, tax=None, default_tax_rate=0.27)
        assert result == pytest.approx(73 / 600)

    def test_no_equity_returns_none(self):
        assert (
            roic(ebit=100, equity=None, debt=0, pretax=None, tax=None, default_tax_rate=0.27)
            is None
        )

    def test_caps_extreme_tax_rate(self):
        # Steuerquote 90 % -> Kappung bei 60 %: NOPAT 40 / 500
        result = roic(ebit=100, equity=500, debt=0, pretax=10, tax=9, default_tax_rate=0.27)
        assert result == pytest.approx(0.08)


class TestEarningsStability:
    def test_stable_series_high_score(self):
        result = earnings_stability([100, 102, 99, 101, 100])
        assert result is not None
        assert result > 0.9

    def test_volatile_series_low_score(self):
        result = earnings_stability([100, -50, 200, -100, 150])
        assert result is not None
        assert result < 0.5

    def test_too_short_series(self):
        """Wie beim Wachstum: mindestens vier der letzten fuenf Jahre."""
        assert earnings_stability([100, 102, 99]) is None
        assert earnings_stability([]) is None


class TestGrowth:
    def test_needs_four_of_five_years(self):
        figures = StatementFigures(revenue_history=(100.0, 90.0, 80.0))
        assert compute_metrics(figures, MarketFigures(), fx=1.0).revenue_growth_5y is None

    def test_cagr_over_the_available_years(self):
        figures = StatementFigures(revenue_history=(100.0, 90.0, 80.0, 60.0))
        result = compute_metrics(figures, MarketFigures(), fx=1.0).revenue_growth_5y
        assert result == pytest.approx((100 / 60) ** (1 / 3) - 1)


# Qiagen-Fall: Kurs/Marktkapitalisierung in EUR, Abschluss in USD
QIAGEN_STATEMENTS = StatementFigures(
    revenue=2_000.0,
    ebit=500.0,
    net_income=400.0,
    total_equity=3_000.0,
    total_debt=1_600.0,
    cash=600.0,
    fcf=400.0,
    buybacks=-200.0,
)
QIAGEN_MARKET = MarketFigures(
    market_cap=8_000.0,
    enterprise_value=9_000.0,  # von Yahoo unkonvertiert gemischt
    price_to_book=2.76,  # EUR-Kurs / USD-Buchwert
    trailing_pe=99.0,
)


class TestCurrencyMismatch:
    def test_value_multiples_use_converted_statements(self):
        m = compute_metrics(QIAGEN_STATEMENTS, QIAGEN_MARKET, fx=0.8)
        # EV = 8000 + (1600 - 600) * 0.8 = 8800, EBIT = 500 * 0.8 = 400
        assert m.enterprise_value == pytest.approx(8_800.0)
        assert m.ev_ebit == pytest.approx(22.0)
        assert m.pb_ratio == pytest.approx(8_000.0 / 2_400.0)
        assert m.p_fcf == pytest.approx(8_000.0 / 320.0)
        assert m.pe_ratio == pytest.approx(8_000.0 / 320.0)
        assert m.buyback_yield == pytest.approx(160.0 / 8_000.0)

    def test_quality_ratios_unaffected_by_fx(self):
        m = compute_metrics(QIAGEN_STATEMENTS, QIAGEN_MARKET, fx=0.8)
        assert m.fcf_margin == pytest.approx(0.2)
        assert m.debt_to_equity == pytest.approx(1_600.0 / 3_000.0)

    def test_unknown_fx_drops_mixed_multiples(self):
        m = compute_metrics(QIAGEN_STATEMENTS, QIAGEN_MARKET, fx=None)
        assert (m.ev_ebit, m.pb_ratio, m.p_fcf) == (None, None, None)
        assert m.fcf_margin == pytest.approx(0.2)


class TestSameCurrency:
    def test_provider_multiples_are_used(self):
        m = compute_metrics(QIAGEN_STATEMENTS, QIAGEN_MARKET, fx=1.0)
        assert m.enterprise_value == 9_000.0
        assert (m.pe_ratio, m.pb_ratio) == (99.0, 2.76)

    def test_price_to_book_falls_back_to_equity(self):
        market = MarketFigures(market_cap=6_000.0)
        assert compute_metrics(QIAGEN_STATEMENTS, market, fx=1.0).pb_ratio == pytest.approx(2.0)


class TestFreeCashFlow:
    def test_fallback_from_operating_cash_flow_and_capex(self):
        figures = StatementFigures(revenue=1_000.0, operating_cash_flow=150.0, capex=-50.0)
        assert compute_metrics(figures, MarketFigures(), fx=1.0).fcf_margin == pytest.approx(0.1)


class TestShareholderYield:
    def test_zero_yield_is_kept(self):
        market = MarketFigures(market_cap=1_000.0, trailing_dividend_yield=0.0)
        assert compute_metrics(StatementFigures(), market, fx=1.0).shareholder_yield == 0.0

    def test_missing_components_give_none(self):
        market = MarketFigures(market_cap=1_000.0)
        assert compute_metrics(StatementFigures(), market, fx=1.0).shareholder_yield is None

    def test_dividend_plus_buybacks(self):
        market = MarketFigures(market_cap=1_000.0, trailing_dividend_yield=0.02)
        figures = StatementFigures(buybacks=-30.0)
        m = compute_metrics(figures, market, fx=1.0)
        assert m.shareholder_yield == pytest.approx(0.05)


class TestNetDebtToEbitda:
    def test_cases(self):
        figures = StatementFigures(total_debt=500.0, cash=100.0, ebitda=200.0)
        assert compute_metrics(figures, MarketFigures(), fx=1.0).net_debt_ebitda == 2.0

    def test_zero_ebitda_gives_none(self):
        figures = StatementFigures(total_debt=500.0, cash=100.0, ebitda=0.0)
        assert compute_metrics(figures, MarketFigures(), fx=1.0).net_debt_ebitda is None
