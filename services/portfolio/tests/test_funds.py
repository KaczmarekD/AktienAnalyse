"""ETFs rechnen (D4.3, ANA-05, ANA-06; docs/architecture/depot/analyse.md, Abschnitt ETFs).

- Laufende Kosten = Positionswert x TER, auf Cent.
- Durchschau: Gewicht eines Titels im Depot = direkt + Σ (ETF-Gewicht x Anteil im ETF).
- Überschneidung zweier ETFs = Σ min(Gewicht in A, Gewicht in B) über gemeinsame Titel.
- Look-through-Score = Σ (Anteil x Composite) / Σ Anteil über die bewerteten Titel, nur ab
  50 % bewertetem Gewicht (einstellbar).
- Kennt die Quelle nur die größten Positionen, sind Durchschau und Überschneidung Untergrenzen.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from va_portfolio.domain.funds import (
    Fund,
    FundHolding,
    look_through,
    look_through_score,
    overlap,
    running_costs,
)

SAP = "DE0007164600"
SIEMENS = "DE0007236101"
APPLE = "US0378331005"
MSFT = "US5949181045"


def _fund(*holdings: tuple[str | None, float], complete: bool = True) -> Fund:
    return Fund(
        holdings=tuple(FundHolding(isin, weight) for isin, weight in holdings), complete=complete
    )


class TestRunningCosts:
    def test_value_times_ter(self):
        assert running_costs(Decimal("10000"), 0.2) == Decimal("20.00")

    def test_in_cents(self):
        assert running_costs(Decimal("1234.56"), 0.07) == Decimal("0.86")

    @pytest.mark.parametrize(("value", "ter"), [(None, 0.2), (Decimal(100), None)])
    def test_without_value_or_ter_none(self, value, ter):
        assert running_costs(value, ter) is None


class TestLookThrough:
    def test_direct_plus_share_in_the_etf(self):
        world = _fund((SAP, 2.0), (APPLE, 5.0))
        exposure = look_through({SAP: 0.2}, [(0.5, world)])
        assert exposure.weights[SAP] == pytest.approx(0.21)
        assert exposure.weights[APPLE] == pytest.approx(0.025)
        assert exposure.lower_bound is False

    def test_top_holdings_only_is_a_lower_bound(self):
        exposure = look_through({}, [(1.0, _fund((APPLE, 5.0), complete=False))])
        assert exposure.lower_bound is True

    def test_without_isin_cash_and_duplicates(self):
        """Ohne ISIN zählt nicht, negative Gewichte (Geldmarkt) auch nicht, doppelte ISINs addiert."""
        fund = _fund((None, 3.0), (APPLE, 2.0), (APPLE, 1.0), (MSFT, -0.5))
        exposure = look_through({}, [(1.0, fund)])
        assert exposure.weights == {APPLE: pytest.approx(0.03)}

    def test_two_etfs_add_up(self):
        exposure = look_through(
            {}, [(0.4, _fund((APPLE, 5.0))), (0.6, _fund((APPLE, 10.0), (MSFT, 8.0)))]
        )
        assert exposure.weights[APPLE] == pytest.approx(0.4 * 0.05 + 0.6 * 0.10)
        assert exposure.weights[MSFT] == pytest.approx(0.048)


class TestOverlap:
    def test_sum_of_the_smaller_weights(self):
        a = _fund((SAP, 10.0), (APPLE, 5.0), (MSFT, 3.0))
        b = _fund((SAP, 4.0), (APPLE, 6.0), (SIEMENS, 2.0))
        share, lower_bound = overlap(a, b)
        assert share == pytest.approx(0.09)
        assert lower_bound is False

    def test_the_same_etf_overlaps_fully(self):
        a = _fund((SAP, 60.0), (APPLE, 40.0))
        assert overlap(a, a)[0] == pytest.approx(1.0)

    def test_nothing_in_common(self):
        assert overlap(_fund((SAP, 50.0)), _fund((APPLE, 50.0)))[0] == 0

    def test_an_incomplete_list_is_a_lower_bound(self):
        assert overlap(_fund((SAP, 5.0)), _fund((SAP, 4.0), complete=False))[1] is True


class TestScore:
    COMPOSITES = {SAP: 0.6, SIEMENS: 0.4}  # noqa: RUF012

    def test_weighted_over_the_scored_titles(self):
        fund = _fund((SAP, 30.0), (SIEMENS, 30.0), (APPLE, 40.0))
        result = look_through_score(fund, self.COMPOSITES)
        assert result.covered == pytest.approx(0.6)
        assert result.score == pytest.approx((30 * 0.6 + 30 * 0.4) / 60)

    def test_below_half_covered_no_score(self):
        fund = _fund((SAP, 30.0), (APPLE, 70.0))
        result = look_through_score(fund, self.COMPOSITES)
        assert (result.score, result.covered) == (None, pytest.approx(0.3))

    def test_the_threshold_is_adjustable(self):
        fund = _fund((SAP, 30.0), (APPLE, 70.0))
        assert look_through_score(fund, self.COMPOSITES, min_covered=0.25).score == pytest.approx(
            0.6
        )

    def test_nothing_scored(self):
        result = look_through_score(_fund((APPLE, 100.0)), self.COMPOSITES)
        assert (result.score, result.covered) == (None, 0)
