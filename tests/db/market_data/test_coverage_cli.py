"""Kommando fuer die Abdeckung (D2.2): ``python -m va_market_data.coverage``.

Bis portfolio die Abdeckung meldet (D3), pflegt sie dieses Kommando im Container von market-data:
``set`` ersetzt die Menge (jede ISIN wird aufgeloest, ``ISIN=SYMBOL`` waehlt das Kurs-Listing),
``show`` zeigt sie. Eine unbekannte oder ungueltige ISIN aendert nichts.
"""

from __future__ import annotations

import io

import pytest

from va_market_data.adapters.postgres.store import PostgresSnapshotStore
from va_market_data.application.securities import ResolvedSecurity
from va_market_data.domain.securities import Listing, SecurityMaster

APPLE = "US0378331005"
ETF = "IE00B4L5Y983"

KNOWN = {
    APPLE: ResolvedSecurity(
        master=SecurityMaster(isin=APPLE, name="APPLE INC", asset_class="equity"),
        listings=(
            Listing(symbol="APC.DE", ticker="APC", exchange="GY"),
            Listing(symbol="AAPL", ticker="AAPL", exchange="US"),
        ),
        listing=Listing(symbol="APC.DE", ticker="APC", exchange="GY"),
    ),
    ETF: ResolvedSecurity(
        master=SecurityMaster(isin=ETF, name="ISHARES CORE MSCI WORLD", asset_class="etf"),
        listings=(Listing(symbol="EUNL.DE", ticker="EUNL", exchange="GY"),),
        listing=Listing(symbol="EUNL.DE", ticker="EUNL", exchange="GY"),
    ),
}


def fake_resolve(isin: str, symbol: str | None = None) -> ResolvedSecurity | None:
    if not isin.startswith(("US", "IE", "DE")):
        msg = f"Keine gueltige ISIN: {isin!r}"
        raise ValueError(msg)
    return KNOWN.get(isin)


def _main(monkeypatch, db_url: str, *argv: str) -> tuple[int, str]:
    from va_market_data import coverage

    monkeypatch.setenv("DATABASE_URL", db_url)
    out = io.StringIO()
    monkeypatch.setattr("sys.stdout", out)
    return coverage.main(list(argv), resolve=fake_resolve), out.getvalue()


@pytest.fixture
def store(engine) -> PostgresSnapshotStore:
    return PostgresSnapshotStore(engine, provider="yfinance", provider_version="test")


def test_set_and_show(monkeypatch, db_url, store):
    code, out = _main(monkeypatch, db_url, "set", APPLE, f"{ETF}=EUNL.DE")
    assert code == 0
    items = {item.isin: item for item in store.coverage()}
    assert (items[APPLE].fundamentals_symbol, items[APPLE].price_symbol) == ("AAPL", "APC.DE")
    assert (items[ETF].asset_class, items[ETF].fundamentals_symbol) == ("etf", None)
    code, out = _main(monkeypatch, db_url, "show")
    assert code == 0
    assert APPLE in out
    assert "AAPL" in out


def test_an_unknown_isin_changes_nothing(monkeypatch, db_url, store):
    _main(monkeypatch, db_url, "set", APPLE)
    code, _ = _main(monkeypatch, db_url, "set", APPLE, "DE0007164600")
    assert code == 1
    assert [item.isin for item in store.coverage()] == [APPLE]


def test_an_invalid_isin_changes_nothing(monkeypatch, db_url, store):
    code, _ = _main(monkeypatch, db_url, "set", "XX123")
    assert code == 1
    assert store.coverage() == []


def test_needs_the_database(monkeypatch):
    from va_market_data import coverage

    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert coverage.main(["show"], resolve=fake_resolve) == 2


def test_set_without_isin_removes_nothing(monkeypatch, db_url, store):
    _main(monkeypatch, db_url, "set", APPLE)
    with pytest.raises(SystemExit) as exit_info:
        _main(monkeypatch, db_url, "set")
    assert exit_info.value.code == 2
    assert [item.isin for item in store.coverage()] == [APPLE]


def test_clear(monkeypatch, db_url, store):
    _main(monkeypatch, db_url, "set", APPLE)
    code, out = _main(monkeypatch, db_url, "clear")
    assert code == 0
    assert "leer" in out
    assert store.coverage() == []
