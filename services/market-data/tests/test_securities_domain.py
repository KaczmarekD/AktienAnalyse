"""Fachregeln der Wertpapiere (D2.1, docs/architecture/depot/wertpapiere.md).

- WP-01: Ein Wertpapier ist ueber die ISIN eindeutig; WKN und Symbol sind Zusatzangaben.
- WP-02: Die Suche erkennt ISIN, WKN und Text; unter drei Zeichen sucht sie nicht.
- WP-03: Standard-Listing ist Xetra, sonst die Heimatboerse; ein gewaehltes Listing geht vor.
- Anlageklasse aus dem CFI-Code (ESMA FIRDS), ersatzweise aus OpenFIGI ``securityType2``.
"""

from __future__ import annotations

import pytest

from va_market_data.domain.securities import (
    Listing,
    asset_class_from_cfi,
    asset_class_from_figi,
    choose_listing,
    classify_query,
    isin_from_wkn,
    looks_like_wkn,
    valid_isin,
    yahoo_symbol,
)


class TestIsin:
    @pytest.mark.parametrize(
        "isin",
        [
            "DE0007164600",  # SAP
            "US0378331005",  # Apple
            "IE00B4L5Y983",  # iShares Core MSCI World
            "DE0001102580",  # Bund 0 % 2032
            "DE000A383J95",  # Deutsche Bank 4 % 2028
        ],
    )
    def test_real_isins_are_valid(self, isin):
        assert valid_isin(isin)

    @pytest.mark.parametrize(
        "value",
        ["DE0007164601", "XX000000000", "de0007164600", "DE00071646000", "", "SAP.DE"],
    )
    def test_wrong_check_digit_case_or_length(self, value):
        assert not valid_isin(value)

    def test_german_isin_from_wkn(self):
        """Deutsche ISINs enthalten die WKN: DE000 + WKN + Pruefziffer. OpenFIGI liefert zur WKN
        keine ISIN, deshalb rechnet market-data sie aus."""
        assert isin_from_wkn("716460") == "DE0007164600"
        assert isin_from_wkn("A383J9") == "DE000A383J95"

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("716460", True),
            ("A383J9", True),
            ("A1B2C", False),
            ("A1B2C3D", False),
            ("A1O2C3", False),
            ("SAP.DE", False),
        ],
    )
    def test_wkn_pattern(self, value, expected):
        """Sechs Zeichen aus Ziffern und Grossbuchstaben ohne I und O."""
        assert looks_like_wkn(value) is expected


def _kind_value(raw: str) -> tuple[str, str]:
    query = classify_query(raw)
    assert query is not None
    return query.kind, query.value


class TestQuery:
    def test_isin(self):
        assert _kind_value(" de0007164600 ") == ("isin", "DE0007164600")

    def test_wkn(self):
        assert _kind_value("716460") == ("wkn", "716460")

    def test_text(self):
        assert _kind_value("  MSCI World ") == ("text", "MSCI World")

    def test_an_invalid_isin_is_searched_as_text(self):
        assert _kind_value("DE0007164601")[0] == "text"

    def test_too_short(self):
        assert classify_query("sa") is None
        assert classify_query("   ") is None


class TestAssetClass:
    @pytest.mark.parametrize(
        ("cfi", "expected"),
        [
            ("ESVUFB", "equity"),
            ("CEOGES", "etf"),
            ("DBFTFB", "bond"),
            ("DTVUGB", "bond"),
            ("RWSNCA", "other"),  # Optionsschein
            ("", None),
            (None, None),
        ],
    )
    def test_from_cfi(self, cfi, expected):
        assert asset_class_from_cfi(cfi) == expected

    @pytest.mark.parametrize(
        ("security_type2", "expected"),
        [
            ("Common Stock", "equity"),
            ("Preference", "equity"),
            ("Depositary Receipt", "equity"),
            ("Mutual Fund", "etf"),
            ("ETP", "etf"),
            ("Govt", "bond"),
            ("Corp", "bond"),
            ("Warrant", "other"),
            (None, "other"),
        ],
    )
    def test_from_openfigi(self, security_type2, expected):
        assert asset_class_from_figi(security_type2) == expected


class TestListings:
    def test_yahoo_symbol_from_exchange_code(self):
        assert yahoo_symbol("APC", "GY") == "APC.DE"
        assert yahoo_symbol("SAP", "GF") == "SAP.F"
        assert yahoo_symbol("AAPL", "US") == "AAPL"
        assert yahoo_symbol("IWDA", "NA") == "IWDA.AS"
        assert yahoo_symbol("DB V4 07/12/28 EMTN", "Gettex") is None  # Anleihe: kein Yahoo
        assert yahoo_symbol("X", "ZZ") is None

    def _listings(self) -> list[Listing]:
        return [
            Listing(symbol="SAP", ticker="SAP", exchange="US", currency="USD"),
            Listing(symbol="SAP.DE", ticker="SAP", exchange="GY", currency="EUR"),
            Listing(symbol="SAP.F", ticker="SAP", exchange="GF", currency="EUR"),
        ]

    def test_xetra_first(self):
        chosen = choose_listing(self._listings())
        assert chosen is not None
        assert chosen.symbol == "SAP.DE"

    def test_a_chosen_listing_wins(self):
        chosen = choose_listing(self._listings(), preferred="SAP.F")
        assert chosen is not None
        assert chosen.symbol == "SAP.F"

    def test_otherwise_the_first_with_a_symbol(self):
        listings = [
            Listing(symbol=None, ticker="DB V4", exchange="Gettex", currency="EUR"),
            Listing(symbol="IWDA.AS", ticker="IWDA", exchange="NA", currency="USD"),
        ]
        chosen = choose_listing(listings)
        assert chosen is not None
        assert chosen.symbol == "IWDA.AS"

    def test_none_without_listings(self):
        assert choose_listing([]) is None
