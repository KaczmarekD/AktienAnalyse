"""Handler von market-data am Bus: screening.run.requested -> marketdata.snapshot.completed (P1.8).

Universum, Abruf und Speicher sind Fakes. Der Bus ist der echte ``InProcessBus``; ein
Probe-Consumer sammelt, was der Handler veroeffentlicht.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd
import pytest

from va_contracts import Envelope, new_envelope
from va_contracts.events.v1 import (
    FETCH_PROGRESSED,
    RUN_FAILED,
    RUN_REQUESTED,
    SNAPSHOT_COMPLETED,
    RunOptionsV1,
    ScreeningRunRequestedV1,
)
from va_market_data.domain.fundamentals import Fundamentals, Identity, MarketData
from va_market_data.domain.history import HistoryState
from va_market_data.domain.universe import Ticker, Universe
from va_market_data.entrypoints.handlers import RunRequestedHandler
from va_platform.bus import InProcessBus

TODAY = date(2026, 10, 17)
TICKERS = [
    Ticker("AAA.DE", "Alpha AG", "DAX", "DE000A"),
    Ticker("BBB.DE", "Beta AG", "MDAX"),
    Ticker("CCC.DE", "Gamma AG", "DAX"),
]


def _fund(t: Ticker, market_cap: float | None = 5e9) -> Fundamentals:
    return Fundamentals(
        identity=Identity(t.symbol, t.name, t.index), market=MarketData(market_cap=market_cap)
    )


class FakeStore:
    def __init__(self, *, reusable: int | None = None, failing: frozenset[str] = frozenset()):
        self.reusable = reusable
        self.failing = failing
        self.calls: list[tuple[str, Any]] = []
        self.history: dict[str, HistoryState] = {}

    def find_reusable_fetch(self, day, symbols):
        self.calls.append(("find_reusable_fetch", (day, list(symbols))))
        return self.reusable

    def load_snapshots(self, fetch_run_id, symbols):
        self.calls.append(("load_snapshots", (fetch_run_id, list(symbols))))
        return pd.DataFrame([_fund(t).to_flat_dict() for t in TICKERS if t.symbol in symbols])

    def start_fetch(self, tickers, source, as_of=None):
        self.calls.append(("start_fetch", (list(tickers), source, as_of)))
        return 10

    def history_state(self, symbols):
        self.calls.append(("history_state", list(symbols)))
        return self.history

    def record_fundamentals(self, fetch_run_id, fund):
        if fund.symbol in self.failing:
            raise ConnectionError("db hiccup")
        self.calls.append(("record_fundamentals", fund.symbol))

    def finish_fetch(self, fetch_run_id, df):
        self.calls.append(("finish_fetch", (fetch_run_id, list(df["symbol"]))))

    def names(self) -> list[str]:
        return [name for name, _ in self.calls]


class FakeFetch:
    def __init__(self, error: Exception | None = None):
        self.error = error
        self.calls: list[dict[str, Any]] = []

    def __call__(self, tickers, *, on_result, history):
        self.calls.append({"tickers": list(tickers), "history": history})
        if self.error:
            raise self.error
        rows = []
        for t in tickers:
            fund = _fund(t, market_cap=None if t.symbol == "CCC.DE" else 5e9)
            on_result(fund)
            rows.append(fund.to_flat_dict())
        return pd.DataFrame(rows)


@pytest.fixture
def bus() -> InProcessBus:
    return InProcessBus(max_deliver=1)


def _probe(bus: InProcessBus, *specs) -> list[Envelope[Any]]:
    seen: list[Envelope[Any]] = []
    for spec in specs:
        bus.subscribe(spec, f"probe-{spec.type}", seen.append)
    return seen


def _request(bus: InProcessBus, **options: bool) -> Envelope[ScreeningRunRequestedV1]:
    env = new_envelope(
        RUN_REQUESTED,
        ScreeningRunRequestedV1(run_id=1, trigger="scheduled", options=RunOptionsV1(**options)),
        source="va/test",
        correlationid="1",
    )
    bus.publish(env)
    return env


def _handler(bus, store, fetch, universe=None, **kwargs) -> RunRequestedHandler:
    universe = universe or Universe(
        TICKERS,
        source="iShares",
        as_of=date(2026, 10, 16),
        added=[Ticker("NEU.DE", "Neu AG", "MDAX")],
        removed=[Ticker("ALT.DE", "Alt AG", "DAX")],
    )
    handler = RunRequestedHandler(
        bus, load_universe=lambda: universe, store=store, fetch=fetch, today=lambda: TODAY, **kwargs
    )
    handler.subscribe()
    return handler


class TestSnapshot:
    def test_fetches_stores_and_publishes_the_snapshot(self, bus):
        store, fetch = FakeStore(), FakeFetch()
        _handler(bus, store, fetch)
        seen = _probe(bus, SNAPSHOT_COMPLETED, RUN_FAILED)
        request = _request(bus)

        assert [e.type for e in seen] == [SNAPSHOT_COMPLETED.type]
        snap = seen[0]
        assert (snap.correlationid, snap.causationid, snap.source) == (
            "1",
            request.id,
            "va/market-data",
        )
        data = snap.data
        assert (data.run_id, data.trigger, data.fetch_run_id, data.as_of) == (
            1,
            "scheduled",
            10,
            TODAY,
        )
        assert [f.symbol for f in data.fundamentals] == ["AAA.DE", "BBB.DE", "CCC.DE"]
        assert data.success_share == pytest.approx(2 / 3)
        assert (data.universe.source, data.universe.as_of, data.universe.size) == (
            "iShares",
            date(2026, 10, 16),
            3,
        )
        assert [(m.symbol, m.name, m.index) for m in data.universe.added] == [
            ("NEU.DE", "Neu AG", "MDAX")
        ]
        assert [m.symbol for m in data.universe.removed] == ["ALT.DE"]
        assert store.names() == [
            "find_reusable_fetch",
            "start_fetch",
            "history_state",
            "record_fundamentals",
            "record_fundamentals",
            "record_fundamentals",
            "finish_fetch",
        ]
        assert store.calls[1][1] == (TICKERS, "iShares", date(2026, 10, 16))

    def test_progress_is_published_per_ticker(self, bus):
        _handler(bus, FakeStore(), FakeFetch())
        seen = _probe(bus, FETCH_PROGRESSED)
        _request(bus)
        assert [(e.data.done, e.data.total, e.data.symbol, e.data.ok) for e in seen] == [
            (1, 3, "AAA.DE", True),
            (2, 3, "BBB.DE", True),
            (3, 3, "CCC.DE", False),
        ]

    def test_stored_history_is_passed_to_the_fetch(self, bus):
        store, fetch = FakeStore(), FakeFetch()
        store.history = {"AAA.DE": HistoryState(last_share_date=date(2026, 7, 29))}
        _handler(bus, store, fetch)
        _request(bus)
        assert fetch.calls[0]["history"] == store.history

    def test_ticker_that_cannot_be_stored_is_dropped(self, bus):
        store, fetch = FakeStore(failing=frozenset({"BBB.DE"})), FakeFetch()
        _handler(bus, store, fetch)
        seen = _probe(bus, SNAPSHOT_COMPLETED)
        _request(bus)
        assert [f.symbol for f in seen[0].data.fundamentals] == ["AAA.DE", "CCC.DE"]
        assert store.calls[-1] == ("finish_fetch", (10, ["AAA.DE", "CCC.DE"]))

    def test_dax_only_filters_the_universe(self, bus):
        store, fetch = FakeStore(), FakeFetch()
        _handler(bus, store, fetch, dax_only=True)
        seen = _probe(bus, SNAPSHOT_COMPLETED)
        _request(bus)
        assert [t.symbol for t in fetch.calls[0]["tickers"]] == ["AAA.DE", "CCC.DE"]
        assert seen[0].data.universe.size == 2

    def test_failing_progress_report_does_not_stop_the_fetch(self, bus):
        store, fetch = FakeStore(), FakeFetch()
        handler = _handler(bus, store, fetch)
        handler._progress = lambda env, total: _broken_progress  # type: ignore[method-assign]
        seen = _probe(bus, SNAPSHOT_COMPLETED, RUN_FAILED)
        _request(bus)
        assert [e.type for e in seen] == [SNAPSHOT_COMPLETED.type]
        assert len(seen[0].data.fundamentals) == 3


def _broken_progress(fund: Fundamentals) -> None:
    raise ValueError("Fortschritt kaputt")


class TestReuse:
    def test_reuses_todays_fetch(self, bus):
        store, fetch = FakeStore(reusable=99), FakeFetch()
        _handler(bus, store, fetch)
        seen = _probe(bus, SNAPSHOT_COMPLETED)
        _request(bus)
        assert fetch.calls == []
        assert store.names() == ["find_reusable_fetch", "load_snapshots"]
        assert store.calls[0][1] == (TODAY, ["AAA.DE", "BBB.DE", "CCC.DE"])
        assert seen[0].data.fetch_run_id == 99
        assert len(seen[0].data.fundamentals) == 3

    def test_force_refresh_skips_reuse(self, bus):
        store, fetch = FakeStore(reusable=99), FakeFetch()
        _handler(bus, store, fetch)
        _request(bus, force_refresh=True)
        assert "find_reusable_fetch" not in store.names()
        assert len(fetch.calls) == 1


class TestFailure:
    def test_error_becomes_run_failed(self, bus):
        _handler(bus, FakeStore(), FakeFetch(error=RuntimeError("yfinance down")))
        seen = _probe(bus, SNAPSHOT_COMPLETED, RUN_FAILED)
        _request(bus, dry_run=True)
        assert [e.type for e in seen] == [RUN_FAILED.type]
        failed = seen[0].data
        assert (failed.run_id, failed.stage, failed.trigger) == (1, "market-data", "scheduled")
        assert failed.options.dry_run is True
        assert "yfinance down" in failed.reason
        assert failed.detail is not None
        assert "RuntimeError" in failed.detail

    def test_unloadable_universe_becomes_run_failed(self, bus):
        def broken() -> Universe:
            raise OSError("CSV fehlt")

        handler = RunRequestedHandler(
            bus, load_universe=broken, store=FakeStore(), fetch=FakeFetch(), today=lambda: TODAY
        )
        handler.subscribe()
        seen = _probe(bus, RUN_FAILED)
        _request(bus)
        assert "CSV fehlt" in seen[0].data.reason
