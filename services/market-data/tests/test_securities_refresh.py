"""Stammdaten und ETF-Daten der Abdeckung im Wochenlauf (D2.4, WP-04, WP-07, WP-10).

Je Wertpapier der Abdeckung:
- Stammdaten aus ESMA FIRDS, gespeichert als neue Zeile nur bei Aenderung (das prueft der
  Katalog); ohne FIRDS die gespeicherten, ohne beides steht die ISIN in ``missing``.
- Bei ETFs die Zusammensetzung: die Quellen der Reihe nach (iShares, dann yfinance). Eine
  vollstaendige Liste geht vor einer unvollstaendigen, auch eine gespeicherte bis 31 Tage. Ohne
  frische Daten gilt die zuletzt gespeicherte.
- Ein Ausfall kostet nur dieses Wertpapier.

Die Quellen sind Fakes hinter den Ports.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

import pytest

from va_market_data.application.securities import refresh_securities
from va_market_data.domain.coverage import CoverageItem
from va_market_data.domain.etf import EtfComposition, FundFacts, Holding
from va_market_data.domain.securities import BondTerms, Listing, SecurityHit, SecurityMaster

NOW = datetime(2026, 11, 21, 8, 0, tzinfo=UTC)
TODAY = NOW.date()
SAP = "DE0007164600"
WORLD = "IE00B4L5Y983"
XTRACKERS = "IE00BJ0KDQ92"
BUND = "DE0001102580"

SAP_MASTER = SecurityMaster(SAP, "SAP SE", "equity", "EUR", "529900D6BF99LW9R2E68", "ESVUFB")
WORLD_MASTER = SecurityMaster(WORLD, "ISHSIII-CORE MSCI WORLD", "etf", "USD", cfi="CEOGMS")
XTRACKERS_MASTER = SecurityMaster(XTRACKERS, "XTR.(IE)-MSCI WORLD", "etf", "USD", cfi="CEOJLS")
BUND_MASTER = SecurityMaster(
    BUND, "Bund 0% 2030", "bond", "EUR", cfi="DBZTFB", bond=BondTerms(0.0, date(2030, 2, 15))
)

ITEMS = [
    CoverageItem(SAP, "equity", "SAP.DE", "SAP.DE"),
    CoverageItem(WORLD, "etf", None, "EUNL.DE"),
    CoverageItem(BUND, "bond", None, None),
]


def _comp(isin: str, source: str, *, complete: bool, as_of: date = date(2026, 11, 19)):
    return EtfComposition(
        isin=isin,
        source=source,
        as_of=as_of,
        complete=complete,
        facts=FundFacts(ter=0.2),
        holdings=(Holding("APPLE", 6.0, ticker="AAPL"),),
    )


@dataclass
class FakeCatalog:
    stored: dict[str, SecurityMaster] = field(default_factory=dict)
    listings: dict[str, tuple[Listing, ...]] = field(default_factory=dict)
    saved: list[SecurityMaster] = field(default_factory=list)
    error: Exception | None = None

    def get(self, isin: str) -> SecurityHit | None:
        if self.error:
            raise self.error
        master = self.stored.get(isin)
        if master is None:
            return None
        return SecurityHit(
            isin, master.name, master.asset_class, self.listings.get(isin, ()), "catalog"
        )

    def master(self, isin: str) -> SecurityMaster | None:
        if self.error:
            raise self.error
        return self.stored.get(isin)

    def save(self, master: SecurityMaster, listings: tuple[Listing, ...], *, at: datetime) -> None:
        if self.error:
            raise self.error
        self.saved.append(master)
        self.stored[master.isin] = master


@dataclass
class FakeFirds:
    masters: dict[str, SecurityMaster] = field(default_factory=dict)
    failing: set[str] = field(default_factory=set)

    def master(self, isin: str) -> SecurityMaster | None:
        if isin in self.failing:
            raise ConnectionError("FIRDS weg")
        return self.masters.get(isin)


@dataclass
class FakeEtfSource:
    name: str
    answers: dict[str, EtfComposition] = field(default_factory=dict)
    error: Exception | None = None
    calls: list[tuple[str, str | None]] = field(default_factory=list)

    def composition(self, isin: str, symbol: str | None) -> EtfComposition | None:
        self.calls.append((isin, symbol))
        if self.error:
            raise self.error
        return self.answers.get(isin)


@dataclass
class FakeCompositions:
    """Wie die Datenbank: Was geschrieben wird, ist danach der juengste Stand."""

    stored: list[EtfComposition] = field(default_factory=list)
    written: list[EtfComposition] = field(default_factory=list)
    error: Exception | None = None

    def write_composition(self, composition: EtfComposition, *, at: datetime) -> bool:
        if self.error:
            raise self.error
        self.written.append(composition)
        self.stored.append(composition)
        return True

    def latest_composition(
        self, isin: str, *, complete_only: bool = False
    ) -> EtfComposition | None:
        if self.error:
            raise self.error
        rows = [c for c in self.stored if c.isin == isin and (c.complete or not complete_only)]
        # juengster Stand, bei gleichem Stand die zuletzt gespeicherte
        return max(reversed(rows), key=lambda c: c.as_of, default=None)


class Timer:
    """Monotone Uhr der Aktualisierung; jede Abfrage der Quellen kostet eine Minute."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


