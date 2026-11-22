"""Depots und Depotstaende (D3.1, DEP-01, 02, 03, 04, 09, 11; docs/architecture/depot/depots.md).

Rein, ohne Ein-/Ausgabe:
- Ein Depot hat Name (1-100 Zeichen) und optional eine Beschreibung; Art ``depot`` oder
  ``watchlist``.
- Positionen je ISIN einmal, mit gueltiger Pruefziffer. Im Depot mit Menge > 0, in der
  Beobachtungsliste ohne Menge, ohne Einstand und ohne Kasse.
- Ein neuer Depotstand bekommt die naechste Version, aber nur auf die neueste als Basis.
- Der Unterschied zweier Staende nach ISIN: neu, geaendert, entfallen.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from va_portfolio.domain.depots import (
    CashLine,
    DepotError,
    HoldingLine,
    VersionConflict,
    check_holdings,
    check_name,
    diff,
    next_version,
)

SAP = "DE0007164600"
APPLE = "US0378331005"
BUND = "DE0001102580"


def _line(isin: str = SAP, quantity: str | None = "10", **kwargs) -> HoldingLine:
    return HoldingLine(isin, Decimal(quantity) if quantity is not None else None, **kwargs)


class TestName:
    def test_trimmed(self):
        assert check_name("  Altersvorsorge ", "  Sparplan  ") == ("Altersvorsorge", "Sparplan")

    def test_an_empty_description_is_none(self):
        assert check_name("DKB", "   ") == ("DKB", None)

    @pytest.mark.parametrize("name", ["", "   ", "x" * 101])
    def test_name_length(self, name):
        with pytest.raises(DepotError, match="Name"):
            check_name(name, None)

    def test_description_length(self):
        with pytest.raises(DepotError, match="Beschreibung"):
            check_name("DKB", "x" * 501)


class TestHoldings:
    def test_a_depot_with_fractions_cost_and_cash(self):
        lines, cash = check_holdings(
            "depot",
            [
                _line(SAP, "12.5", cost_basis_eur=Decimal("1500.00"), note=" Kaufgrund "),
                _line(BUND, "10000", unit="nominal"),
            ],
            [CashLine(Decimal("250.10"))],
        )
        assert [line.isin for line in lines] == [SAP, BUND]
        assert lines[0].note == "Kaufgrund"
        assert lines[1].unit == "nominal"
        assert cash == (CashLine(Decimal("250.10")),)

    def test_isin_in_lower_case_is_fine(self):
        lines, _ = check_holdings("depot", [_line(SAP.lower())], [])
        assert lines[0].isin == SAP

    def test_a_wrong_check_digit(self):
        with pytest.raises(DepotError, match="ISIN"):
            check_holdings("depot", [_line("DE0007164601")], [])

    def test_each_isin_once(self):
        with pytest.raises(DepotError, match="doppelt"):
            check_holdings("depot", [_line(SAP, "1"), _line(SAP, "2")], [])

    @pytest.mark.parametrize("quantity", [None, "0", "-1"])
    def test_a_depot_needs_a_positive_quantity(self, quantity):
        with pytest.raises(DepotError, match="Menge"):
            check_holdings("depot", [_line(SAP, quantity)], [])

    def test_a_negative_cost_basis(self):
        with pytest.raises(DepotError, match="Einstand"):
            check_holdings("depot", [_line(SAP, cost_basis_eur=Decimal("-1"))], [])

    def test_an_unknown_unit(self):
        with pytest.raises(DepotError, match="Einheit"):
            check_holdings("depot", [_line(SAP, unit="kilo")], [])  # type: ignore[arg-type]

    def test_a_long_note(self):
        with pytest.raises(DepotError, match="Notiz"):
            check_holdings("depot", [_line(SAP, note="x" * 501)], [])

    def test_cash_only_in_euro_and_once(self):
        with pytest.raises(DepotError, match="Kasse"):
            check_holdings("depot", [], [CashLine(Decimal("1"), "USD")])
        with pytest.raises(DepotError, match="Kasse"):
            check_holdings("depot", [], [CashLine(Decimal("1")), CashLine(Decimal("2"))])

    def test_a_watchlist_has_no_quantities_and_no_cash(self):
        lines, cash = check_holdings("watchlist", [_line(SAP, None), _line(APPLE, None)], [])
        assert [line.quantity for line in lines] == [None, None]
        assert cash == ()
        with pytest.raises(DepotError, match="Beobachtungsliste"):
            check_holdings("watchlist", [_line(SAP, "1")], [])
        with pytest.raises(DepotError, match="Beobachtungsliste"):
            check_holdings("watchlist", [], [CashLine(Decimal("1"))])

    def test_too_many_positions(self):
        from va_contracts.portfolio import MAX_LINES

        isins = [f"DE000{n:06d}" for n in range(MAX_LINES + 1)]
        with pytest.raises(DepotError, match="Positionen"):
            check_holdings("watchlist", [_line(i, None) for i in isins], [])


class TestVersion:
    def test_the_next_version(self):
        assert next_version(newest=0, base=0) == 1
        assert next_version(newest=7, base=7) == 8

    def test_an_old_base_is_a_conflict(self):
        with pytest.raises(VersionConflict) as caught:
            next_version(newest=8, base=7)
        assert caught.value.newest == 8


class TestDiff:
    def test_added_changed_removed(self):
        before = [_line(SAP, "10"), _line(APPLE, "5"), _line(BUND, "1000", unit="nominal")]
        after = [_line(SAP, "12"), _line(BUND, "1000", unit="nominal"), _line("IE00B4L5Y983", "3")]
        change = diff(before, after)
        assert (change.added, change.changed, change.removed) == (1, 1, 1)

    def test_a_new_note_is_a_change(self):
        assert diff([_line(SAP)], [_line(SAP, note="Kaufgrund")]).changed == 1

    def test_equal_quantities_in_other_notation(self):
        assert diff([_line(SAP, "10")], [_line(SAP, "10.000")]).changed == 0
