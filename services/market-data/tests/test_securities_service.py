"""Suche und Aufloesung von Wertpapieren (D2.1, WP-02, WP-03, WP-04, WP-07).

- Suche: eigene Wertpapiere zuerst, dann OpenFIGI (ISIN, WKN), dann die Suche von Yahoo (Text).
  Faellt eine Quelle aus, kommen die Treffer der anderen. Treffer bleiben 24 h im Speicher,
  Fehler nicht. Die Suche schreibt nichts.
- Aufloesung: Stammdaten aus ESMA FIRDS, Listings aus OpenFIGI; gespeichert werden Wertpapier,
  Stammdaten und Listings. Ohne beides ist die ISIN unbekannt.

Die Quellen sind Fakes hinter den Ports; die Abrufe selbst laufen nicht in den Tests.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

import pytest

from va_market_data.application.securities import LookupResult, SecurityService
from va_market_data.domain.securities import (
    BondTerms,
    Listing,
    SecurityHit,
    SecurityMaster,
)

APPLE = "US0378331005"
SAP = "DE0007164600"
BOND = "DE000A383J95"


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now


@dataclass
class FakeCatalog:
    """Die eigenen Wertpapiere (Schema market_data)."""

    hits: dict[str, SecurityHit] = field(default_factory=dict)
    saved: list[tuple[SecurityMaster, tuple[Listing, ...]]] = field(default_factory=list)

    def find(self, text: str, limit: int) -> list[SecurityHit]:
        found = [h for h in self.hits.values() if text.lower() in h.name.lower()]
        return found[:limit]

    def get(self, isin: str) -> SecurityHit | None:
        return self.hits.get(isin)

    def save(self, master: SecurityMaster, listings: tuple[Listing, ...], *, at: datetime) -> None:
        self.saved.append((master, listings))


@dataclass
class FakeLookup:
    """OpenFIGI: ISIN -> Name, Anlageklasse, Listings."""

    answers: dict[str, LookupResult] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)
    error: Exception | None = None

    def lookup(self, isin: str) -> LookupResult | None:
        self.calls.append(isin)
        if self.error:
            raise self.error
        return self.answers.get(isin)


@dataclass
class FakeText:
    """Suche von Yahoo: Name oder Symbol -> Treffer ohne ISIN."""

    hits: list[SecurityHit] = field(default_factory=list)
    calls: list[str] = field(default_factory=list)
    error: Exception | None = None

    def search(self, text: str, limit: int) -> list[SecurityHit]:
        self.calls.append(text)
        if self.error:
            raise self.error
        return self.hits[:limit]


@dataclass
class FakeMaster:
    """ESMA FIRDS: Stammdaten je ISIN."""

    masters: dict[str, SecurityMaster] = field(default_factory=dict)
    error: Exception | None = None

    def master(self, isin: str) -> SecurityMaster | None:
        if self.error:
            raise self.error
        return self.masters.get(isin)


def _apple_lookup() -> LookupResult:
    return LookupResult(
        name="APPLE INC",
        asset_class="equity",
        listings=(
            Listing(symbol="APC.DE", ticker="APC", exchange="GY", currency=None),
            Listing(symbol="AAPL", ticker="AAPL", exchange="US", currency=None),
        ),
    )


def _yahoo_hit(symbol: str, name: str = "iShares Core MSCI World") -> SecurityHit:
    return SecurityHit(
        isin=None,
        name=name,
        asset_class="etf",
        listings=(Listing(symbol=symbol, ticker=symbol, exchange="GER", currency=None),),
        source="yahoo",
    )


@dataclass
class World:
    catalog: FakeCatalog = field(default_factory=FakeCatalog)
    lookup: FakeLookup = field(default_factory=FakeLookup)
    text: FakeText = field(default_factory=FakeText)
    master: FakeMaster = field(default_factory=FakeMaster)
    clock: Clock = field(default_factory=Clock)

    def service(self) -> SecurityService:
        return SecurityService(
            catalog=self.catalog,
            lookup=self.lookup,
            text=self.text,
            master=self.master,
            clock=self.clock,
        )


@pytest.fixture
def world() -> World:
    return World()


class TestSearch:
    def test_an_isin_from_openfigi(self, world):
        world.lookup.answers[APPLE] = _apple_lookup()
        [hit] = world.service().search(APPLE)
        assert (hit.isin, hit.name, hit.asset_class, hit.source) == (
            APPLE,
            "APPLE INC",
            "equity",
            "openfigi",
        )
        assert [listing.symbol for listing in hit.listings] == ["APC.DE", "AAPL"]
        assert world.catalog.saved == []  # die Suche schreibt nichts

    def test_an_own_security_needs_no_request(self, world):
        world.catalog.hits[SAP] = SecurityHit(
            isin=SAP, name="SAP SE", asset_class="equity", listings=(), source="catalog"
        )
        [hit] = world.service().search(SAP)
        assert hit.source == "catalog"
        assert world.lookup.calls == []

    def test_a_wkn_becomes_the_german_isin(self, world):
        world.lookup.answers[SAP] = LookupResult("SAP SE", "equity", ())
        [hit] = world.service().search("716460")
        assert hit.isin == SAP
        assert world.lookup.calls == [SAP]

    def test_text_own_first_then_yahoo_without_duplicates(self, world):
        world.catalog.hits["IE00B4L5Y983"] = SecurityHit(
            isin="IE00B4L5Y983",
            name="iShares Core MSCI World UCITS ETF",
            asset_class="etf",
            listings=(Listing(symbol="EUNL.DE", ticker="EUNL", exchange="GY", currency="EUR"),),
            source="catalog",
        )
        world.text.hits = [_yahoo_hit("EUNL.DE"), _yahoo_hit("IWDA.AS")]
        hits = world.service().search("MSCI World")
        assert [(h.source, h.listings[0].symbol) for h in hits] == [
            ("catalog", "EUNL.DE"),
            ("yahoo", "IWDA.AS"),
        ]

    def test_a_failing_source_leaves_the_others(self, world):
        world.catalog.hits[SAP] = SecurityHit(
            isin=SAP, name="SAP SE", asset_class="equity", listings=(), source="catalog"
        )
        world.text.error = ConnectionError("Yahoo weg")
        assert [h.isin for h in world.service().search("SAP")] == [SAP]

    def test_openfigi_down_gives_no_hit_but_no_error(self, world):
        world.lookup.error = ConnectionError("OpenFIGI weg")
        assert world.service().search(APPLE) == []

    def test_unknown_isin(self, world):
        assert world.service().search(APPLE) == []

    def test_a_symbol_that_looks_like_a_wkn_falls_back_to_text(self, world):
        world.text.hits = [_yahoo_hit("BAS1DE", name="Beispiel")]
        hits = world.service().search("BAS1DE")
        assert [h.source for h in hits] == ["yahoo"]

    def test_database_down_leaves_the_external_hits(self, world):
        def broken(*args, **kwargs):
            raise ConnectionError("Postgres weg")

        world.catalog.get = broken  # type: ignore[method-assign]
        world.lookup.answers[APPLE] = _apple_lookup()
        assert [h.source for h in world.service().search(APPLE)] == ["openfigi"]

    def test_too_short(self, world):
        assert world.service().search("sa") == []
        assert world.text.calls == []

    def test_results_stay_a_day_in_memory(self, world):
        world.lookup.answers[APPLE] = _apple_lookup()
        service = world.service()
        service.search(APPLE)
        service.search(APPLE.lower())
        assert world.lookup.calls == [APPLE]
        world.clock.now += timedelta(hours=24, minutes=1)
        service.search(APPLE)
        assert world.lookup.calls == [APPLE, APPLE]

    def test_no_yahoo_hits_are_not_kept(self, world):
        """yfinance meldet manche Fehler als leere Liste; die naechste Anfrage fragt neu."""
        service = world.service()
        assert service.search("MSCI World") == []
        world.text.hits = [_yahoo_hit("EUNL.DE")]
        assert len(service.search("MSCI World")) == 1

    def test_failures_are_not_kept(self, world):
        world.text.error = ConnectionError("Yahoo weg")
        service = world.service()
        assert service.search("MSCI World") == []
        world.text.error = None
        world.text.hits = [_yahoo_hit("EUNL.DE")]
        assert len(service.search("MSCI World")) == 1


class TestResolve:
    def _bond(self) -> SecurityMaster:
        return SecurityMaster(
            isin=BOND,
            name="DB  4.000  7/12/28 c27 (URegS) DEUTSCHE BANK",
            asset_class="bond",
            currency="EUR",
            lei="7LTWFZYICNSX8D621K86",
            cfi="DTVUGB",
            bond=BondTerms(
                coupon=4.0,
                maturity=date(2028, 7, 12),
                denomination=100000.0,
                seniority="SNDB",
                floating=True,
            ),
        )

    def test_master_data_and_listings_are_saved(self, world):
        world.master.masters[APPLE] = SecurityMaster(
            isin=APPLE,
            name="APPLE INC",
            asset_class="equity",
            currency="USD",
            lei="HWUPKR0MPOU8FGXBT394",
            cfi="ESVUFR",
        )
        world.lookup.answers[APPLE] = _apple_lookup()
        resolved = world.service().resolve(APPLE)
        assert resolved is not None
        assert (resolved.master.name, resolved.master.asset_class) == ("APPLE INC", "equity")
        assert resolved.listing is not None
        assert resolved.listing.symbol == "APC.DE"  # Xetra zuerst
        [(master, listings)] = world.catalog.saved
        assert master.lei == "HWUPKR0MPOU8FGXBT394"
        assert [listing.symbol for listing in listings] == ["APC.DE", "AAPL"]

    def test_a_chosen_listing(self, world):
        world.lookup.answers[APPLE] = _apple_lookup()
        resolved = world.service().resolve(APPLE, symbol="AAPL")
        assert resolved is not None
        assert resolved.listing is not None
        assert resolved.listing.symbol == "AAPL"

    def test_a_bond_without_listing(self, world):
        """WP-08: Anleihen haben oft kein Listing bei Yahoo; die Stammdaten reichen."""
        world.master.masters[BOND] = self._bond()
        resolved = world.service().resolve(BOND)
        assert resolved is not None
        assert resolved.listing is None
        assert resolved.master.bond is not None
        assert resolved.master.bond.floating

    def test_without_firds_openfigi_names_the_class(self, world):
        world.lookup.answers[APPLE] = _apple_lookup()
        world.master.error = ConnectionError("ESMA weg")
        resolved = world.service().resolve(APPLE)
        assert resolved is not None
        assert (resolved.master.name, resolved.master.asset_class) == ("APPLE INC", "equity")
        assert resolved.master.cfi is None

    def test_a_resolved_security_stays_a_day_in_memory(self, world):
        world.lookup.answers[APPLE] = _apple_lookup()
        service = world.service()
        service.resolve(APPLE)
        service.resolve(APPLE)
        assert world.lookup.calls == [APPLE]
        world.clock.now += timedelta(hours=24, minutes=1)
        service.resolve(APPLE)
        assert world.lookup.calls == [APPLE, APPLE]

    def test_unknown(self, world):
        assert world.service().resolve(APPLE) is None
        assert world.catalog.saved == []

    def test_invalid_isin(self, world):
        with pytest.raises(ValueError, match="ISIN"):
            world.service().resolve("DE0007164601")
