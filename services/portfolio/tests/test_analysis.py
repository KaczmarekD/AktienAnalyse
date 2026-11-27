"""Analyse eines Depots (D4.4, ANA-08 bis 10), an einem von Hand nachgerechneten Beispiel.

Depot, Wert 7000 EUR:
- SAP 10 x 200 EUR = 2000 (Composite 0,6, Value 0,4, Quality 0,9, Perzentil 0,75, Technology)
- Apple 10 x 150 USD x 0,9 = 1350 (Composite 0,4, Value 0,2, Quality 0,7, Perzentil 0,15,
  Technology, Value-Trap)
- Welt-ETF 20 x 100 EUR = 2000 (TER 0,2 %, Fondswaehrung USD, Sektoren IT 25 %, Financials
  15 %, Laender Vereinigte Staaten 70 %, Japan 5 %, nur die groessten Positionen: Apple 5 %,
  Microsoft 4 %)
- Bund 2,6 % 2033, Nennwert 1000 zu 97,5 % = 975
- Kasse 675
"""

from __future__ import annotations

from dataclasses import fields
from datetime import date
from decimal import Decimal

import pytest

from va_portfolio.domain.analysis import (
    AnalysisInput,
    BondData,
    EtfData,
    analyze,
    country_key,
    sector_key,
)
from va_portfolio.domain.bonds import BondTerms, bond_figures
from va_portfolio.domain.depots import CashLine, HoldingLine
from va_portfolio.domain.funds import Fund, FundHolding
from va_portfolio.domain.valuation import Market, Quote, Score, SecurityInfo, value_depot

SAP = "DE0007164600"
APPLE = "US0378331005"
MSFT = "US5949181045"
WORLD = "IE00B4L5Y983"
BUND = "DE0001102580"
FRIDAY = date(2026, 11, 20)
THURSDAY = date(2026, 11, 19)
BUND_TERMS = BondTerms(coupon=2.6, maturity=date(2033, 8, 15))


def _score(isin: str, composite: float, value: float, quality: float, percentile: float, **kw):
    return Score(
        isin=isin,
        scoring_run_id=8,
        as_of=FRIDAY,
        symbol=isin,
        reference="universe",
        value_score=value,
        quality_score=quality,
        composite_score=composite,
        composite_percentile=percentile,
        sector="Technology",
        **kw,
    )


MARKET = Market(
    securities={
        SAP: SecurityInfo(SAP, "SAP SE", "equity", "EUR"),
        APPLE: SecurityInfo(APPLE, "Apple Inc.", "equity", "USD"),
        WORLD: SecurityInfo(WORLD, "iShares Core MSCI World", "etf", "USD"),
        BUND: SecurityInfo(BUND, "Bund 2033", "bond", "EUR"),
    },
    quotes={
        SAP: Quote(SAP, FRIDAY, Decimal(200), "EUR"),
        APPLE: Quote(APPLE, THURSDAY, Decimal(150), "USD"),
        WORLD: Quote(WORLD, FRIDAY, Decimal(100), "EUR"),
        BUND: Quote(BUND, FRIDAY, Decimal("97.5"), "EUR", percent_of_par=True),
    },
    fx={"USD": Decimal("0.9")},
    scores={
        SAP: _score(SAP, 0.6, 0.4, 0.9, 0.75),
        APPLE: _score(APPLE, 0.4, 0.2, 0.7, 0.15, value_trap_flag=True),
    },
)
LINES = [
    HoldingLine(SAP, Decimal(10)),
    HoldingLine(APPLE, Decimal(10)),
    HoldingLine(WORLD, Decimal(20)),
    HoldingLine(BUND, Decimal(1000), unit="nominal"),
]
WORLD_DATA = EtfData(
    as_of=date(2026, 11, 15),
    ter=0.2,
    currency="USD",
    sectors={"IT": 25.0, "Financials": 15.0},
    countries={"Vereinigte Staaten": 70.0, "Japan": 5.0},
    holdings=Fund(
        holdings=(FundHolding(APPLE, 5.0), FundHolding(MSFT, 4.0)),
        complete=False,
    ),
)


def _input(**overrides) -> AnalysisInput:
    value = value_depot("depot", LINES, [CashLine(Decimal(675))], MARKET)
    data = AnalysisInput(
        value=value,
        etfs={WORLD: WORLD_DATA},
        bonds={BUND: BondData(BUND_TERMS, "DBFTFB")},
        composites={SAP: 0.6, APPLE: 0.4},
        names={MSFT: "MICROSOFT CORP"},
    )
    return AnalysisInput(**{**data.__dict__, **overrides})


