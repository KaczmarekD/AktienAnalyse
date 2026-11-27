"""Neue Aktien sofort holen (D4.6, WP-13; docs/architecture/depot/analyse.md, Einordnung).

- Nach einer neuen Fassung der Abdeckung holt market-data die Kennzahlen neuer Aktien ausserhalb
  des Referenzuniversums gleich, speichert jede (``coverage_fetch``) und meldet die gespeicherten
  (``marketdata.coverage.fetched``).
- Hoechstens zehn je Meldung und zwei Minuten; der Rest kommt mit dem Wochenlauf.
- Ein Ausfall kostet nur die sofortige Einordnung, nie die Uebernahme der Abdeckung.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pandas as pd
import pytest

from va_contracts import Envelope, new_envelope
from va_contracts.events.v1 import COVERAGE_CHANGED, COVERAGE_FETCHED, CoverageChangedV1
from va_market_data.application.coverage import CoverageUpdate, Fetched, fetch_added
from va_market_data.domain.coverage import CoverageItem
from va_market_data.domain.fundamentals import Fundamentals, Identity, MarketData, Provenance
from va_market_data.entrypoints.handlers import CoverageChangedHandler
from va_platform.bus import InProcessBus

T0 = datetime(2026, 11, 27, 10, 0, tzinfo=UTC)
APPLE = "US0378331005"
MSFT = "US5949181045"
SAP = "DE0007164600"
WORLD = "IE00B4L5Y983"


def _item(isin: str, symbol: str | None, asset_class: str = "equity") -> CoverageItem:
    return CoverageItem(isin, asset_class, symbol, symbol, name=symbol)  # type: ignore[arg-type]


@dataclass
class FakeStore:
    symbols: set[str] = field(default_factory=lambda: {"SAP.DE"})
    isins: set[str] = field(default_factory=lambda: {SAP})
    saved: list[tuple[str, str]] = field(default_factory=list)
    broken: set[str] = field(default_factory=set)
    unreadable: bool = False

    def universe_keys(self) -> tuple[set[str], set[str]]:
        if self.unreadable:
            msg = "Datenbank weg"
            raise RuntimeError(msg)
        return self.symbols, self.isins

    def record_coverage_fetch(self, fund: Fundamentals, isin: str) -> None:
        if fund.symbol in self.broken:
            msg = "Speichern fehlgeschlagen"
            raise RuntimeError(msg)
        self.saved.append((fund.symbol, isin))


def _fund(symbol: str) -> Fundamentals:
    return Fundamentals(
        identity=Identity(symbol, symbol, "-", sector="Technology"),
        market=MarketData(market_cap=1e12),
        provenance=Provenance(fetched_at=T0),
    )


@dataclass
class FakeFetch:
    asked: list[list[str]] = field(default_factory=list)
    fail_after: int | None = None

    def __call__(
        self,
        tickers: list[Any],
        *,
        on_result: Callable[[Fundamentals], None],
        history: Mapping[str, Any],
    ) -> pd.DataFrame:
        assert history == {}
        self.asked.append([t.symbol for t in tickers])
        for i, ticker in enumerate(tickers):
            if self.fail_after is not None and i >= self.fail_after:
                msg = "Rate-Limit"
                raise RuntimeError(msg)
            on_result(_fund(ticker.symbol))
        return pd.DataFrame()


class TestFetchAdded:
    def test_new_stocks_outside_the_universe(self):
        store, fetch = FakeStore(), FakeFetch()
        items = [
            _item(APPLE, "AAPL"),
            _item(SAP, "SAP.DE"),  # im Universum
            _item(WORLD, "EUNL.DE", "etf"),  # keine Aktie
            _item(MSFT, None),  # ohne Symbol fuer Kennzahlen
        ]
        result = fetch_added(items, store=store, fetch=fetch)
        assert fetch.asked == [["AAPL"]]
        assert store.saved == [("AAPL", APPLE)]
        assert [f.symbol for f in result.fundamentals] == ["AAPL"]
        assert result.isins == {"AAPL": APPLE}

    def test_at_most_ten(self):
        store, fetch = FakeStore(), FakeFetch()
        items = [_item(f"US00000000{i:02d}", f"T{i}") for i in range(12)]
        fetch_added(items, store=store, fetch=fetch)
        assert len(fetch.asked[0]) == 10

    def test_the_budget_ends_the_loop(self):
        store, fetch = FakeStore(), FakeFetch()
        clock = iter([0.0, 10.0, 200.0, 300.0])
        items = [_item(APPLE, "AAPL"), _item(MSFT, "MSFT"), _item("US0231351067", "AMZN")]
        result = fetch_added(
            items, store=store, fetch=fetch, budget=timedelta(minutes=2), timer=lambda: next(clock)
        )
        assert [f.symbol for f in result.fundamentals] == ["AAPL", "MSFT"]

    def test_a_failed_save_costs_only_that_stock(self):
        store, fetch = FakeStore(broken={"AAPL"}), FakeFetch()
        result = fetch_added([_item(APPLE, "AAPL"), _item(MSFT, "MSFT")], store=store, fetch=fetch)
        assert result.isins == {"MSFT": MSFT}

    def test_an_interrupted_fetch_keeps_what_was_saved(self):
        store, fetch = FakeStore(), FakeFetch(fail_after=1)
        result = fetch_added([_item(APPLE, "AAPL"), _item(MSFT, "MSFT")], store=store, fetch=fetch)
        assert result.isins == {"AAPL": APPLE}

    def test_without_universe_nothing(self):
        store, fetch = FakeStore(unreadable=True), FakeFetch()
        assert fetch_added([_item(APPLE, "AAPL")], store=store, fetch=fetch) == Fetched()
        assert fetch.asked == []


class TestHandler:
    @pytest.fixture
    def bus(self) -> InProcessBus:
        return InProcessBus(max_deliver=1)

    def _probe(self, bus: InProcessBus) -> list[Envelope[Any]]:
        seen: list[Envelope[Any]] = []
        bus.subscribe(COVERAGE_FETCHED, "probe", seen.append)
        return seen

    def _announce(self, bus: InProcessBus) -> None:
        bus.publish(
            new_envelope(COVERAGE_CHANGED, CoverageChangedV1(isins=[APPLE]), source="va/portfolio")
        )

    def _handler(self, bus, *, added, fetched, refresh=None) -> None:
        CoverageChangedHandler(
            bus,
            follow=lambda isins, at: CoverageUpdate(changed=True, added=added),
            refresh=refresh,
            fetch_added=lambda items: fetched,
            today=lambda: date(2026, 11, 27),
        ).subscribe()

    def test_the_fetched_stocks_go_to_scoring(self, bus):
        seen = self._probe(bus)
        fetched = Fetched([_fund("AAPL")], {"AAPL": APPLE})
        self._handler(bus, added=[_item(APPLE, "AAPL")], fetched=fetched)
        self._announce(bus)
        [event] = seen
        assert event.data.as_of == date(2026, 11, 27)
        assert [f.symbol for f in event.data.fundamentals] == ["AAPL"]
        assert event.data.isins == {"AAPL": APPLE}
        assert event.data.fundamentals[0].identity.sector == "Technology"

    def test_a_failed_refresh_does_not_stop_the_fetch(self, bus):
        def refresh(items):
            msg = "FIRDS weg"
            raise RuntimeError(msg)

        seen = self._probe(bus)
        fetched = Fetched([_fund("AAPL")], {"AAPL": APPLE})
        self._handler(bus, added=[_item(APPLE, "AAPL")], fetched=fetched, refresh=refresh)
        self._announce(bus)
        assert len(seen) == 1

    def test_nothing_fetched_no_event(self, bus):
        seen = self._probe(bus)
        self._handler(bus, added=[_item(APPLE, "AAPL")], fetched=Fetched())
        self._announce(bus)
        assert seen == []

    def test_nothing_new_no_fetch(self, bus):
        seen = self._probe(bus)
        calls: list[Any] = []
        CoverageChangedHandler(
            bus,
            follow=lambda isins, at: CoverageUpdate(changed=False),
            fetch_added=lambda items: calls.append(items) or Fetched(),
        ).subscribe()
        self._announce(bus)
        assert (calls, seen) == ([], [])
