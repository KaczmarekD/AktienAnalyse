"""ETF-Daten aus den Quellen lesen (D2.4, WP-10).

Die Beispiele sind gekuerzte echte Antworten vom 20.11.2026: der Produkt-Screener von iShares
(Fondsliste mit TER, Volumen, Ausschuettung), die Positionen je Fonds (``get-product-data``) und
``funds_data`` von yfinance 1.7. Die Abrufe selbst laufen nicht in den Tests.
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from typing import Any

import pandas as pd
import pytest

from va_market_data.adapters.ishares import (
    ISHARES_SCREENER_URL,
    ISHARES_URL,
    IsharesFunds,
    funds_from_screener,
    holdings_from_payload,
)
from va_market_data.adapters.yahoo import composition_from_funds
from va_market_data.domain.universe import SourceError

WORLD = "IE00B4L5Y983"
CORP = "IE00B3F81R35"
DAX = "DE0005933931"
TODAY = date(2026, 11, 20)


def _screener_entry(**entry: Any) -> dict[str, Any]:
    """Ein Fonds des Screeners; die Antwort hat rund 80 Felder je Fonds, hier die genutzten."""
    return {
        "aladdinAssetClass": "Aktien",
        "productType": "ISHARES_FUND_DATA",
        "productView": ["all", "etf"],
        "onGoingCharges": {"d": "-", "r": 0.2},
        "effectiveDuration": "-",
        "yieldToWorst": "-",
        "totalFundSizeInMillionsAsOf": {"d": "Nov. 19, 2026", "r": 20261119},
        **entry,
    }


SCREENER = {
    "251882": _screener_entry(
        isin=WORLD,
        fundName="iShares Core MSCI World UCITS ETF",
        portfolioId=251882,
        localExchangeTicker="EUNL",
        ter={"d": "0,20", "r": 0.2},
        totalFundSizeInMillions={"d": "142.076,32", "r": 142076.31956343},
        useOfProfits="thesaurierend",
        seriesBaseCurrencyCode="USD",
    ),
    "251726": _screener_entry(
        isin=CORP,
        fundName="iShares Core € Corp Bond UCITS ETF",
        portfolioId=251726,
        aladdinAssetClass="Anleihen",
        ter={"d": "0,09", "r": 0.09},
        totalFundSizeInMillions={"d": "15.483,59", "r": 15483.59377354},
        useOfProfits="ausschüttend",
        seriesBaseCurrencyCode="EUR",
        effectiveDuration={"d": "4,34", "r": 4.33547},
    ),
    # Ein Fonds ohne ISIN (kommt im Screener vor) faellt weg
    "999999": _screener_entry(isin="-", fundName="iShares Platzhalter", portfolioId=999999),
}


def _column(values: list[Any]) -> dict[str, Any]:
    """Eine Spalte wie bei iShares: ``value`` und ``formattedValue`` mit Beschriftung."""
    return {"name": "x", "visible": True, "label": "", "value": values, "formattedValue": values}


def _holdings(as_of: int, **columns: list[Any]) -> dict[str, Any]:
    points = {name: _column(values) for name, values in columns.items()}
    points["asOfDate"] = {"name": "asOfDate", "value": as_of, "formattedValue": "19.Nov.2026"}
    points["dateList"] = {"name": "dateList", "value": [as_of, 20261030]}
    return {
        "componentsByNameMap": {
            "holdings": {"containersByNameMap": {"all": {"dataPointsByNameMap": points}}}
        }
    }


WORLD_HOLDINGS = _holdings(
    20261119,
    ticker=["AAPL", "MSFT", "SAP"],
    isin=["US0378331005", "US5949181045", "DE0007164600"],
    issueName=["APPLE", "MICROSOFT", "SAP"],
    assetClass=["Aktien", "Aktien", "Aktien"],
    sectorName=["IT", "IT", "IT"],
    countryOfRisk=["Vereinigte Staaten", "Vereinigte Staaten", "Deutschland"],
    holdingPercent=[6.00083, 4.11428, 0.51],
    marketCurrencyCode=["USD", "USD", "EUR"],
    exchange=["NASDAQ", "NASDAQ", "Xetra"],
    marketValue=[8530605246.16, 5848739444.0, 725000000.0],
    unitPrice=[349.21, 512.3, 240.1],
)

CORP_HOLDINGS = _holdings(
    20261119,
    ticker=["JPM", "ABIBB", "EUR"],
    isin=["XS2461234622", "BE6285457519", None],
    issueName=["JPMORGAN CHASE & CO MTN RegS", "ANHEUSER-BUSCH INBEV NV MTN RegS", "EUR CASH"],
    assetClass=["Anleihen", "Anleihen", "Geldmarkt"],
    sectorName=["Bankwesen", "Nicht-zyklische Konsumgüter", "Cash und/oder Derivate"],
    countryOfRisk=["Vereinigte Staaten", "Belgien", "Europäische Union"],
    holdingPercent=[0.08519, 0.08161, -0.27472],
    marketCurrencyCode=["EUR", "EUR", "EUR"],
    couponRate=[1.96, 2.75, None],
    maturityDate=[20300323, 20360317, None],
    exchange=[None, None, None],
)


class TestIsharesScreener:
    def test_funds_by_isin(self):
        funds = funds_from_screener(SCREENER)
        assert set(funds) == {WORLD, CORP}
        world = funds[WORLD]
        assert world.portfolio_id == "251882"
        facts = world.facts
        assert (facts.name, facts.ter, facts.currency) == (
            "iShares Core MSCI World UCITS ETF",
            0.2,
            "USD",
        )
        assert facts.fund_size == pytest.approx(142076.32, abs=0.01)
        assert (facts.distribution, facts.provider, facts.effective_duration) == (
            "accumulating",
            "iShares",
            None,
        )

    def test_a_bond_fund(self):
        facts = funds_from_screener(SCREENER)[CORP].facts
        assert facts.distribution == "distributing"
        assert facts.effective_duration == pytest.approx(4.33547)

    def test_an_unknown_distribution_stays_empty(self):
        entry = _screener_entry(isin=WORLD, portfolioId=1, fundName="x", useOfProfits="gemischt")
        assert funds_from_screener({"1": entry})[WORLD].facts.distribution is None

    def test_an_odd_entry_is_skipped(self):
        """Ein Eintrag, der kein Fonds ist, kostet nicht die ganze Liste."""
        funds = funds_from_screener({**SCREENER, "meta": "Stand 20.11.2026"})
        assert set(funds) == {WORLD, CORP}

    @pytest.mark.parametrize("payload", [[], "<html>", {"1": "kein Fonds"}])
    def test_a_wrong_structure_is_an_error_of_the_source(self, payload):
        with pytest.raises(SourceError):
            funds_from_screener(payload)


class TestIsharesHoldings:
    def test_all_holdings_with_their_labels(self):
        as_of, holdings = holdings_from_payload(WORLD_HOLDINGS)
        assert as_of == date(2026, 11, 19)
        assert [h.ticker for h in holdings] == ["AAPL", "MSFT", "SAP"]
        apple = holdings[0]
        assert (apple.name, apple.isin, apple.weight) == ("APPLE", "US0378331005", 6.00083)
        assert (apple.asset_class, apple.sector, apple.country, apple.currency) == (
            "Aktien",
            "IT",
            "Vereinigte Staaten",
            "USD",
        )

    def test_a_bond_fund_with_cash(self):
        _, holdings = holdings_from_payload(CORP_HOLDINGS)
        cash = holdings[2]
        assert (cash.isin, cash.asset_class, cash.weight) == (None, "Geldmarkt", -0.27472)

    def test_a_row_without_weight_is_left_out(self):
        payload = _holdings(
            20261119,
            ticker=["AAPL", "FUT"],
            isin=["US0378331005", None],
            issueName=["APPLE", "S&P500 EMINI DEC 26"],
            assetClass=["Aktien", "Futures"],
            sectorName=["IT", None],
            countryOfRisk=["Vereinigte Staaten", None],
            holdingPercent=[6.0, None],
            marketCurrencyCode=["USD", "USD"],
        )
        assert [h.ticker for h in holdings_from_payload(payload)[1]] == ["AAPL"]

    def test_a_wrong_structure_is_an_error_of_the_source(self):
        with pytest.raises(SourceError):
            holdings_from_payload({"componentsByNameMap": {}})

    def test_columns_of_different_length_are_an_error(self):
        payload = _holdings(
            20261119,
            ticker=["AAPL"],
            isin=["US0378331005", "US5949181045"],
            issueName=["APPLE"],
            assetClass=["Aktien"],
            sectorName=["IT"],
            countryOfRisk=["Vereinigte Staaten"],
            holdingPercent=[6.0],
            marketCurrencyCode=["USD"],
        )
        with pytest.raises(SourceError):
            holdings_from_payload(payload)


class FakeFetch:
    """``(url, params) -> JSON``; zaehlt die Abrufe je URL."""

    def __init__(self, *, screener: Any = SCREENER, error: Exception | None = None) -> None:
        self.screener = screener
        self.error = error
        self.calls: list[tuple[str, dict[str, str]]] = []

    def __call__(self, url: str, params: dict[str, str]) -> Any:
        self.calls.append((url, params))
        if url == ISHARES_SCREENER_URL:
            if self.error is not None:
                raise self.error
            return self.screener
        assert url == ISHARES_URL
        return {"251882": WORLD_HOLDINGS, "251726": CORP_HOLDINGS}[params["portfolioId"]]


class TestIsharesFunds:
    def test_a_fund_with_all_holdings(self):
        fetch = FakeFetch()
        comp = IsharesFunds(fetch=fetch, today=lambda: TODAY).composition(WORLD, "EUNL.DE")
        assert comp is not None
        assert (comp.source, comp.as_of, comp.complete, comp.holdings_count) == (
            "ishares",
            date(2026, 11, 19),
            True,
            3,
        )
        assert comp.facts.ter == 0.2
        assert comp.countries["Deutschland"] == pytest.approx(0.51)
        assert fetch.calls[1][1]["portfolioId"] == "251882"

    def test_the_fund_list_is_read_once(self):
        fetch = FakeFetch()
        funds = IsharesFunds(fetch=fetch, today=lambda: TODAY)
        funds.composition(WORLD, None)
        funds.composition(CORP, None)
        assert [url for url, _ in fetch.calls].count(ISHARES_SCREENER_URL) == 1

    def test_another_provider_is_not_an_ishares_fund(self):
        fetch = FakeFetch()
        assert (
            IsharesFunds(fetch=fetch, today=lambda: TODAY).composition("IE00BJ0KDQ92", "XDWD.DE")
            is None
        )
        assert [url for url, _ in fetch.calls] == [ISHARES_SCREENER_URL]

    def test_a_failing_fund_list_fails_once(self):
        """Faellt der Screener aus, fragt der Lauf nicht fuer jeden ETF erneut (3,8 MB); ab dem
        zweiten ETF nur noch ein Fehler der Quelle, ohne Traceback im Log."""
        fetch = FakeFetch(error=ConnectionError("weg"))
        funds = IsharesFunds(fetch=fetch, today=lambda: TODAY)
        with pytest.raises(ConnectionError):
            funds.composition(WORLD, None)
        with pytest.raises(SourceError, match="ConnectionError: weg"):
            funds.composition(CORP, None)
        assert len(fetch.calls) == 1

    def test_an_old_list_is_an_error_of_the_source(self):
        """Ein aufgeloester Fonds nennt sonst eine alte Liste als vollstaendig."""
        funds = IsharesFunds(fetch=FakeFetch(), today=lambda: date(2027, 1, 15))
        with pytest.raises(SourceError, match="Tage alt"):
            funds.composition(WORLD, None)


def _operations(symbol: str, ter: float | None) -> pd.DataFrame:
    return pd.DataFrame(
        {symbol: [ter, 0.28, 290538.38], "Category Average": [pd.NA, pd.NA, 290538.38]},
        index=pd.Index(
            ["Annual Report Expense Ratio", "Annual Holdings Turnover", "Total Net Assets"],
            name="Attributes",
        ),
    )


def _top(rows: list[tuple[str, str, float]]) -> pd.DataFrame:
    frame = pd.DataFrame(
        [(name, weight) for _, name, weight in rows], columns=["Name", "Holding Percent"]
    )
    frame.index = pd.Index([symbol for symbol, _, _ in rows], name="Symbol")
    return frame


XTRACKERS_WORLD = SimpleNamespace(
    fund_operations=_operations("XDWD.DE", 0.0012),
    asset_classes={
        "cashPosition": 0.0037,
        "stockPosition": 0.9959,
        "bondPosition": 0.0,
        "preferredPosition": 0.0,
        "convertiblePosition": 0.0,
        "otherPosition": 0.0004,
    },
    sector_weightings={"technology": 0.3062, "financial_services": 0.1598, "realestate": 0.0163},
    top_holdings=_top([("AAPL", "Apple Inc", 0.056287), ("NVDA", "NVIDIA Corp", 0.05231)]),
    fund_overview={
        "categoryName": None,
        "family": "DWS Investment S.A. (ETF)",
        "legalType": "Exchange Traded Fund",
    },
)

XTRACKERS_BUND = SimpleNamespace(
    fund_operations=_operations("DBXG.DE", 0.0015),
    asset_classes={"cashPosition": 0.0024, "stockPosition": 0.0, "bondPosition": 0.9976},
    sector_weightings={},
    top_holdings=_top([]),
    fund_overview={"family": "DWS Investment S.A. (ETF)"},
)


class TestYahooFunds:
    def test_a_share_etf_of_another_provider(self):
        comp = composition_from_funds("IE00BJ0KDQ92", XTRACKERS_WORLD, TODAY)
        assert comp is not None
        assert (comp.source, comp.as_of, comp.complete) == ("yahoo", TODAY, False)
        assert comp.facts.ter == pytest.approx(0.12)  # yfinance: Anteil, hier in Prozent
        assert comp.facts.provider == "DWS Investment S.A. (ETF)"
        assert comp.facts.fund_size is None  # „Total Net Assets“ ist unzuverlaessig
        assert comp.asset_classes == {
            "Aktien": pytest.approx(99.59),
            "Cash": pytest.approx(0.37),
            "Sonstige": pytest.approx(0.04),
        }
        assert comp.sectors["technology"] == pytest.approx(30.62)
        assert comp.countries == {}
        assert [(h.ticker, h.name) for h in comp.holdings] == [
            ("AAPL", "Apple Inc"),
            ("NVDA", "NVIDIA Corp"),
        ]
        assert comp.holdings[0].weight == pytest.approx(5.6287)

    def test_a_bond_etf_without_sectors_and_holdings(self):
        comp = composition_from_funds("LU0643975591", XTRACKERS_BUND, TODAY)
        assert comp is not None
        assert comp.asset_classes == {"Anleihen": pytest.approx(99.76), "Cash": pytest.approx(0.24)}
        assert (comp.sectors, comp.holdings) == ({}, ())

    def test_nothing_known_is_no_result(self):
        """yfinance meldet manche Fehler als leere Antwort: das ist kein Stand."""
        empty = SimpleNamespace(
            fund_operations=pd.DataFrame(),
            asset_classes={},
            sector_weightings={},
            top_holdings=pd.DataFrame(),
            fund_overview={},
        )
        assert composition_from_funds("IE00BJ0KDQ92", empty, TODAY) is None

    def test_a_missing_ter_stays_empty(self):
        funds = SimpleNamespace(
            **{**vars(XTRACKERS_WORLD), "fund_operations": _operations("VWCE.DE", None)}
        )
        comp = composition_from_funds("IE00BK5BQT80", funds, TODAY)
        assert comp is not None
        assert comp.facts.ter is None
