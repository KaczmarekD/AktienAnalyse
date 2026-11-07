"""Tageskurse im Schema market_data (D2.3, WP-06, WP-11).

- ``price_run``: ein Abruf der Tageskurse, nur angefuegt (mit Ende und Ergebnis in einem Schritt).
- ``daily_close``: Schlusskurs je ISIN, Quelle und Tag, nur einmal (ein zweiter Abruf am selben Tag
  oder nach einem Feiertag aendert nichts), nach ISIN, auch ohne Yahoo-Symbol.
- ``fx_daily``: Waehrungskurs nach EUR je Waehrung, Tag und Quelle, nur einmal.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError

from va_market_data.adapters.postgres.prices import PostgresPriceStore
from va_market_data.domain.prices import DailyClose, FxDaily

NOW = datetime(2026, 11, 6, 21, 35, tzinfo=UTC)
FRIDAY = date(2026, 11, 6)
APPLE = DailyClose("US0378331005", "APC.DE", FRIDAY, 231.5, "EUR", "EUR")
WORLD = DailyClose("IE00B4L5Y983", "IWDA.L", FRIDAY, 98.5, "USD", "USD")
SHELL = DailyClose("GB00BP6MXD84", "SHEL.L", FRIDAY, 26.5, "GBP", "GBp")
USD = FxDaily("USD", FRIDAY, 0.92)


def _count(engine: Engine, table: str) -> int:
    with engine.connect() as conn:
        return int(conn.execute(text(f"SELECT count(*) FROM market_data.{table}")).scalar_one())


@pytest.fixture
def store(engine: Engine) -> PostgresPriceStore:
    return PostgresPriceStore(engine)


def _write(store: PostgresPriceStore, closes, fx, status: str = "ok") -> int:
    return store.write_prices(
        source="yahoo",
        started_at=NOW,
        finished_at=NOW + timedelta(seconds=20),
        status=status,
        closes=closes,
        fx=fx,
    )


def test_a_run_with_closes_and_fx(store, engine):
    run_id = _write(store, [APPLE, WORLD], [USD])
    assert run_id > 0
    assert (_count(engine, "price_run"), _count(engine, "daily_close")) == (1, 2)
    assert _count(engine, "fx_daily") == 1
    assert store.latest_closes(["US0378331005", "IE00B4L5Y983"]) == {
        "US0378331005": APPLE,
        "IE00B4L5Y983": WORLD,
    }


def test_the_same_day_is_stored_once(store, engine):
    _write(store, [APPLE], [USD])
    _write(store, [APPLE], [USD])  # Feiertag oder zweiter Abruf: Yahoo liefert denselben Tag
    assert (_count(engine, "price_run"), _count(engine, "daily_close")) == (2, 1)
    assert _count(engine, "fx_daily") == 1


def test_a_failed_run_is_recorded(store, engine):
    _write(store, [], [], status="failed")
    with engine.connect() as conn:
        status = conn.execute(text("SELECT status FROM market_data.price_run")).scalar_one()
    assert status == "failed"


def test_known_currencies_come_from_earlier_closes(store):
    _write(store, [APPLE, WORLD], [])
    assert store.known_currencies(["APC.DE", "IWDA.L", "SHEL.L"]) == {
        "APC.DE": "EUR",
        "IWDA.L": "USD",
    }


def test_the_quote_unit_is_known_not_the_major_currency(store):
    """Gespeichert ist 26,50 GBP; fuer den naechsten Tag zaehlt die Notierung GBp (Pence)."""
    _write(store, [SHELL], [])
    assert store.known_currencies(["SHEL.L"]) == {"SHEL.L": "GBp"}


def test_a_bond_price_without_symbol(store):
    """Spaeter aus der Bundesbank (D2.4) oder von Hand: nach ISIN, ohne Yahoo-Symbol."""
    bund = DailyClose("DE0001102580", None, FRIDAY, 84.31, "EUR")
    _write(store, [bund], [])
    assert store.latest_closes(["DE0001102580"])["DE0001102580"] == bund


@pytest.mark.parametrize("table", ["price_run", "daily_close", "fx_daily"])
def test_nothing_is_changed_or_deleted(store, engine, table):
    _write(store, [APPLE], [USD])
    with pytest.raises(DBAPIError), engine.begin() as conn:
        conn.execute(text(f"DELETE FROM market_data.{table}"))
    with pytest.raises(DBAPIError), engine.begin() as conn:
        conn.execute(text(f"UPDATE market_data.{table} SET source = 'x'"))
