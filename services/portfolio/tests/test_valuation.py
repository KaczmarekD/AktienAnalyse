"""Bewertung eines Depots (D3.4, DEP-07, DEP-13, WP-11; docs/architecture/depot/depots.md).

- Wert = Menge x letzter Schlusskurs x Waehrungskurs in EUR; Anleihen Nennwert x Kurs / 100.
- Fehlt der Kurs oder der Waehrungskurs, fehlt der Wert sichtbar (kein stilles 0), mit Grund.
- Ohne Stammdaten heisst die Position "wird geprueft" (``pending``), ein Kurs zaehlt trotzdem.
- Einstand und Differenz je Position und fuer das Depot, nur wo der Einstand erfasst ist.
- Kasse zaehlt zum Depotwert. Eine Beobachtungsliste hat keinen Wert, nur Kurse.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from va_portfolio.domain.depots import CashLine, HoldingLine
from va_portfolio.domain.valuation import (
    Market,
    Quote,
    Score,
    SecurityInfo,
    score_reason,
    value_depot,
)

SAP = "DE0007164600"
APPLE = "US0378331005"
BUND = "DE0001102580"
SHELL = "GB00BP6MXD84"
FRIDAY = date(2026, 11, 20)
THURSDAY = date(2026, 11, 19)


def _market(**overrides) -> Market:
    market = Market(
        securities={
            SAP: SecurityInfo(SAP, "SAP SE", "equity", "EUR"),
            APPLE: SecurityInfo(APPLE, "Apple Inc.", "equity", "USD"),
            BUND: SecurityInfo(BUND, "Bund 2033", "bond", "EUR"),
        },
        quotes={
            SAP: Quote(SAP, FRIDAY, Decimal("231.5"), "EUR", source="yahoo", symbol="SAP.DE"),
            APPLE: Quote(APPLE, THURSDAY, Decimal("190"), "USD", source="yahoo", symbol="AAPL"),
            BUND: Quote(
                BUND, FRIDAY, Decimal("98.94"), "EUR", percent_of_par=True, source="bundesbank"
            ),
        },
        fx={"USD": Decimal("0.92")},
    )
    return Market(**{**market.__dict__, **overrides})


def _line(isin: str, quantity: str | None = "10", **kwargs) -> HoldingLine:
    return HoldingLine(isin, Decimal(quantity) if quantity else None, **kwargs)


class TestPositions:
    def test_shares_in_euro(self):
        value = value_depot("depot", [_line(SAP, "10")], [], _market())
        [sap] = value.positions
        assert sap.value_eur == Decimal("2315.00")
        assert (sap.quote.trade_date, sap.quote.source) == (FRIDAY, "yahoo")  # type: ignore[union-attr]
        assert (sap.fx_rate, sap.missing, sap.pending) == (Decimal(1), None, False)

    def test_foreign_currency_with_the_rate_to_euro(self):
        [apple] = value_depot("depot", [_line(APPLE, "3")], [], _market()).positions
        assert apple.value_eur == Decimal("524.40")  # 3 x 190 USD x 0,92
        assert apple.fx_rate == Decimal("0.92")

    def test_bond_nominal_times_percent(self):
        line = _line(BUND, "10000", unit="nominal")
        [bund] = value_depot("depot", [line], [], _market()).positions
        assert bund.value_eur == Decimal("9894.00")

    def test_fractions_from_savings_plans(self):
        [sap] = value_depot("depot", [_line(SAP, "0.123456")], [], _market()).positions
        assert sap.value_eur == Decimal("28.58")  # kaufmaennisch gerundet auf Cent

    def test_missing_price_is_visible(self):
        market = _market(quotes={})
        [sap] = value_depot("depot", [_line(SAP)], [], market).positions
        assert (sap.value_eur, sap.missing) == (None, "price")

    def test_missing_rate_is_visible(self):
        [apple] = value_depot("depot", [_line(APPLE)], [], _market(fx={})).positions
        assert (apple.value_eur, apple.missing, apple.fx_rate) == (None, "fx", None)

    @pytest.mark.parametrize(
        ("isin", "unit"),
        [(BUND, "pieces"), (SAP, "nominal")],  # Prozentkurs je Stueck / Stueckkurs auf Nennwert
    )
    def test_a_price_that_does_not_fit_the_unit_values_nothing(self, isin, unit):
        [line] = value_depot("depot", [_line(isin, unit=unit)], [], _market()).positions
        assert (line.value_eur, line.missing) == (None, "unit")

    def test_without_master_data_pending_but_valued(self):
        market = _market(securities={})
        [sap] = value_depot("depot", [_line(SAP)], [], market).positions
        assert sap.pending
        assert sap.value_eur == Decimal("2315.00")

    def test_cost_basis_and_difference(self):
        line = _line(SAP, "10", cost_basis_eur=Decimal("2000"))
        [sap] = value_depot("depot", [line], [], _market()).positions
        assert sap.difference_eur == Decimal("315.00")

    def test_difference_in_cents(self):
        line = _line(SAP, "10", cost_basis_eur=Decimal("2000.123"))
        [sap] = value_depot("depot", [line], [], _market()).positions
        assert sap.difference_eur == Decimal("314.88")

    def test_no_difference_without_value_or_cost_basis(self):
        lines = [_line(SAP), _line(APPLE, cost_basis_eur=Decimal("100"))]
        sap, apple = value_depot("depot", lines, [], _market(fx={})).positions
        assert (sap.difference_eur, apple.difference_eur) == (None, None)


class TestDepot:
    def test_total_with_cash(self):
        lines = [_line(SAP, "10"), _line(BUND, "10000", unit="nominal")]
        value = value_depot("depot", lines, [CashLine(Decimal("250.10"))], _market())
        assert value.positions_eur == Decimal("12209.00")
        assert value.cash_eur == Decimal("250.10")
        assert value.value_eur == Decimal("12459.10")
        assert (value.complete, value.unvalued, value.pending) == (True, 0, 0)
        assert value.price_date == FRIDAY

    def test_incomplete_value_says_so(self):
        lines = [_line(SAP, "10"), _line(APPLE, "3")]
        value = value_depot("depot", lines, [], _market(fx={}))
        assert value.value_eur == Decimal("2315.00")  # nur was bewertet ist
        assert (value.complete, value.unvalued) == (False, 1)

    def test_oldest_price_date_is_the_date_of_the_value(self):
        value = value_depot("depot", [_line(SAP), _line(APPLE)], [], _market())
        assert value.price_date == THURSDAY

    def test_cost_basis_and_difference_only_where_known(self):
        lines = [
            _line(SAP, "10", cost_basis_eur=Decimal("2000")),
            _line(APPLE, "3", cost_basis_eur=Decimal("400")),
            _line(BUND, "10000", unit="nominal"),
        ]
        value = value_depot("depot", lines, [], _market(fx={}))  # Apple ohne Wert
        assert value.cost_basis_eur == Decimal("2400")
        assert value.difference_eur == Decimal("315.00")  # nur SAP hat beides

    def test_without_cost_basis_no_sum(self):
        value = value_depot("depot", [_line(SAP)], [], _market())
        assert (value.cost_basis_eur, value.difference_eur) == (None, None)

    def test_pending_positions_are_counted(self):
        value = value_depot("depot", [_line(SAP), _line(SHELL)], [], _market())
        assert value.pending == 1
        assert value.unvalued == 1  # Shell ohne Kurs

    def test_an_empty_depot_is_worth_its_cash(self):
        value = value_depot("depot", [], [CashLine(Decimal("100"))], _market())
        assert (value.value_eur, value.complete, value.price_date) == (
            Decimal("100.00"),
            True,
            None,
        )

    def test_a_watchlist_has_prices_but_no_value(self):
        value = value_depot("watchlist", [_line(SAP, None), _line(APPLE, None)], [], _market())
        assert (value.value_eur, value.positions_eur, value.cost_basis_eur) == (None, None, None)
        assert [p.quote.close for p in value.positions] == [Decimal("231.5"), Decimal("190")]  # type: ignore[union-attr]
        assert all(p.value_eur is None and p.missing is None for p in value.positions)
        assert value.complete


class TestScores:
    """D4.2: Scores je Aktie aus dem juengsten Bewertungslauf, der sie kennt."""

    def _sap(self) -> Score:
        return Score(
            isin=SAP,
            scoring_run_id=7,
            as_of=FRIDAY,
            symbol="SAP.DE",
            reference="universe",
            rank=12,
            value_score=0.41,
            quality_score=0.83,
            composite_score=0.578,
            composite_percentile=0.71,
        )

    def test_a_position_carries_its_score(self):
        market = _market(scores={SAP: self._sap()})
        depot = value_depot("depot", [_line(SAP), _line(APPLE)], [], market)
        sap, apple = depot.positions
        assert sap.score == self._sap()
        assert apple.score is None

    def test_without_price_the_score_stays(self):
        market = _market(quotes={}, scores={SAP: self._sap()})
        [sap] = value_depot("depot", [_line(SAP)], [], market).positions
        assert (sap.missing, sap.score) == ("price", self._sap())

    def test_a_watchlist_has_scores(self):
        market = _market(scores={SAP: self._sap()})
        [sap] = value_depot("watchlist", [_line(SAP, None)], [], market).positions
        assert sap.score == self._sap()

    def test_reason_without_composite(self):
        assert score_reason(0.4, 0.6) is None
        assert score_reason(0.4, None) == "no_quality"
        assert score_reason(None, 0.6) == "no_value"
        assert score_reason(None, None) == "no_data"
