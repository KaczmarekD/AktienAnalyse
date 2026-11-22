"""Die Abdeckung von portfolio (D3.3, WP-09; docs/architecture/depot/wertpapiere.md).

``portfolio.coverage.changed`` nennt die ganze Menge der ISINs. market-data
- behaelt bekannte Eintraege (auch ein Symbol, das das Kommando gewaehlt hat),
- loest neue auf: eigene Wertpapiere mit Listings zuerst, sonst FIRDS und OpenFIGI,
- loest einen Eintrag ohne Kurs-Symbol bei jeder Meldung neu auf,
- laesst eine nicht aufloesbare ISIN vorerst weg (die naechste Meldung versucht es wieder),
- uebergeht eine Meldung, die aelter ist als die juengste Fassung,
- frischt die Stammdaten der neuen Wertpapiere sofort auf (``marketdata.securities.updated``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest

from va_contracts import Envelope, new_envelope
from va_contracts.events.v1 import COVERAGE_CHANGED, SECURITIES_UPDATED, CoverageChangedV1
from va_market_data.application.coverage import (
    PORTFOLIO_SOURCE,
    CoverageUpdate,
    follow_portfolio,
)
from va_market_data.application.securities import RefreshResult, ResolvedSecurity
from va_market_data.domain.coverage import CoverageItem
from va_market_data.domain.securities import Listing, SecurityHit, SecurityMaster
from va_market_data.entrypoints.handlers import CoverageChangedHandler
from va_platform.bus import InProcessBus

T0 = datetime(2026, 11, 22, 10, 0, tzinfo=UTC)
APPLE = "US0378331005"
SAP = "DE0007164600"
WORLD = "IE00B4L5Y983"
BUND = "DE0001102580"
UNKNOWN = "XS0000000009"

APPLE_LISTINGS = (Listing("AAPL", "AAPL", "US", "USD"), Listing("APC.DE", "APC", "GY", "EUR"))
WORLD_LISTINGS = (Listing("EUNL.DE", "EUNL", "GY", "EUR"),)


@dataclass
class FakeCoverage:
    items: list[CoverageItem] = field(default_factory=list)
    as_of: datetime | None = None
    writes: list[tuple[list[CoverageItem], str, datetime]] = field(default_factory=list)

    def coverage(self) -> list[CoverageItem]:
        return list(self.items)

    def coverage_as_of(self) -> datetime | None:
        return self.as_of

    def write_coverage(self, items, *, source: str, at: datetime) -> bool:
        wanted = sorted(items, key=lambda item: item.isin)
        if wanted == self.items and self.as_of is not None:
            return False
        self.items, self.as_of = wanted, at
        self.writes.append((wanted, source, at))
        return True


@dataclass
class Sources:
    """Eigene Wertpapiere und die Aufloesung ueber FIRDS/OpenFIGI."""

    catalog: dict[str, SecurityHit] = field(default_factory=dict)
    resolvable: dict[str, ResolvedSecurity] = field(default_factory=dict)
    asked: list[str] = field(default_factory=list)
    broken: bool = False

    def known(self, isin: str) -> SecurityHit | None:
        return self.catalog.get(isin)

    def resolve(self, isin: str) -> ResolvedSecurity | None:
        self.asked.append(isin)
        if self.broken:
            msg = "OpenFIGI weg"
            raise RuntimeError(msg)
        if isin == "DE0007164601":
            msg = "Keine gueltige ISIN"
            raise ValueError(msg)
        return self.resolvable.get(isin)


def _resolved(isin: str, name: str, asset_class, listings=()) -> ResolvedSecurity:
    return ResolvedSecurity(SecurityMaster(isin, name, asset_class), tuple(listings), None)


@pytest.fixture
def sources() -> Sources:
    return Sources(
        catalog={APPLE: SecurityHit(APPLE, "Apple Inc.", "equity", APPLE_LISTINGS, "catalog")},
        resolvable={
            WORLD: _resolved(WORLD, "iShares Core MSCI World", "etf", WORLD_LISTINGS),
            BUND: _resolved(BUND, "Bund 2033", "bond"),
        },
    )


def _follow(store: FakeCoverage, sources: Sources, *isins: str, at: datetime = T0):
    return follow_portfolio(
        list(isins), as_of=at, store=store, known=sources.known, resolve=sources.resolve
    )


class TestFollow:
    def test_new_isins_from_the_catalog_and_the_sources(self, sources):
        store = FakeCoverage()
        update = _follow(store, sources, WORLD, APPLE)
        assert update.changed
        assert sources.asked == [WORLD]  # Apple kannte der Katalog mit Listings
        world, apple = store.items  # nach ISIN
        assert (apple.isin, apple.fundamentals_symbol, apple.price_symbol) == (
            APPLE,
            "AAPL",
            "APC.DE",
        )
        assert (world.asset_class, world.fundamentals_symbol, world.price_symbol) == (
            "etf",
            None,
            "EUNL.DE",
        )
        assert [item.isin for item in update.added] == [WORLD, APPLE]
        [(_, source, at)] = store.writes
        assert (source, at) == (PORTFOLIO_SOURCE, T0)  # mit dem Zeitpunkt der Meldung

    def test_known_items_stay_as_they_are(self, sources):
        chosen = CoverageItem(APPLE, "equity", "AAPL", "AAPL", "Apple")  # Kommando: ISIN=AAPL
        store = FakeCoverage([chosen], T0 - timedelta(days=1))
        update = _follow(store, sources, APPLE, WORLD)
        assert {item.isin: item for item in store.items}[APPLE] == chosen
        assert [item.isin for item in update.added] == [WORLD]

    def test_the_same_set_writes_nothing(self, sources):
        store = FakeCoverage()
        _follow(store, sources, APPLE)
        update = _follow(store, sources, APPLE, at=T0 + timedelta(days=1))
        assert update == CoverageUpdate(changed=False)
        assert len(store.writes) == 1

    def test_removed_isins_leave_the_coverage(self, sources):
        store = FakeCoverage()
        _follow(store, sources, APPLE, WORLD)
        update = _follow(store, sources, WORLD, at=T0 + timedelta(hours=1))
        assert update.changed
        assert update.added == []
        assert [item.isin for item in store.items] == [WORLD]

    def test_an_empty_set_empties_the_coverage(self, sources):
        store = FakeCoverage()
        _follow(store, sources, APPLE)
        assert _follow(store, sources, at=T0 + timedelta(hours=1)).changed
        assert store.items == []

    def test_an_unresolvable_isin_is_left_out_for_now(self, sources):
        store = FakeCoverage()
        update = _follow(store, sources, APPLE, UNKNOWN, "DE0007164601")
        assert [item.isin for item in store.items] == [APPLE]
        assert update.unresolved == ["DE0007164601", UNKNOWN]
        # Die naechste Meldung (taeglich) versucht es wieder
        sources.resolvable[UNKNOWN] = _resolved(UNKNOWN, "Neu", "other")
        _follow(store, sources, APPLE, UNKNOWN, at=T0 + timedelta(days=1))
        assert [item.isin for item in store.items] == [APPLE, UNKNOWN]

    def test_failing_sources_cost_only_the_new_isin(self, sources):
        sources.broken = True
        store = FakeCoverage()
        update = _follow(store, sources, APPLE, WORLD)
        assert [item.isin for item in store.items] == [APPLE]
        assert update.unresolved == [WORLD]

    def test_a_known_security_without_listings_stays_without_symbol(self, sources):
        sources.catalog[BUND] = SecurityHit(BUND, "Bund 2033", "bond", (), "catalog")
        del sources.resolvable[BUND]
        store = FakeCoverage()
        _follow(store, sources, BUND)
        [bund] = store.items
        assert (bund.asset_class, bund.price_symbol, bund.name) == ("bond", None, "Bund 2033")

    def test_an_item_without_price_symbol_is_resolved_again(self, sources):
        store = FakeCoverage([CoverageItem(WORLD, "etf", None, None, "World")], T0)
        update = _follow(store, sources, WORLD, at=T0 + timedelta(days=1))
        assert sources.asked == [WORLD]
        assert store.items[0].price_symbol == "EUNL.DE"
        assert [item.isin for item in update.added] == [WORLD]

    def test_an_older_announcement_changes_nothing(self, sources):
        store = FakeCoverage()
        _follow(store, sources, APPLE, WORLD, at=T0)
        update = _follow(store, sources, APPLE, at=T0 - timedelta(minutes=1))
        assert update == CoverageUpdate(changed=False)
        assert [item.isin for item in store.items] == [WORLD, APPLE]
        assert sources.asked == [WORLD]  # nichts neu aufgeloest

    def test_after_the_budget_only_the_catalog(self, sources):
        ticks = iter([0.0, 400.0, 400.0, 400.0])  # Start, dann je neue ISIN
        store = FakeCoverage()
        update = follow_portfolio(
            [APPLE, WORLD, BUND],
            as_of=T0,
            store=store,
            known=sources.known,
            resolve=sources.resolve,
            budget=timedelta(minutes=5),
            timer=lambda: next(ticks),
        )
        assert sources.asked == []  # nach 400 s keine Quelle mehr
        assert [item.isin for item in store.items] == [APPLE]  # aus dem Katalog
        assert update.unresolved == [BUND, WORLD]

    def test_an_unreadable_coverage_raises_for_redelivery(self, sources):
        class Broken(FakeCoverage):
            def coverage(self):
                msg = "Datenbank weg"
                raise RuntimeError(msg)

        with pytest.raises(RuntimeError):
            _follow(Broken(), sources, APPLE)


def _announce(bus: InProcessBus, *isins: str) -> None:
    bus.publish(
        new_envelope(COVERAGE_CHANGED, CoverageChangedV1(isins=list(isins)), source="va/portfolio")
    )


class TestHandler:
    @pytest.fixture
    def bus(self) -> InProcessBus:
        return InProcessBus(max_deliver=1)

    def _updated(self, bus: InProcessBus) -> list[Envelope[Any]]:
        seen: list[Envelope[Any]] = []
        bus.subscribe(SECURITIES_UPDATED, "probe", seen.append)
        return seen

    def test_new_securities_get_their_master_data_at_once(self, bus, sources):
        store = FakeCoverage()
        refreshed: list[list[str]] = []

        def refresh(items) -> RefreshResult:
            refreshed.append([item.isin for item in items])
            return RefreshResult(
                securities=[sources.resolvable[WORLD]], missing=[i.isin for i in items][:0]
            )

        seen = self._updated(bus)
        CoverageChangedHandler(
            bus,
            follow=lambda isins, at: _follow(store, sources, *isins, at=at),
            refresh=refresh,
            today=lambda: date(2026, 11, 22),
        ).subscribe()
        _announce(bus, WORLD)
        assert refreshed == [[WORLD]]
        [event] = seen
        assert [s.isin for s in event.data.securities] == [WORLD]
        assert event.data.as_of == date(2026, 11, 22)

    def test_nothing_new_no_refresh(self, bus, sources):
        store = FakeCoverage()
        _follow(store, sources, APPLE)
        refreshed: list[Any] = []
        seen = self._updated(bus)
        CoverageChangedHandler(
            bus,
            follow=lambda isins, at: _follow(store, sources, *isins, at=at),
            refresh=lambda items: refreshed.append(items) or RefreshResult(),
        ).subscribe()
        _announce(bus, APPLE)
        assert (refreshed, seen) == ([], [])

    def test_a_failed_refresh_keeps_the_coverage(self, bus, sources):
        store = FakeCoverage()

        def refresh(items) -> RefreshResult:
            msg = "FIRDS weg"
            raise RuntimeError(msg)

        seen = self._updated(bus)
        CoverageChangedHandler(
            bus, follow=lambda isins, at: _follow(store, sources, *isins, at=at), refresh=refresh
        ).subscribe()
        _announce(bus, WORLD)
        assert [item.isin for item in store.items] == [WORLD]
        assert seen == []
