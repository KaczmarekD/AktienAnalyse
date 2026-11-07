"""Antworten der Quellen fuer Wertpapiere lesen (D2.1).

Die Beispiele sind gekuerzte echte Antworten vom 07.11.2026 (ESMA FIRDS, OpenFIGI, Suche von
Yahoo). Die Abrufe selbst laufen nicht in den Tests.
"""

from __future__ import annotations

from datetime import date

from va_market_data.adapters.firds import master_from_firds
from va_market_data.adapters.openfigi import lookup_from_figi
from va_market_data.adapters.yahoo import hits_from_yahoo_search

FIRDS_BOND = {
    "isin": "DE000A383J95",
    "gnr_full_name": "DB  4.000  7/12/28 c27 (URegS) DEUTSCHE BANK",
    "gnr_cfi_code": "DTVUGB",
    "gnr_notional_curr_code": "EUR",
    "lei": "7LTWFZYICNSX8D621K86",
    "bnd_maturity_date": "2028-07-12T00:00:00Z",
    "bnd_nmnl_value_unit": "100000",
    "bnd_fixed_rate": "4",
    "bnd_seniority": "SNDB",
    "latest_received_flag": "1",
}

FIRDS_SHARE = {
    "isin": "DE0007164600",
    "gnr_full_name": "SAP SE",
    "gnr_cfi_code": "ESVUFB",
    "gnr_notional_curr_code": "EUR",
    "lei": "529900D6BF99LW9R2E68",
    "latest_received_flag": "1",
}


class TestFirds:
    def test_a_bond(self):
        master = master_from_firds(FIRDS_BOND)
        assert (master.isin, master.asset_class, master.currency, master.lei, master.cfi) == (
            "DE000A383J95",
            "bond",
            "EUR",
            "7LTWFZYICNSX8D621K86",
            "DTVUGB",
        )
        assert master.bond is not None
        assert (master.bond.coupon, master.bond.maturity, master.bond.denomination) == (
            4.0,
            date(2028, 7, 12),
            100000.0,
        )
        assert master.bond.seniority == "SNDB"
        # Dritte Stelle des CFI-Codes: V variabel, trotz festem Kupon (kuendbar ab 2027)
        assert master.bond.floating

    def test_a_share_has_no_bond_terms(self):
        master = master_from_firds(FIRDS_SHARE)
        assert (master.name, master.asset_class, master.bond) == ("SAP SE", "equity", None)

    def test_missing_fields_stay_empty(self):
        master = master_from_firds({"isin": "DE0001102580", "gnr_cfi_code": "DBFTFB"})
        assert master.asset_class == "bond"
        assert master.bond is not None
        assert (master.bond.coupon, master.bond.maturity, master.bond.floating) == (
            None,
            None,
            False,
        )
        assert master.name == "DE0001102580"  # ohne Namen die ISIN


class TestOpenFigi:
    def test_listings_with_yahoo_symbols(self):
        answer = {
            "data": [
                {
                    "name": "APPLE INC",
                    "ticker": "APC",
                    "exchCode": "GY",
                    "securityType2": "Common Stock",
                    "marketSector": "Equity",
                },
                {
                    "name": "APPLE INC",
                    "ticker": "AAPL",
                    "exchCode": "US",
                    "securityType2": "Common Stock",
                    "marketSector": "Equity",
                },
            ]
        }
        result = lookup_from_figi(answer)
        assert result is not None
        assert (result.name, result.asset_class) == ("APPLE INC", "equity")
        assert [(entry.symbol, entry.exchange) for entry in result.listings] == [
            ("APC.DE", "GY"),
            ("AAPL", "US"),
        ]

    def test_a_bond_has_no_yahoo_symbol(self):
        answer = {
            "data": [
                {
                    "name": "DEUTSCHE BANK AG",
                    "ticker": "DB V4 07/12/28 EMTN",
                    "exchCode": "Gettex",
                    "securityType2": "Corp",
                }
            ]
        }
        result = lookup_from_figi(answer)
        assert result is not None
        assert result.asset_class == "bond"
        assert [entry.symbol for entry in result.listings] == [None]

    def test_errors_and_empty_answers(self):
        assert lookup_from_figi({"error": "Invalid idValue format."}) is None
        assert lookup_from_figi({"warning": "No identifier found."}) is None
        assert lookup_from_figi({"data": []}) is None
        assert lookup_from_figi("kaputt") is None


class TestYahooSearch:
    def test_quotes_become_hits_without_isin(self):
        quotes = [
            {
                "symbol": "EUNL.DE",
                "shortname": "iShsIII-Core MSCI World U.ETF R",
                "longname": "iShares Core MSCI World UCITS ETF USD (Acc)",
                "quoteType": "ETF",
                "exchange": "GER",
            },
            {"symbol": "SAP.DE", "shortname": "SAP SE", "quoteType": "EQUITY", "exchange": "GER"},
            {"symbol": "^GDAXI", "shortname": "DAX", "quoteType": "INDEX", "exchange": "GER"},
            {"symbol": "EURUSD=X", "quoteType": "CURRENCY"},
        ]
        hits = hits_from_yahoo_search(quotes)
        assert [(h.isin, h.name, h.asset_class, h.source) for h in hits] == [
            (None, "iShares Core MSCI World UCITS ETF USD (Acc)", "etf", "yahoo"),
            (None, "SAP SE", "equity", "yahoo"),
        ]
        assert hits[0].listings[0].symbol == "EUNL.DE"