def _by_key(slices) -> dict[str, tuple[Decimal, float]]:
    return {s.key: (s.value_eur, s.weight) for s in slices}


@pytest.fixture
def analysis():
    return analyze(_input())


class TestAllocation:
    def test_value_and_asset_classes(self, analysis):
        assert analysis.value_eur == Decimal("7000.00")
        assert _by_key(analysis.allocation.asset_class) == {
            "equity": (Decimal("3350.00"), pytest.approx(3350 / 7000)),
            "etf": (Decimal("2000.00"), pytest.approx(2000 / 7000)),
            "bond": (Decimal("975.00"), pytest.approx(975 / 7000)),
            "cash": (Decimal("675.00"), pytest.approx(675 / 7000)),
        }
        assert [s.key for s in analysis.allocation.asset_class] == ["equity", "etf", "bond", "cash"]

    def test_currency_of_an_etf_is_its_fund_currency(self, analysis):
        assert _by_key(analysis.allocation.currency) == {
            "EUR": (Decimal("3650.00"), pytest.approx(3650 / 7000)),
            "USD": (Decimal("3350.00"), pytest.approx(3350 / 7000)),
        }

    def test_sectors_with_look_through(self, analysis):
        sectors = _by_key(analysis.allocation.sector)
        assert sectors["Technology"][0] == Decimal("3850.00")  # 2000 + 1350 + 25 % von 2000
        assert sectors["Financial Services"][0] == Decimal("300.00")
        assert sectors["unknown"][0] == Decimal("1200.00")  # 60 % des ETF ohne Angabe
        assert (sectors["bonds"][0], sectors["cash"][0]) == (Decimal("975.00"), Decimal("675.00"))

    def test_countries_from_the_isin_and_the_etf(self, analysis):
        countries = _by_key(analysis.allocation.country)
        assert countries["DE"][0] == Decimal("2975.00")  # SAP und die Bundesanleihe
        assert countries["US"][0] == Decimal("2750.00")  # Apple und 70 % des ETF
        assert countries["JP"][0] == Decimal("100.00")
        assert countries["unknown"][0] == Decimal("500.00")

    def test_without_etf_data_no_look_through(self):
        analysis = analyze(_input(etfs={}))
        assert _by_key(analysis.allocation.sector)["no_look_through"][0] == Decimal("2000.00")
        assert _by_key(analysis.allocation.country)["no_look_through"][0] == Decimal("2000.00")


class TestConcentration:
    def test_largest_and_top_with_look_through(self, analysis):
        concentration = analysis.concentration
        assert concentration.largest is not None
        assert (concentration.largest.isin, concentration.largest.name) == (SAP, "SAP SE")
        apple = next(t for t in concentration.top if t.isin == APPLE)
        assert apple.weight == pytest.approx(1350 / 7000 + 2000 / 7000 * 0.05)
        assert [t.isin for t in concentration.top] == [SAP, APPLE, BUND, MSFT]
        assert concentration.top[-1].name == "MICROSOFT CORP"
        assert concentration.lower_bound is True  # der ETF kennt nur seine groessten

    def test_effective_number_of_positions(self, analysis):
        invested = 6325
        weights = [2000 / invested, 1350 / invested, 2000 / invested, 975 / invested]
        expected = 1 / sum(w * w for w in weights)
        assert analysis.concentration.effective_positions == pytest.approx(expected)


class TestQuality:
    def test_value_weighted_scores(self, analysis):
        quality = analysis.quality
        assert quality.equity_eur == Decimal("3350.00")
        assert quality.composite == pytest.approx((2000 * 0.6 + 1350 * 0.4) / 3350)
        assert quality.value_score == pytest.approx((2000 * 0.4 + 1350 * 0.2) / 3350)
        assert quality.quality_score == pytest.approx((2000 * 0.9 + 1350 * 0.7) / 3350)
        assert (quality.covered, quality.value_traps) == (pytest.approx(1.0), 1)

    def test_quintiles_of_the_reference(self, analysis):
        by_quintile = {q.quintile: (q.count, q.weight) for q in analysis.quality.quintiles}
        assert by_quintile[1] == (1, pytest.approx(1350 / 3350))  # Apple, Perzentil 0,15
        assert by_quintile[4] == (1, pytest.approx(2000 / 3350))  # SAP, Perzentil 0,75
        assert by_quintile[2] == by_quintile[3] == by_quintile[5] == (0, 0.0)

    def test_look_through_score_of_the_etf(self, analysis):
        [fund] = analysis.quality.funds
        assert (fund.isin, fund.score, fund.lower_bound) == (WORLD, None, True)
        assert fund.covered == pytest.approx(0.05)  # nur Apple hat einen Composite

    def test_a_stock_without_score_lowers_the_coverage(self):
        market = Market(**{**MARKET.__dict__, "scores": {SAP: MARKET.scores[SAP]}})
        value = value_depot("depot", LINES, [CashLine(Decimal(675))], market)
        quality = analyze(_input(value=value)).quality
        assert quality.covered == pytest.approx(2000 / 3350)
        assert quality.composite == pytest.approx(0.6)


