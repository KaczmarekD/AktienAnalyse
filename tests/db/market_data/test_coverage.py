"""Abdeckung im Schema market_data (D2.2, WP-05, WP-09).

- ``coverage_version``/``coverage_item``: die Menge der abzudeckenden Wertpapiere, je Aenderung eine
  neue Version (nie ueberschrieben), gueltig ist die juengste. Ohne Nutzer und Mengen.
- ``fundamental_snapshot.role``: ``universe`` (Standard) oder ``coverage``. Alle bestehenden
  Lesewege sehen nur ``universe``, sonst stuenden Depot-Titel im Ranking.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import Engine, text

from va_market_data.adapters.postgres.store import PostgresSnapshotStore
from va_market_data.domain.coverage import CoverageItem
from va_market_data.domain.fundamentals import Fundamentals, Identity, MarketData
from va_market_data.domain.universe import Ticker

T0 = datetime(2026, 11, 7, 6, 0, tzinfo=UTC)
APPLE = CoverageItem("US0378331005", "equity", "AAPL", "APC.DE", "Apple Inc.")
ETF = CoverageItem("IE00B4L5Y983", "etf", None, "EUNL.DE", "iShares Core MSCI World")


def _fund(symbol: str, index: str = "DAX") -> Fundamentals:
    return Fundamentals(
        identity=Identity(symbol, f"{symbol} AG", index), market=MarketData(market_cap=5e9)
    )


@pytest.fixture
def store(engine: Engine) -> PostgresSnapshotStore:
    return PostgresSnapshotStore(engine, provider="yfinance", provider_version="test")


class TestVersions:
    def test_the_newest_version_counts(self, store):
        assert store.coverage() == []
        store.write_coverage([APPLE, ETF], source="test", at=T0)
        assert sorted(item.isin for item in store.coverage()) == [ETF.isin, APPLE.isin]
        store.write_coverage([ETF], source="test", at=T0)
        assert store.coverage() == [ETF]

    def test_an_unchanged_set_is_no_new_version(self, store, engine):
        assert store.write_coverage([APPLE, ETF], source="test", at=T0) is True
        assert store.write_coverage([ETF, APPLE], source="test", at=T0) is False
        with engine.connect() as conn:
            versions = conn.execute(text("SELECT count(*) FROM market_data.coverage_version"))
            assert versions.scalar_one() == 1

    def test_an_empty_set_is_a_version_too(self, store):
        store.write_coverage([APPLE], source="test", at=T0)
        assert store.write_coverage([], source="test", at=T0) is True
        assert store.coverage() == []


class TestSnapshots:
    def _run(self, store: PostgresSnapshotStore) -> int:
        tickers = [Ticker("SAP.DE", "SAP SE", "DAX", "DE0007164600")]
        fetch_run_id = store.start_fetch(tickers, "Replay")
        store.record_fundamentals(fetch_run_id, _fund("SAP.DE"))
        return fetch_run_id

    def test_covered_snapshots_stay_out_of_the_universe(self, store):
        fetch_run_id = self._run(store)
        store.record_covered(fetch_run_id, _fund("AAPL", "-"), "US0378331005")
        universe = store.load_snapshots(fetch_run_id, ["SAP.DE", "AAPL"])
        assert list(universe["symbol"]) == ["SAP.DE"]
        covered = store.covered_snapshots(fetch_run_id)
        assert list(covered["symbol"]) == ["AAPL"]
        assert "role" not in universe.columns

    def test_the_isin_of_a_covered_share_is_recorded(self, store, engine):
        fetch_run_id = self._run(store)
        store.record_covered(fetch_run_id, _fund("AAPL", "-"), "US0378331005")
        with engine.connect() as conn:
            isin = conn.execute(
                text("SELECT isin FROM market_data.instrument WHERE symbol = 'AAPL'")
            ).scalar_one()
        assert isin == "US0378331005"

    def test_the_role_is_checked(self, store, engine):
        fetch_run_id = self._run(store)
        with engine.connect() as conn:
            role = conn.execute(
                text("SELECT role FROM market_data.fundamental_snapshot WHERE fetch_run_id = :id"),
                {"id": fetch_run_id},
            ).scalar_one()
        assert role == "universe"
