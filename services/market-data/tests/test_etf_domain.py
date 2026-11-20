"""ETF-Zusammensetzung (D2.4, WP-10; docs/architecture/depot/wertpapiere.md).

Rein, ohne Ein-/Ausgabe: Gewichte je Sektor, Land und Anlageklasse aus den Positionen eines
Fonds (in Prozent, ohne Angabe „-“), die groessten Positionen und der Hinweis, ob die Liste
vollstaendig ist.
"""

from __future__ import annotations

from datetime import date

import pytest

from va_market_data.domain.etf import (
    TOP_HOLDINGS,
    UNKNOWN,
    EtfComposition,
    FundFacts,
    Holding,
    composition_from_holdings,
    weights,
)

WORLD = "IE00B4L5Y983"
AS_OF = date(2026, 11, 19)

APPLE = Holding("APPLE", 6.0, "US0378331005", "AAPL", "Aktien", "IT", "Vereinigte Staaten", "USD")
MICROSOFT = Holding(
    "MICROSOFT", 4.1, "US5949181045", "MSFT", "Aktien", "IT", "Vereinigte Staaten", "USD"
)
SAP = Holding("SAP", 0.5, "DE0007164600", "SAP", "Aktien", "IT", "Deutschland", "EUR")
NESTLE = Holding(
    "NESTLE", 0.4, "CH0038863350", "NESN", "Aktien", "Basiskonsumgüter", "Schweiz", "CHF"
)
CASH = Holding("USD CASH", 0.2, None, None, "Cash", None, None, "USD")


class TestWeights:
    def test_sum_per_sector_in_percent(self):
        assert weights([APPLE, MICROSOFT, SAP, NESTLE], "sector") == {
            "IT": pytest.approx(10.6),
            "Basiskonsumgüter": pytest.approx(0.4),
        }

    def test_largest_first(self):
        assert list(weights([NESTLE, SAP, APPLE], "country")) == [
            "Vereinigte Staaten",
            "Deutschland",
            "Schweiz",
        ]

    def test_without_label_unknown(self):
        assert weights([APPLE, CASH], "sector") == {"IT": 6.0, UNKNOWN: 0.2}

    def test_negative_positions_count_too(self):
        """Ein Anleihe-ETF fuehrt Geldmarkt-Positionen mit negativem Gewicht (Stand 20.11.2026)."""
        bond = Holding("BUND", 100.3, asset_class="Anleihen")
        money = Holding("EUR CASH", -0.3, asset_class="Geldmarkt")
        assert weights([bond, money], "asset_class") == {
            "Anleihen": pytest.approx(100.3),
            "Geldmarkt": pytest.approx(-0.3),
        }

    def test_unknown_dimension(self):
        with pytest.raises(ValueError, match="name"):
            weights([APPLE], "name")


class TestComposition:
    def test_from_all_holdings(self):
        facts = FundFacts(name="iShares Core MSCI World UCITS ETF", ter=0.2, currency="USD")
        comp = composition_from_holdings(
            WORLD, "ishares", AS_OF, facts, [SAP, APPLE, CASH, MICROSOFT]
        )
        assert (comp.isin, comp.source, comp.as_of, comp.complete) == (
            WORLD,
            "ishares",
            AS_OF,
            True,
        )
        assert comp.facts == facts
        assert comp.holdings_count == 4
        assert comp.sectors == {"IT": pytest.approx(10.6), UNKNOWN: 0.2}
        assert comp.countries["Vereinigte Staaten"] == pytest.approx(10.1)
        assert comp.asset_classes == {"Aktien": pytest.approx(10.6), "Cash": 0.2}

    def test_the_largest_holdings(self):
        comp = composition_from_holdings(
            WORLD, "ishares", AS_OF, FundFacts(), [SAP, APPLE, MICROSOFT]
        )
        assert [h.ticker for h in comp.top(2)] == ["AAPL", "MSFT"]
        assert len(comp.top()) == 3  # weniger Positionen als TOP_HOLDINGS
        assert TOP_HOLDINGS == 10

    def test_an_incomplete_list(self):
        """yfinance kennt nur die zehn groessten Positionen und keine Laender."""
        comp = EtfComposition(
            isin=WORLD,
            source="yahoo",
            as_of=AS_OF,
            complete=False,
            facts=FundFacts(ter=0.2),
            holdings=(APPLE,),
            sectors={"technology": 30.6},
            asset_classes={"Aktien": 99.5},
        )
        assert comp.countries == {}
        assert comp.holdings_count == 1
