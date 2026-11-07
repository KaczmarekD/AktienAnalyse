"""Abdeckung im Wochenlauf (D2.2, WP-05, WP-07, WP-09; docs/architecture/depot/wertpapiere.md).

- Die Abdeckung ist die Menge der Wertpapiere ausserhalb des Referenzuniversums, fuer die
  market-data Daten holt. market-data kennt nur ISIN, Anlageklasse und Symbole, nie Nutzer.
- Der Wochenlauf ruft die Fundamentaldaten ihrer Aktien zusaetzlich ab und schickt sie in
  ``covered[]``, nicht in ``fundamentals[]``: Ranking, CSV und Mail bleiben gleich.
- Faellt die Abdeckung aus, laeuft der Wochenlauf trotzdem durch (Robustheit).
- Fundamentaldaten vom Heimat-Listing, Kurse von Xetra, falls vorhanden.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd
import pytest

from va_contracts import Envelope, new_envelope
from va_contracts.events.v1 import (
    RUN_REQUESTED,
    SNAPSHOT_COMPLETED,
    RunOptionsV1,
    ScreeningRunRequestedV1,
)
from va_market_data.application.coverage import take_coverage
from va_market_data.domain.coverage import CoverageItem, coverage_symbols, coverage_tickers
from va_market_data.domain.fundamentals import Fundamentals, Identity, MarketData
from va_market_data.domain.securities import Listing
from va_market_data.domain.universe import Ticker, Universe
from va_market_data.entrypoints.handlers import RunRequestedHandler
from va_platform.bus import InProcessBus

TODAY = date(2026, 11, 7)
UNIVERSE = [
    Ticker("SAP.DE", "SAP SE", "DAX", "DE0007164600"),
    Ticker("ALV.DE", "Allianz SE", "DAX", "DE0008404005"),
]
APPLE = CoverageItem(
    isin="US0378331005",
    asset_class="equity",
    fundamentals_symbol="AAPL",
    price_symbol="APC.DE",
    name="Apple Inc.",
)
ETF = CoverageItem(
    isin="IE00B4L5Y983",
    asset_class="etf",
    fundamentals_symbol=None,
    price_symbol="EUNL.DE",
    name="iShares Core MSCI World",
)
# Auch im Depot, aber schon im Referenzuniversum: kein zweiter Abruf
SAP_HELD = CoverageItem(
    isin="DE0007164600",
    asset_class="equity",
    fundamentals_symbol="SAP.DE",
    price_symbol="SAP.DE",
    name="SAP SE",
)


def _fund(t: Ticker, market_cap: float | None = 5e9) -> Fundamentals:
    return Fundamentals(
        identity=Identity(t.symbol, t.name, t.index), market=MarketData(market_cap=market_cap)
    )


class TestSymbols:
    def test_foreign_share_fundamentals_from_home_price_from_xetra(self):
        listings = [
            Listing(symbol="APC.DE", ticker="APC", exchange="GY"),
            Listing(symbol="APC.F", ticker="APC", exchange="GF"),
            Listing(symbol="AAPL", ticker="AAPL", exchange="US"),
        ]
        assert coverage_symbols("US0378331005", "equity", listings) == ("AAPL", "APC.DE")

    def test_german_share_both_from_xetra(self):
        listings = [Listing(symbol="SAP.DE", ticker="SAP", exchange="GY")]
        assert coverage_symbols("DE0007164600", "equity", listings) == ("SAP.DE", "SAP.DE")

    def test_without_xetra_the_home_listing_for_both(self):
        listings = [Listing(symbol="NOVO-B.CO", ticker="NOVOB", exchange="DC")]
        assert coverage_symbols("DK0062498333", "equity", listings) == ("NOVO-B.CO", "NOVO-B.CO")

    def test_an_etf_has_no_fundamentals(self):
        listings = [Listing(symbol="EUNL.DE", ticker="EUNL", exchange="GY")]
        assert coverage_symbols("IE00B4L5Y983", "etf", listings) == (None, "EUNL.DE")

    def test_a_bond_without_listing(self):
        assert coverage_symbols("DE000A383J95", "bond", []) == (None, None)

    def test_only_shares_outside_the_universe_are_fetched(self):
        tickers = coverage_tickers(
            [APPLE, ETF, SAP_HELD],
            universe_symbols={"SAP.DE", "ALV.DE"},
            universe_isins={"DE0007164600", "DE0008404005"},
        )
        assert tickers == [Ticker("AAPL", "Apple Inc.", "-", "US0378331005")]


class FakeCoverageStore:
    def __init__(self, items: list[CoverageItem], *, done: list[str] | None = None) -> None:
        self.items = items
        self.done = done or []
        self.recorded: list[tuple[int, str, str | None]] = []
        self.failing: set[str] = set()
        self.error: Exception | None = None

    def coverage(self) -> list[CoverageItem]:
        if self.error:
            raise self.error
        return list(self.items)

    def covered_snapshots(self, fetch_run_id: int) -> pd.DataFrame:
        tickers = [Ticker(s, s, "-") for s in self.done]
        return pd.DataFrame([_fund(t).to_flat_dict() for t in tickers])

    def record_covered(self, fetch_run_id: int, fund: Fundamentals, isin: str | None) -> None:
        if fund.symbol in self.failing:
            raise ConnectionError("db hiccup")
        self.recorded.append((fetch_run_id, fund.symbol, isin))

    def history_state(self, symbols):
        return {}


class FakeFetch:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def __call__(self, tickers, *, on_result, history):
        self.calls.append([t.symbol for t in tickers])
        rows = []
        for t in tickers:
            fund = _fund(t)
            on_result(fund)
            rows.append(fund.to_flat_dict())
        return pd.DataFrame(rows)


class TestTakeCoverage:
    def _take(self, store: FakeCoverageStore, fetch: FakeFetch, *, reused: bool = False):
        return take_coverage(
            fetch_run_id=10,
            universe=UNIVERSE,
            store=store,
            fetch=fetch,
            reused=reused,
        )

    def test_fetches_and_stores_as_coverage(self):
        store, fetch = FakeCoverageStore([APPLE, ETF, SAP_HELD]), FakeFetch()
        covered = self._take(store, fetch)
        assert fetch.calls == [["AAPL"]]
        assert store.recorded == [(10, "AAPL", "US0378331005")]
        assert list(covered.frame["symbol"]) == ["AAPL"]
        assert covered.isins == {"AAPL": "US0378331005"}

    def test_a_reused_run_fetches_only_what_is_missing(self):
        store = FakeCoverageStore(
            [APPLE, CoverageItem("US5949181045", "equity", "MSFT", None, "Microsoft")],
            done=["AAPL"],
        )
        fetch = FakeFetch()
        covered = self._take(store, fetch, reused=True)
        assert fetch.calls == [["MSFT"]]
        assert sorted(covered.frame["symbol"]) == ["AAPL", "MSFT"]

    def test_a_title_that_cannot_be_stored_is_left_out(self):
        store = FakeCoverageStore(
            [APPLE, CoverageItem("US5949181045", "equity", "MSFT", None, "Microsoft")]
        )
        store.failing = {"AAPL"}
        covered = self._take(store, FakeFetch())
        assert list(covered.frame["symbol"]) == ["MSFT"]

    def test_an_aborted_fetch_keeps_what_was_stored(self):
        """Event und Datenbank bleiben deckungsgleich, auch wenn der Abruf abbricht."""

        class Aborting(FakeFetch):
            def __call__(self, tickers, *, on_result, history):
                on_result(_fund(tickers[0]))
                raise RuntimeError("Rate-Limit")

        store = FakeCoverageStore(
            [APPLE, CoverageItem("US5949181045", "equity", "MSFT", None, "Microsoft")]
        )
        covered = self._take(store, Aborting())
        assert list(covered.frame["symbol"]) == ["AAPL"]
        assert [symbol for _, symbol, _ in store.recorded] == ["AAPL"]

    def test_unreadable_coverage_is_empty(self):
        store = FakeCoverageStore([APPLE])
        store.error = ConnectionError("db weg")
        fetch = FakeFetch()
        covered = self._take(store, fetch)
        assert covered.frame.empty
        assert fetch.calls == []

    def test_nothing_to_fetch(self):
        fetch = FakeFetch()
        assert self._take(FakeCoverageStore([ETF, SAP_HELD]), fetch).frame.empty
        assert fetch.calls == []


class FakeStore:
    """Der Speicher des Referenzuniversums wie in test_market_data_handler.py."""

    def find_reusable_fetch(self, day, symbols):
        return None

    def load_snapshots(self, fetch_run_id, symbols):
        raise AssertionError

    def start_fetch(self, tickers, source, as_of=None):
        return 10

    def history_state(self, symbols):
        return {}

    def record_fundamentals(self, fetch_run_id, fund):
        return None

    def finish_fetch(self, fetch_run_id, df):
        return None

    def instrument_ids(self, symbols):
        return {s: i for i, s in enumerate(sorted(symbols), start=101)}


def _run(bus: InProcessBus, coverage: FakeCoverageStore | None) -> Envelope[Any]:
    seen: list[Envelope[Any]] = []
    bus.subscribe(SNAPSHOT_COMPLETED, "probe", seen.append)
    RunRequestedHandler(
        bus,
        load_universe=lambda: Universe(tickers=UNIVERSE, source="Replay"),
        store=FakeStore(),
        fetch=FakeFetch(),
        coverage=coverage,
        today=lambda: TODAY,
    ).subscribe()
    bus.publish(
        new_envelope(
            RUN_REQUESTED,
            ScreeningRunRequestedV1(run_id=1, trigger="scheduled", options=RunOptionsV1()),
            source="va/test",
        )
    )
    [completed] = seen
    return completed


@pytest.fixture
def bus() -> InProcessBus:
    return InProcessBus(max_deliver=1)


class TestWeeklyRun:
    def test_covered_shares_travel_apart_from_the_universe(self, bus):
        completed = _run(bus, FakeCoverageStore([APPLE, ETF, SAP_HELD]))
        data = completed.data
        assert sorted(f.identity.symbol for f in data.fundamentals) == ["ALV.DE", "SAP.DE"]
        assert [f.identity.symbol for f in data.covered] == ["AAPL"]
        assert data.covered[0].identity.index == "-"
        assert data.isins["AAPL"] == "US0378331005"
        assert "AAPL" in data.instrument_ids
        assert data.universe.size == 2  # die Abdeckung zaehlt nicht zum Universum

    def test_progress_counts_universe_and_coverage(self, bus):
        from va_contracts.events.v1 import FETCH_PROGRESSED

        progress: list[Any] = []
        bus.subscribe(FETCH_PROGRESSED, "probe-progress", progress.append)
        _run(bus, FakeCoverageStore([APPLE]))
        assert [(p.data.done, p.data.total) for p in progress] == [(1, 3), (2, 3), (3, 3)]
        assert progress[-1].data.symbol == "AAPL"

    def test_without_coverage_the_event_is_as_before(self, bus):
        completed = _run(bus, None)
        assert completed.data.covered == []
        assert "AAPL" not in completed.data.isins

    def test_a_broken_coverage_does_not_stop_the_run(self, bus):
        store = FakeCoverageStore([APPLE])
        store.error = ConnectionError("db weg")
        completed = _run(bus, store)
        assert completed.data.covered == []
        assert len(completed.data.fundamentals) == 2
