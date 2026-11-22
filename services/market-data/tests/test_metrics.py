"""Kennzahlen als reine Funktionen (P1.3): keine Ein-/Ausgabe, kein yfinance, kein pandas.

Die Hilfsfunktions-Tests stammen aus tests/test_data_fetcher.py. Dass die Kennzahlen echter
Titel beim Umbau gleich bleiben, prueft tests/test_metrics_snapshot.py.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta

import pytest

from va_market_data.domain.metrics import (
    FiscalYear,
    MarketFigures,
    Metrics,
    ShareHistory,
    StatementFigures,
    cagr,
    cfo_assets,
    compute_metrics,
    earnings_stability,
    f_score,
    f_score_signals,
    net_share_issuance,
    operating_accruals,
    roic,
    safe_div,
)

TAX = 0.27


def _metrics(
    statements: StatementFigures, market: MarketFigures | None = None, fx: float | None = 1.0
) -> Metrics:
    return compute_metrics(statements, market or MarketFigures(), fx=fx, default_tax_rate=TAX)


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


class TestRoic:
    def test_with_effective_tax_rate(self):
        # EBIT=100, pretax=80, tax=20 -> Steuerquote 0.25; NOPAT 75 / (500+100)
        result = roic(ebit=100, equity=500, debt=100, pretax=80, tax=20, default_tax_rate=TAX)
        assert result == pytest.approx(0.125)

    def test_fallback_to_default_tax(self):
        result = roic(ebit=100, equity=500, debt=100, pretax=None, tax=None, default_tax_rate=TAX)
        assert result == pytest.approx(73 / 600)

    def test_no_equity_returns_none(self):
        assert (
            roic(ebit=100, equity=None, debt=0, pretax=None, tax=None, default_tax_rate=TAX) is None
        )

    def test_caps_extreme_tax_rate(self):
        # Steuerquote 90 % -> Kappung bei 60 %: NOPAT 40 / 500
        result = roic(ebit=100, equity=500, debt=0, pretax=10, tax=9, default_tax_rate=TAX)
        assert result == pytest.approx(0.08)

    def test_wired_into_compute_metrics_with_the_given_default_rate(self):
        figures = StatementFigures(ebit=100.0, total_equity=500.0, total_debt=100.0)
        m = compute_metrics(figures, MarketFigures(), fx=1.0, default_tax_rate=0.3)
        assert m.roic == pytest.approx(70 / 600)


class TestEarningsStability:
    def test_stable_series_high_score(self):
        result = earnings_stability([100, 102, 99, 101, 100])
        assert result is not None
        assert result > 0.9

    def test_volatile_series_low_score(self):
        result = earnings_stability([100, -50, 200, -100, 150])
        assert result is not None
        assert result < 0.5

    def test_needs_four_of_the_last_five_years(self):
        assert earnings_stability([100, 102, 99]) is None
        assert earnings_stability([]) is None

    def test_missing_years_do_not_count(self):
        """Fehlende Jahre zaehlen nicht mit: drei gueltige Werte reichen nicht."""
        assert earnings_stability([None, 100, 100, 100]) is None
        assert earnings_stability([float("nan"), 100, 100, 100]) is None

    def test_only_the_last_five_years_count(self):
        # Die Werte ab dem sechsten Jahr zaehlen nicht, sonst waere die Reihe instabil
        assert earnings_stability([100, 100, 100, 100, 100, -900]) == 1.0

    def test_wired_into_compute_metrics(self):
        figures = StatementFigures(net_income_history=(100.0, 102.0, 99.0, 101.0, 100.0))
        assert _metrics(figures).earnings_stability == earnings_stability([100, 102, 99, 101, 100])


class TestGrowth:
    def test_needs_four_of_five_years(self):
        figures = StatementFigures(revenue_history=(100.0, 90.0, 80.0))
        assert _metrics(figures).revenue_growth_5y is None

    def test_cagr_over_the_available_years(self):
        figures = StatementFigures(revenue_history=(100.0, 90.0, 80.0, 60.0))
        assert _metrics(figures).revenue_growth_5y == pytest.approx((100 / 60) ** (1 / 3) - 1)

    def test_missing_years_are_skipped(self):
        figures = StatementFigures(revenue_history=(100.0, 90.0, None, 80.0))
        assert _metrics(figures).revenue_growth_5y is None

    def test_eps_growth(self):
        figures = StatementFigures(eps_history=(2.0, 1.8, 1.6, 1.5, 1.0))
        assert _metrics(figures).eps_growth_5y == pytest.approx(2.0 ** (1 / 4) - 1)


class TestQualityRatios:
    def test_margins_and_returns(self):
        figures = StatementFigures(
            revenue=1_000.0,
            gross_profit=400.0,
            operating_income=150.0,
            net_income=90.0,
            total_assets=3_000.0,
        )
        m = _metrics(figures)
        assert (m.gross_margin, m.operating_margin, m.roa) == (0.4, 0.15, 0.03)

    def test_missing_revenue_gives_no_margins(self):
        m = _metrics(StatementFigures(gross_profit=400.0, operating_income=150.0))
        assert (m.gross_margin, m.operating_margin, m.fcf_margin) == (None, None, None)


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
    dividend_yield=0.01,
)


class TestCurrencyMismatch:
    def test_value_multiples_use_converted_statements(self):
        m = _metrics(QIAGEN_STATEMENTS, QIAGEN_MARKET, fx=0.8)
        # EV = 8000 + (1600 - 600) * 0.8 = 8800, EBIT = 500 * 0.8 = 400
        assert m.enterprise_value == pytest.approx(8_800.0)
        assert m.ev_ebit == pytest.approx(22.0)
        assert m.pb_ratio == pytest.approx(8_000.0 / 2_400.0)
        assert m.p_fcf == pytest.approx(8_000.0 / 320.0)
        assert m.pe_ratio == pytest.approx(8_000.0 / 320.0)
        assert m.buyback_yield == pytest.approx(160.0 / 8_000.0)

    def test_quality_ratios_unaffected_by_fx(self):
        m = _metrics(QIAGEN_STATEMENTS, QIAGEN_MARKET, fx=0.8)
        assert m.fcf_margin == pytest.approx(0.2)
        assert m.debt_to_equity == pytest.approx(1_600.0 / 3_000.0)

    def test_loss_gives_no_pe(self):
        loss = StatementFigures(net_income=-50.0)
        assert _metrics(loss, QIAGEN_MARKET, fx=0.8).pe_ratio is None

    def test_unknown_fx_drops_everything_that_mixes_currencies(self):
        m = _metrics(QIAGEN_STATEMENTS, QIAGEN_MARKET, fx=None)
        assert (m.enterprise_value, m.ev_ebit, m.pe_ratio, m.pb_ratio, m.p_fcf) == (None,) * 5
        assert m.buyback_yield is None
        assert m.shareholder_yield == 0.01  # nur die Dividende
        assert m.fcf_margin == pytest.approx(0.2)


class TestSameCurrency:
    def test_provider_multiples_are_used(self):
        m = _metrics(QIAGEN_STATEMENTS, QIAGEN_MARKET, fx=1.0)
        assert m.enterprise_value == 9_000.0
        assert (m.pe_ratio, m.pb_ratio) == (99.0, 2.76)

    @pytest.mark.parametrize("price_to_book", [None, 0.0])
    def test_price_to_book_falls_back_to_equity(self, price_to_book):
        market = MarketFigures(market_cap=6_000.0, price_to_book=price_to_book)
        assert _metrics(QIAGEN_STATEMENTS, market).pb_ratio == pytest.approx(2.0)


class TestFreeCashFlow:
    def test_fallback_from_operating_cash_flow_and_capex(self):
        figures = StatementFigures(revenue=1_000.0, operating_cash_flow=150.0, capex=-50.0)
        assert _metrics(figures).fcf_margin == pytest.approx(0.1)

    def test_reported_fcf_has_priority(self):
        figures = StatementFigures(
            revenue=1_000.0, fcf=200.0, operating_cash_flow=150.0, capex=-50.0
        )
        assert _metrics(figures).fcf_margin == pytest.approx(0.2)


class TestShareholderYield:
    def test_zero_yield_is_kept(self):
        market = MarketFigures(market_cap=1_000.0, dividend_yield=0.0)
        assert _metrics(StatementFigures(), market).shareholder_yield == 0.0

    def test_missing_components_give_none(self):
        market = MarketFigures(market_cap=1_000.0)
        assert _metrics(StatementFigures(), market).shareholder_yield is None

    def test_dividend_plus_buybacks(self):
        market = MarketFigures(market_cap=1_000.0, dividend_yield=0.02)
        m = _metrics(StatementFigures(buybacks=-30.0), market)
        assert (m.dividend_yield, m.shareholder_yield) == (0.02, pytest.approx(0.05))


class TestNetDebtToEbitda:
    def test_cases(self):
        figures = StatementFigures(total_debt=500.0, cash=100.0, ebitda=200.0)
        assert _metrics(figures).net_debt_ebitda == 2.0

    def test_zero_ebitda_gives_none(self):
        figures = StatementFigures(total_debt=500.0, cash=100.0, ebitda=0.0)
        assert _metrics(figures).net_debt_ebitda is None


# --- F2.1 (ADR-0011): F-Score nach Piotroski (2000), Accruals nach Sloan (1996) ---------------

# Drei Geschäftsjahre, jüngstes zuerst, in denen alle neun Signale erfüllt sind. Von Hand:
# ROA 10/100 = 0,10 (Vorjahr 5/100 = 0,05), CFO 15/100 = 0,15 > ROA, Verschuldung 10/100
# gegen 20/100, Liquidität 60/30 = 2,0 gegen 50/30 = 1,67, Aktien 100 gegen 100, Bruttomarge
# 40/100 = 0,40 gegen 35/90 = 0,389, Kapitalumschlag 100/100 = 1,0 gegen 90/100 = 0,9.
_T = FiscalYear(
    net_income=10.0,
    revenue=100.0,
    gross_profit=40.0,
    total_assets=100.0,
    long_term_debt=10.0,
    current_assets=60.0,
    current_liabilities=30.0,
    shares=100.0,
    operating_cash_flow=15.0,
)
_PRIOR = FiscalYear(
    net_income=5.0,
    revenue=90.0,
    gross_profit=35.0,
    total_assets=100.0,
    long_term_debt=20.0,
    current_assets=50.0,
    current_liabilities=30.0,
    shares=100.0,
    operating_cash_flow=8.0,
)
_BEFORE = FiscalYear(total_assets=100.0)
_YEARS = (_T, _PRIOR, _BEFORE)


class TestFScore:
    def test_all_nine_signals(self):
        signals = f_score_signals(_YEARS)
        assert signals is not None
        assert set(signals) == {
            "roa_positive",
            "cfo_positive",
            "roa_up",
            "cfo_above_net_income",
            "leverage_down",
            "liquidity_up",
            "no_new_shares",
            "margin_up",
            "turnover_up",
        }
        assert all(value == 1 for value in signals.values())
        assert f_score(_YEARS) == 9

    @pytest.mark.parametrize(
        ("change", "signal"),
        [
            ({"net_income": -1.0}, "roa_positive"),
            ({"operating_cash_flow": -1.0}, "cfo_positive"),
            ({"net_income": 4.0}, "roa_up"),  # 0,04 < 0,05
            ({"operating_cash_flow": 9.0}, "cfo_above_net_income"),  # 0,09 < 0,10
            ({"long_term_debt": 25.0}, "leverage_down"),
            ({"current_assets": 40.0}, "liquidity_up"),  # 1,33 < 1,67
            ({"shares": 101.0}, "no_new_shares"),
            ({"gross_profit": 35.0}, "margin_up"),  # 0,35 < 0,389
            ({"revenue": 85.0}, "turnover_up"),  # 0,85 < 0,9
        ],
    )
    def test_each_signal_on_its_own(self, change: dict[str, float], signal: str):
        signals = f_score_signals((replace(_T, **change), _PRIOR, _BEFORE))
        assert signals is not None
        assert signals[signal] == 0

    def test_unchanged_does_not_count(self):
        # Piotroski: eine Verbesserung zählt, Gleichstand nicht
        signals = f_score_signals((replace(_T, long_term_debt=20.0), _PRIOR, _BEFORE))
        assert signals is not None
        assert signals["leverage_down"] == 0

    def test_equal_share_count_is_no_new_shares(self):
        signals = f_score_signals(_YEARS)
        assert signals is not None
        assert signals["no_new_shares"] == 1

    def test_missing_prior_value_gives_none_not_zero(self):
        assert f_score((_T, replace(_PRIOR, current_liabilities=None), _BEFORE)) is None
        assert f_score((_T, replace(_PRIOR, net_income=None), _BEFORE)) is None

    def test_needs_three_years_of_total_assets(self):
        # ROA des Vorjahres braucht die Bilanzsumme von davor (Jahresanfang)
        assert f_score((_T, _PRIOR)) is None
        assert f_score((_T, _PRIOR, FiscalYear())) is None

    def test_no_long_term_debt_in_both_years_is_no_improvement(self):
        years = (replace(_T, long_term_debt=None), replace(_PRIOR, long_term_debt=None), _BEFORE)
        signals = f_score_signals(years)
        assert signals is not None
        assert signals["leverage_down"] == 0
        assert f_score(years) == 8

    def test_long_term_debt_missing_in_one_year_is_a_gap(self):
        assert f_score((replace(_T, long_term_debt=None), _PRIOR, _BEFORE)) is None

    def test_gross_profit_from_revenue_and_cost_of_revenue(self):
        years = (replace(_T, gross_profit=None, cost_of_revenue=60.0), _PRIOR, _BEFORE)
        assert f_score(years) == 9


class TestAccruals:
    def test_cash_above_earnings_is_negative(self):
        # (10 - 15) / Ø Bilanzsumme 100
        assert operating_accruals(_YEARS) == pytest.approx(-0.05)

    def test_earnings_above_cash_is_positive(self):
        years = (replace(_T, operating_cash_flow=4.0), _PRIOR)
        assert operating_accruals(years) == pytest.approx(0.06)

    def test_scaled_by_average_total_assets(self):
        years = (replace(_T, total_assets=150.0), _PRIOR)  # Ø 125
        assert operating_accruals(years) == pytest.approx(-5.0 / 125.0)
        assert cfo_assets(years) == pytest.approx(15.0 / 125.0)

    def test_cfo_assets_with_sign(self):
        assert cfo_assets(_YEARS) == pytest.approx(0.15)
        assert cfo_assets((replace(_T, operating_cash_flow=-3.0), _PRIOR)) == pytest.approx(-0.03)

    def test_need_two_years_of_total_assets(self):
        assert operating_accruals((_T,)) is None
        assert cfo_assets((_T, replace(_PRIOR, total_assets=None))) is None

    def test_wired_into_compute_metrics(self):
        m = _metrics(StatementFigures(years=_YEARS))
        assert m.f_score == 9
        assert m.operating_accruals == pytest.approx(-0.05)
        assert m.cfo_assets == pytest.approx(0.15)
        assert _metrics(StatementFigures()).f_score is None


# --- F2.2 (ADR-0011): Netto-Aktienemission über 12 Monate, um Splits bereinigt -------------------

_DAY = date(2026, 11, 20)
_YEAR_AGO = _DAY - timedelta(days=365)


def _issuance(counts: dict[date, float], splits: dict[date, float] | None = None, as_of=_DAY):
    return net_share_issuance(ShareHistory(counts=counts, splits=splits or {}, as_of=as_of))


class TestNetShareIssuance:
    def test_buyback_is_negative(self):
        assert _issuance({_YEAR_AGO: 100.0, _DAY: 95.0}) == pytest.approx(-0.05)

    def test_capital_increase_is_positive(self):
        assert _issuance({_YEAR_AGO: 100.0, _DAY: 110.0}) == pytest.approx(0.10)

    def test_split_is_no_issuance(self):
        # Yahoo liefert die Aktienanzahl roh: am 2:1-Split verdoppelt sie sich
        counts = {_YEAR_AGO: 100.0, _DAY: 200.0}
        assert _issuance(counts, {_DAY - timedelta(days=100): 2.0}) == pytest.approx(0.0)

    def test_reverse_split_is_no_buyback(self):
        counts = {_YEAR_AGO: 1_000.0, _DAY: 100.0}
        assert _issuance(counts, {_DAY - timedelta(days=50): 0.1}) == pytest.approx(0.0)

    def test_split_before_the_year_does_not_count(self):
        counts = {_YEAR_AGO: 100.0, _DAY: 200.0}
        assert _issuance(counts, {_YEAR_AGO - timedelta(days=40): 2.0}) == pytest.approx(1.0)

    def test_median_ignores_a_stray_value(self):
        # Yahoo liefert manche Tage doppelt oder abweichend
        counts = {
            _YEAR_AGO: 100.0,
            _DAY - timedelta(days=2): 300.0,
            _DAY - timedelta(days=1): 95.0,
            _DAY: 95.0,
        }
        assert _issuance(counts) == pytest.approx(-0.05)

    def test_reference_is_the_newest_count(self):
        counts = {_YEAR_AGO: 100.0, _DAY: 95.0}
        assert _issuance(counts, as_of=_DAY + timedelta(days=30)) == pytest.approx(-0.05)

    def test_stale_counts_give_none(self):
        counts = {_YEAR_AGO: 100.0, _DAY: 95.0}
        assert _issuance(counts, as_of=_DAY + timedelta(days=121)) is None

    def test_needs_a_count_a_year_earlier(self):
        assert _issuance({_DAY: 95.0}) is None
        assert _issuance({_DAY - timedelta(days=200): 100.0, _DAY: 95.0}) is None
        assert _issuance({}) is None

    def test_wired_into_compute_metrics(self):
        shares = ShareHistory(counts={_YEAR_AGO: 100.0, _DAY: 95.0}, splits={}, as_of=_DAY)
        m = compute_metrics(
            StatementFigures(), MarketFigures(), fx=1.0, default_tax_rate=TAX, shares=shares
        )
        assert m.net_share_issuance == pytest.approx(-0.05)
        assert _metrics(StatementFigures()).net_share_issuance is None