class TestCostsAndBonds:
    def test_costs_of_the_etfs(self, analysis):
        costs = analysis.costs
        assert (costs.etf_eur, costs.ter, costs.running_costs_eur) == (
            Decimal("2000.00"),
            pytest.approx(0.2),
            Decimal("4.00"),
        )
        assert costs.covered == pytest.approx(1.0)

    def test_bonds_at_the_last_price(self, analysis):
        expected = bond_figures(BUND_TERMS, clean_price=97.5, on=FRIDAY, cfi="DBFTFB")
        bonds = analysis.bonds
        assert bonds.bond_eur == Decimal("975.00")
        assert bonds.ytm == pytest.approx(expected.ytm)
        assert bonds.modified_duration == pytest.approx(expected.modified_duration)
        assert [(m.year, m.value_eur) for m in bonds.maturities] == [(2033, Decimal("975.00"))]
        [position] = bonds.positions
        assert (position.next_coupon, position.special) == (date(2027, 8, 15), None)

    def test_a_floater_has_no_yield(self):
        floater = BondData(BondTerms(coupon=1.0, maturity=date(2030, 1, 1), floating=True))
        bonds = analyze(_input(bonds={BUND: floater})).bonds
        assert (bonds.ytm, bonds.covered, bonds.positions[0].special) == (None, 0.0, "floating")


class TestDataQuality:
    def test_oldest_data(self, analysis):
        data = analysis.data
        assert (data.positions, data.valued, data.look_through) == (4, 4, pytest.approx(1.0))
        assert (data.oldest_price, data.oldest_score, data.oldest_fund_data) == (
            THURSDAY,
            FRIDAY,
            date(2026, 11, 15),
        )

    def test_a_position_without_price_does_not_count(self):
        market = Market(**{**MARKET.__dict__, "quotes": {SAP: MARKET.quotes[SAP]}})
        value = value_depot("depot", LINES, [], market)
        analysis = analyze(_input(value=value))
        assert (analysis.data.positions, analysis.data.valued) == (4, 1)
        assert _by_key(analysis.allocation.asset_class) == {
            "equity": (Decimal("2000.00"), pytest.approx(1.0))
        }

    def test_without_master_data_a_stock_with_score_counts_as_stock(self):
        """Noch "wird geprueft": Scores gibt es nur fuer Aktien."""
        securities = {k: v for k, v in MARKET.securities.items() if k != SAP}
        market = Market(**{**MARKET.__dict__, "securities": securities})
        value = value_depot("depot", LINES, [CashLine(Decimal(675))], market)
        quality = analyze(_input(value=value)).quality
        assert quality.equity_eur == Decimal("3350.00")
        assert quality.composite == pytest.approx((2000 * 0.6 + 1350 * 0.4) / 3350)

    def test_a_watchlist_has_no_value_and_empty_parts(self):
        lines = [HoldingLine(SAP, None)]
        value = value_depot("watchlist", lines, [], MARKET)
        analysis = analyze(_input(value=value))
        assert analysis.value_eur is None
        assert analysis.allocation.asset_class == []
        assert analysis.quality.composite is None
        assert analysis.concentration.largest is None


class TestLabels:
    @pytest.mark.parametrize(
        ("label", "key"),
        [
            ("IT", "Technology"),
            ("Informationstechnologie", "Technology"),
            ("financial_services", "Financial Services"),
            ("Health Care", "Healthcare"),
            ("Cash und/oder Derivate", "cash"),
            ("Raumfahrt", "Raumfahrt"),
            (None, "unknown"),
        ],
    )
    def test_sectors_of_the_sources(self, label, key):
        assert sector_key(label) == key

    def test_countries_as_iso_codes(self):
        assert [country_key(c) for c in ("Vereinigte Staaten", "Japan", "Atlantis")] == [
            "US",
            "JP",
            "Atlantis",
        ]


def test_the_analysis_has_every_part():
    from va_portfolio.domain.analysis import DepotAnalysis

    assert [f.name for f in fields(DepotAnalysis)] == [
        "value_eur",
        "allocation",
        "concentration",
        "quality",
        "costs",
        "bonds",
        "data",
    ]