@dataclass
class World:
    catalog: FakeCatalog = field(default_factory=FakeCatalog)
    firds: FakeFirds = field(
        default_factory=lambda: FakeFirds(
            {m.isin: m for m in (SAP_MASTER, WORLD_MASTER, BUND_MASTER)}
        )
    )
    ishares: FakeEtfSource = field(
        default_factory=lambda: FakeEtfSource(
            "ishares", {WORLD: _comp(WORLD, "ishares", complete=True)}
        )
    )
    yahoo: FakeEtfSource = field(
        default_factory=lambda: FakeEtfSource(
            "yahoo",
            {
                WORLD: _comp(WORLD, "yahoo", complete=False, as_of=TODAY),
                XTRACKERS: _comp(XTRACKERS, "yahoo", complete=False, as_of=TODAY),
            },
        )
    )
    compositions: FakeCompositions = field(default_factory=FakeCompositions)
    timer: Timer = field(default_factory=Timer)

    def refresh(self, items=ITEMS, **kwargs):
        return refresh_securities(
            items,
            catalog=self.catalog,
            master=self.firds,
            etf_sources=[self.ishares, self.yahoo],
            compositions=self.compositions,
            clock=lambda: NOW,
            timer=self.timer,
            **kwargs,
        )


@pytest.fixture
def world() -> World:
    return World()


class TestMasterData:
    def test_every_security_of_the_coverage(self, world):
        world.catalog.listings[SAP] = (Listing("SAP.DE", "SAP", "GY", "EUR"),)
        result = world.refresh()
        assert [s.master.isin for s in result.securities] == [SAP, WORLD, BUND]
        assert result.missing == []
        sap = result.securities[0]
        assert sap.master == SAP_MASTER
        assert sap.listing == Listing("SAP.DE", "SAP", "GY", "EUR")
        assert sap.etf is None
        assert world.catalog.saved == [SAP_MASTER, WORLD_MASTER, BUND_MASTER]

    def test_the_price_listing_of_the_coverage_is_chosen(self, world):
        world.catalog.listings[WORLD] = (
            Listing("IWDA.AS", "IWDA", "NA", "USD"),
            Listing("EUNL.DE", "EUNL", "GY", "EUR"),
        )
        world.catalog.stored[WORLD] = WORLD_MASTER
        world_etf = world.refresh().securities[1]
        assert world_etf.listing is not None
        assert world_etf.listing.symbol == "EUNL.DE"
        assert len(world_etf.listings) == 2

    def test_without_firds_the_stored_master_data(self, world):
        world.firds.failing.add(SAP)
        world.catalog.stored[SAP] = SAP_MASTER
        result = world.refresh()
        assert result.securities[0].master == SAP_MASTER
        assert SAP_MASTER not in world.catalog.saved

    def test_without_any_master_data_the_isin_is_missing(self, world):
        world.firds.failing.add(SAP)
        result = world.refresh()
        assert [s.master.isin for s in result.securities] == [WORLD, BUND]
        assert result.missing == [SAP]

    def test_an_isin_is_refreshed_once(self, world):
        result = world.refresh([ITEMS[0], ITEMS[0]])
        assert len(result.securities) == 1

    def test_a_broken_catalog_costs_only_the_storage(self, world):
        """Die Datenbank fehlt: die frischen Stammdaten gelten trotzdem, nur ohne Listings."""
        world.catalog.error = ConnectionError("db weg")
        result = world.refresh()
        assert [s.master.isin for s in result.securities] == [SAP, WORLD, BUND]
        assert result.securities[0].listings == ()


