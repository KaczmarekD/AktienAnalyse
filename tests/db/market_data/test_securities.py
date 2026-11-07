"""Wertpapiere im Schema market_data (D2.1, WP-01, WP-04).

- ``security``: ein Eintrag je ISIN mit Anlageklasse.
- ``security_master``: Stammdaten je Quelle, eine neue Zeile nur bei geaendertem Inhalt (nie
  ueberschrieben).
- ``listing``: Listings je ISIN, Symbol eindeutig.

Mit der Rolle des Dienstes (``va_market_data``): Sie darf anfuegen, aber nicht loeschen.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError

from va_market_data.adapters.postgres.securities import PostgresSecurityCatalog
from va_market_data.domain.securities import BondTerms, Listing, SecurityMaster

T0 = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)
APPLE = "US0378331005"
BOND = "DE000A383J95"

APPLE_MASTER = SecurityMaster(
    isin=APPLE,
    name="APPLE INC",
    asset_class="equity",
    currency="USD",
    lei="HWUPKR0MPOU8FGXBT394",
    cfi="ESVUFR",
)
APPLE_LISTINGS = (
    Listing(symbol="APC.DE", ticker="APC", exchange="GY", currency="EUR"),
    Listing(symbol="AAPL", ticker="AAPL", exchange="US", currency="USD"),
)


def _count(engine: Engine, table: str) -> int:
    with engine.connect() as conn:
        return int(conn.execute(text(f"SELECT count(*) FROM market_data.{table}")).scalar_one())


@pytest.fixture
def catalog(engine: Engine) -> PostgresSecurityCatalog:
    return PostgresSecurityCatalog(engine)


class TestSave:
    def test_security_master_and_listings(self, catalog, engine):
        catalog.save(APPLE_MASTER, APPLE_LISTINGS, at=T0)
        hit = catalog.get(APPLE)
        assert hit is not None
        assert (hit.isin, hit.name, hit.asset_class, hit.source) == (
            APPLE,
            "APPLE INC",
            "equity",
            "catalog",
        )
        assert [listing.symbol for listing in hit.listings] == ["APC.DE", "AAPL"]
        assert _count(engine, "security") == 1

    def test_unchanged_master_data_adds_no_row(self, catalog, engine):
        catalog.save(APPLE_MASTER, APPLE_LISTINGS, at=T0)
        catalog.save(APPLE_MASTER, APPLE_LISTINGS, at=T0 + timedelta(days=1))
        assert _count(engine, "security_master") == 1
        assert _count(engine, "listing") == 2

    def test_changed_master_data_is_a_new_version(self, catalog, engine):
        catalog.save(APPLE_MASTER, APPLE_LISTINGS, at=T0)
        renamed = replace(APPLE_MASTER, name="APPLE INC.")
        catalog.save(renamed, (), at=T0 + timedelta(days=1))
        assert _count(engine, "security_master") == 2
        hit = catalog.get(APPLE)
        assert hit is not None
        assert hit.name == "APPLE INC."  # gueltig ist die juengste
        assert len(hit.listings) == 2  # Listings bleiben

    def test_the_newest_master_data_name_the_class(self, catalog):
        """Erst nur OpenFIGI (``other``), dann FIRDS (``bond``): Es gilt die juengste."""
        first = SecurityMaster(isin=BOND, name="DB", asset_class="other", source="openfigi")
        catalog.save(first, (), at=T0)
        catalog.save(replace(first, asset_class="bond", source="firds"), (), at=T0)
        hit = catalog.get(BOND)
        assert hit is not None
        assert hit.asset_class == "bond"

    def test_bond_terms_round_trip(self, catalog):
        bond = SecurityMaster(
            isin=BOND,
            name="DB 4.000 7/12/28",
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
        catalog.save(bond, (), at=T0)
        master = catalog.master(BOND)
        assert master == bond

    def test_a_listing_symbol_belongs_to_one_isin(self, catalog):
        catalog.save(APPLE_MASTER, APPLE_LISTINGS, at=T0)
        other = SecurityMaster(isin="DE0007164600", name="SAP SE", asset_class="equity")
        catalog.save(other, (Listing(symbol="AAPL", ticker="AAPL", exchange="US"),), at=T0)
        hit = catalog.get("DE0007164600")
        assert hit is not None
        assert hit.listings == ()  # das Symbol gehoert schon Apple


class TestFind:
    def test_by_name_symbol_or_isin(self, catalog):
        catalog.save(APPLE_MASTER, APPLE_LISTINGS, at=T0)
        assert [h.isin for h in catalog.find("apple", limit=10)] == [APPLE]
        assert [h.isin for h in catalog.find("APC", limit=10)] == [APPLE]
        assert [h.isin for h in catalog.find("US03783", limit=10)] == [APPLE]
        assert catalog.find("microsoft", limit=10) == []

    def test_wildcards_are_plain_text(self, catalog):
        catalog.save(APPLE_MASTER, APPLE_LISTINGS, at=T0)
        assert catalog.find("%", limit=10) == []
        assert catalog.find("_", limit=10) == []

    def test_unknown(self, catalog):
        assert catalog.get(APPLE) is None
        assert catalog.master(APPLE) is None


class TestProtection:
    @pytest.mark.parametrize("table", ["security", "security_master", "listing"])
    def test_nothing_is_deleted(self, catalog, engine, table):
        catalog.save(APPLE_MASTER, APPLE_LISTINGS, at=T0)
        with pytest.raises(DBAPIError), engine.begin() as conn:
            conn.execute(text(f"DELETE FROM market_data.{table}"))
