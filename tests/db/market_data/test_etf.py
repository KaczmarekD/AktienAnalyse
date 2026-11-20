"""ETF-Zusammensetzungen im Schema market_data (D2.4, WP-10).

- ``etf_composition``: je ISIN, Quelle und Stand eine Zeile, nur angefuegt. Fondsdaten,
  Gewichte und alle Positionen; die Positionen spaltenweise (ein Anleihe-ETF hat ueber 4.000).
- Gueltig ist der juengste Stand, bei gleichem Stand die zuletzt gespeicherte Quelle.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError

from va_market_data.adapters.postgres.etf import PostgresEtfStore
from va_market_data.adapters.postgres.securities import PostgresSecurityCatalog
from va_market_data.domain.etf import EtfComposition, FundFacts, Holding, composition_from_holdings
from va_market_data.domain.securities import SecurityMaster

T0 = datetime(2026, 11, 21, 8, 0, tzinfo=UTC)
WORLD = "IE00B4L5Y983"
FACTS = FundFacts(
    name="iShares Core MSCI World UCITS ETF",
    ter=0.2,
    fund_size=142076.32,
    currency="USD",
    distribution="accumulating",
    provider="iShares",
)
HOLDINGS = [
    Holding("APPLE", 6.0, "US0378331005", "AAPL", "Aktien", "IT", "Vereinigte Staaten", "USD"),
    Holding("SAP", 0.5, "DE0007164600", "SAP", "Aktien", "IT", "Deutschland", "EUR"),
    Holding("USD CASH", 0.2, None, None, "Cash", None, None, "USD"),
]


def _comp(as_of: date = date(2026, 11, 19), source: str = "ishares") -> EtfComposition:
    return composition_from_holdings(WORLD, source, as_of, FACTS, HOLDINGS)


def _count(engine: Engine) -> int:
    with engine.connect() as conn:
        return int(
            conn.execute(text("SELECT count(*) FROM market_data.etf_composition")).scalar_one()
        )


@pytest.fixture
def store(engine: Engine) -> PostgresEtfStore:
    PostgresSecurityCatalog(engine).save(
        SecurityMaster(WORLD, "ISHSIII-CORE MSCI WORLD", "etf", "USD"), (), at=T0
    )
    return PostgresEtfStore(engine)


def test_a_composition_round_trips(store):
    assert store.write_composition(_comp(), at=T0)
    assert store.latest_composition(WORLD) == _comp()


def test_the_same_state_is_stored_once(store, engine):
    assert store.write_composition(_comp(), at=T0)
    assert not store.write_composition(_comp(), at=T0 + timedelta(hours=1))
    assert _count(engine) == 1


def test_the_newest_state_is_valid(store):
    store.write_composition(_comp(date(2026, 11, 19)), at=T0)
    store.write_composition(_comp(date(2026, 11, 12)), at=T0)  # spaet nachgeholt
    latest = store.latest_composition(WORLD)
    assert latest is not None
    assert latest.as_of == date(2026, 11, 19)


def test_an_incomplete_list_without_countries(store):
    comp = EtfComposition(
        isin=WORLD,
        source="yahoo",
        as_of=date(2026, 11, 21),
        complete=False,
        facts=FundFacts(ter=0.2, provider="BlackRock Asset Management Ireland - ETF"),
        holdings=(Holding("Apple Inc", 5.6, ticker="AAPL"),),
        sectors={"technology": 30.6},
        asset_classes={"Aktien": 99.5, "Cash": 0.46},
    )
    store.write_composition(comp, at=T0)
    assert store.latest_composition(WORLD) == comp


def test_the_newest_complete_list(store):
    """Fuer die Regel „vollstaendig vor frisch“: die juengste vollstaendige Liste."""
    store.write_composition(_comp(date(2026, 11, 13)), at=T0)
    incomplete = EtfComposition(
        isin=WORLD,
        source="yahoo",
        as_of=date(2026, 11, 21),
        complete=False,
        facts=FundFacts(ter=0.2),
    )
    store.write_composition(incomplete, at=T0)
    assert store.latest_composition(WORLD) == incomplete
    complete = store.latest_composition(WORLD, complete_only=True)
    assert complete is not None
    assert (complete.source, complete.as_of) == ("ishares", date(2026, 11, 13))


def test_holdings_are_stored_by_column(store, engine):
    store.write_composition(_comp(), at=T0)
    with engine.connect() as conn:
        holdings = conn.execute(
            text("SELECT holdings FROM market_data.etf_composition")
        ).scalar_one()
    assert holdings["ticker"] == ["AAPL", "SAP", None]
    assert holdings["weight"] == [6.0, 0.5, 0.2]


def test_unknown(store):
    assert store.latest_composition("IE00BJ0KDQ92") is None


def test_read_only_role_can_read(store, read_engine):
    store.write_composition(_comp(), at=T0)
    assert PostgresEtfStore(read_engine).latest_composition(WORLD) == _comp()


def test_nothing_is_changed_or_deleted(store, engine):
    store.write_composition(_comp(), at=T0)
    with pytest.raises(DBAPIError), engine.begin() as conn:
        conn.execute(text("DELETE FROM market_data.etf_composition"))
    with pytest.raises(DBAPIError), engine.begin() as conn:
        conn.execute(text("UPDATE market_data.etf_composition SET complete = false"))