class TestEtf:
    def test_ishares_first(self, world):
        etf = world.refresh().securities[1].etf
        assert etf is not None
        assert (etf.source, etf.complete) == ("ishares", True)
        assert world.ishares.calls == [(WORLD, "EUNL.DE")]
        assert world.yahoo.calls == []
        assert world.compositions.written == [etf]

    def test_another_provider_from_yahoo(self, world):
        world.firds.masters[XTRACKERS] = XTRACKERS_MASTER
        result = world.refresh([CoverageItem(XTRACKERS, "etf", None, "XDWD.DE")])
        etf = result.securities[0].etf
        assert etf is not None
        assert (etf.source, etf.complete) == ("yahoo", False)
        assert world.yahoo.calls == [(XTRACKERS, "XDWD.DE")]

    def test_a_failing_source_leaves_the_next(self, world):
        world.ishares.error = ConnectionError("iShares weg")
        etf = world.refresh().securities[1].etf
        assert etf is not None
        assert etf.source == "yahoo"

    def test_a_recent_complete_list_beats_a_fresh_incomplete_one(self, world):
        """iShares faellt eine Woche aus: die Liste der Vorwoche statt der zehn groessten."""
        world.ishares.error = ConnectionError("iShares weg")
        last_week = _comp(WORLD, "ishares", complete=True, as_of=date(2026, 11, 13))
        world.compositions.stored.append(last_week)
        assert world.refresh().securities[1].etf == last_week
        # Gespeichert wird die frische trotzdem, und sie ist danach der juengste Stand
        assert [c.source for c in world.compositions.written] == ["yahoo"]
        assert world.compositions.latest_composition(WORLD) == world.compositions.written[0]

    def test_an_old_complete_list_does_not(self, world):
        world.ishares.error = ConnectionError("iShares weg")
        world.compositions.stored.append(
            _comp(WORLD, "ishares", complete=True, as_of=date(2026, 10, 1))
        )
        etf = world.refresh().securities[1].etf
        assert etf is not None
        assert etf.source == "yahoo"

    def test_without_fresh_data_the_stored_one(self, world):
        world.ishares.error = ConnectionError("iShares weg")
        world.yahoo.error = ConnectionError("Yahoo weg")
        old = _comp(WORLD, "yahoo", complete=False, as_of=date(2026, 8, 1))
        world.compositions.stored.append(old)
        assert world.refresh().securities[1].etf == old

    def test_without_any_data_no_composition(self, world):
        world.ishares.answers.clear()
        world.yahoo.answers.clear()
        result = world.refresh()
        assert result.securities[1].etf is None
        assert result.missing == []  # Stammdaten hat der ETF trotzdem

    def test_a_failing_store_keeps_the_fresh_data(self, world):
        world.compositions.error = ConnectionError("db weg")
        etf = world.refresh().securities[1].etf
        assert etf is not None
        assert etf.source == "ishares"

    def test_shares_and_bonds_ask_no_fund_source(self, world):
        world.refresh([ITEMS[0], ITEMS[2]])
        assert world.ishares.calls == world.yahoo.calls == []


class TestBudget:
    """Haengen FIRDS oder iShares, darf die Aktualisierung den Wochenlauf nicht ueber die Grenze
    des Watchdogs ziehen: Nach dem Zeitbudget gelten nur noch die gespeicherten Daten."""

    def test_after_the_budget_only_stored_data(self, world):
        world.catalog.stored[BUND] = BUND_MASTER
        world.compositions.stored.append(_comp(WORLD, "ishares", complete=True))

        class SlowFirds(FakeFirds):
            def master(self, isin):
                world.timer.now += 6 * 60  # sechs Minuten je Anfrage
                return super().master(isin)

        world.firds = SlowFirds(dict(world.firds.masters))
        result = world.refresh(budget=timedelta(minutes=10))
        assert [s.master.isin for s in result.securities] == [SAP, WORLD, BUND]
        assert world.ishares.calls == []  # WORLD kam nach dem Budget: gespeicherte Daten
        assert result.securities[1].etf == _comp(WORLD, "ishares", complete=True)
        assert world.catalog.saved == [SAP_MASTER, WORLD_MASTER]  # BUND nicht mehr gefragt

    def test_after_the_budget_without_stored_data_missing(self, world):
        result = world.refresh(budget=timedelta(0))
        assert result.securities == []
        assert result.missing == [SAP, WORLD, BUND]
