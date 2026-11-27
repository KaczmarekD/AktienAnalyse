"""F3.1 (ADR-0011, Punkt 6): fundamentale Anker je Titel, nicht im Composite."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import pytest

from va_contracts.events.v1.ranking import ANCHOR_KEYS
from va_scoring.domain.anchors import (
    ANCHOR_COLUMNS,
    add_anchors,
    epv_equity,
    implied_fcf_growth,
)
from va_scoring.domain.scoring import ScoringConfig


def _dcf_value(fcf: float, g: float, r: float, terminal: float, years: int) -> float:
    """Wert eines FCF, der ``years`` Jahre mit g und danach mit ``terminal`` wächst."""
    value = sum(fcf * (1 + g) ** t / (1 + r) ** t for t in range(1, years + 1))
    last = fcf * (1 + g) ** years
    return value + last * (1 + terminal) / (r - terminal) / (1 + r) ** years


class TestEpv:
    def test_earnings_power_minus_net_debt(self):
        # 80 / 0,08 = 1000, minus 200 Nettoschulden
        assert epv_equity(nopat=80.0, net_debt=200.0, cost_of_capital=0.08) == pytest.approx(800.0)

    def test_net_cash_adds(self):
        assert epv_equity(nopat=80.0, net_debt=-100.0, cost_of_capital=0.08) == pytest.approx(
            1100.0
        )

    def test_missing_input_gives_none(self):
        assert epv_equity(nopat=None, net_debt=0.0, cost_of_capital=0.08) is None
        assert epv_equity(nopat=80.0, net_debt=None, cost_of_capital=0.08) is None


class TestImpliedGrowth:
    def test_by_hand(self):
        # FCF 100, r 10 %, ein Jahr, danach kein Wachstum: Wert = 1000 x (1 + g)
        g = implied_fcf_growth(
            market_cap=1100.0, fcf=100.0, cost_of_capital=0.10, terminal_growth=0.0, years=1
        )
        assert g == pytest.approx(0.10, abs=1e-6)

    def test_inverts_the_dcf(self):
        value = _dcf_value(10.0, 0.05, 0.08, 0.02, 10)
        g = implied_fcf_growth(
            market_cap=value, fcf=10.0, cost_of_capital=0.08, terminal_growth=0.02, years=10
        )
        assert g == pytest.approx(0.05, abs=1e-6)

    @pytest.mark.parametrize("fcf", [0.0, -10.0, None])
    def test_without_positive_fcf_none(self, fcf):
        args = {"cost_of_capital": 0.08, "terminal_growth": 0.02, "years": 10}
        assert implied_fcf_growth(market_cap=1000.0, fcf=fcf, **args) is None

    def test_no_solution_between_minus_20_and_plus_40_percent(self):
        args = {"fcf": 10.0, "cost_of_capital": 0.08, "terminal_growth": 0.02, "years": 10}
        low = _dcf_value(10.0, -0.25, 0.08, 0.02, 10)
        high = _dcf_value(10.0, 0.45, 0.08, 0.02, 10)
        assert implied_fcf_growth(market_cap=low, **args) is None
        assert implied_fcf_growth(market_cap=high, **args) is None

    def test_cost_of_capital_must_exceed_terminal_growth(self):
        g = implied_fcf_growth(
            market_cap=1000.0, fcf=10.0, cost_of_capital=0.02, terminal_growth=0.02, years=10
        )
        assert g is None


def _frame(**overrides: Any) -> pd.DataFrame:
    rows = [
        {
            "symbol": "SAP.DE",
            "industry": "Software - Application",
            "market_cap": 1000.0,
            "enterprise_value": 1200.0,  # 200 Nettoschulden
            "shares_outstanding": 10.0,
            "nopat_normalized": 80.0,
            "p_fcf": 20.0,  # FCF 50
            "composite_score": 0.7,
        },
        {
            "symbol": "DBK.DE",
            "industry": "Banks - Regional",
            "market_cap": 1000.0,
            "enterprise_value": 1500.0,
            "shares_outstanding": 10.0,
            "nopat_normalized": 80.0,
            "p_fcf": 10.0,
            "composite_score": 0.5,
        },
    ]
    rows[0].update(overrides)
    return pd.DataFrame(rows)


def _row(out: pd.DataFrame, symbol: str) -> dict[str, Any]:
    """Eine Zeile als dict: Werte ohne pandas-Typen fuer die Vergleiche."""
    return next(
        {str(k): v for k, v in r.items()} for r in out.to_dict("records") if r["symbol"] == symbol
    )


class TestAddAnchors:
    def test_keys_match_the_contract(self):
        assert set(ANCHOR_COLUMNS) == set(ANCHOR_KEYS)

    def test_values_per_title(self):
        sap = _row(add_anchors(_frame(), ScoringConfig()), "SAP.DE")
        # EPV = 80 / 0,08 - 200 = 800
        assert sap["epv_per_share"] == pytest.approx(80.0)
        assert sap["price_to_epv"] == pytest.approx(1000.0 / 800.0)
        expected = implied_fcf_growth(
            market_cap=1000.0, fcf=50.0, cost_of_capital=0.08, terminal_growth=0.02, years=10
        )
        assert sap["implied_fcf_growth"] == pytest.approx(expected)

    def test_sensitivity_one_point_either_side(self):
        sap = _row(add_anchors(_frame(), ScoringConfig()), "SAP.DE")
        # Höhere Kapitalkosten: weniger Ertragskraft, mehr nötiges Wachstum
        assert sap["price_to_epv_r_low"] < sap["price_to_epv"] < sap["price_to_epv_r_high"]
        assert (
            sap["implied_fcf_growth_r_low"]
            < sap["implied_fcf_growth"]
            < sap["implied_fcf_growth_r_high"]
        )
        assert sap["price_to_epv_r_low"] == pytest.approx(1000.0 / (80.0 / 0.07 - 200.0))

    def test_no_anchors_for_financials_even_without_the_industry_rule(self):
        cfg = ScoringConfig(industry_rules=False)
        dbk = _row(add_anchors(_frame(), cfg), "DBK.DE")
        assert all(pd.isna(dbk[key]) for key in ANCHOR_COLUMNS)

    def test_negative_earnings_power_has_no_price_ratio(self):
        sap = _row(add_anchors(_frame(nopat_normalized=-8.0), ScoringConfig()), "SAP.DE")
        assert sap["epv_per_share"] == pytest.approx((-8.0 / 0.08 - 200.0) / 10.0)
        assert np.isnan(sap["price_to_epv"])

    def test_parameters_come_from_the_config(self):
        cfg = ScoringConfig(cost_of_capital=0.10, terminal_growth=0.0, dcf_years=1)
        # FCF = 1100 / 11 = 100, also Wert = 1000 x (1 + g) wie im Beispiel von Hand
        sap = _row(add_anchors(_frame(p_fcf=11.0, market_cap=1100.0), cfg), "SAP.DE")
        assert sap["implied_fcf_growth"] == pytest.approx(0.10, abs=1e-6)

    def test_missing_columns_give_empty_anchors(self):
        # Ältere Snapshots ohne NOPAT und Unternehmenswert: nur das implizite Wachstum
        frame = _frame().drop(columns=["nopat_normalized", "enterprise_value", "industry"])
        out = add_anchors(frame, ScoringConfig()).set_index("symbol")
        assert out["epv_per_share"].isna().all()
        assert out.loc["SAP.DE", "implied_fcf_growth"] == pytest.approx(
            implied_fcf_growth(
                market_cap=1000.0, fcf=50.0, cost_of_capital=0.08, terminal_growth=0.02, years=10
            )
        )

    def test_scores_stay_as_they_are(self):
        frame = _frame()
        out = add_anchors(frame, ScoringConfig())
        pd.testing.assert_series_equal(out["composite_score"], frame["composite_score"])
        assert len(out) == len(frame)
