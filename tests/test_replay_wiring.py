"""U5.1: Mit ``REPLAY_SOURCE`` baut die Composition Root Universum und Abruf aus einer Fixture.

Kein Aufruf von iShares, Deka, OpenFIGI oder Yahoo: Das Netz ist im Test gesperrt.
"""

from __future__ import annotations

import socket
from pathlib import Path

import pytest

from src.composition import build_adapters
from src.regression.case import ReplayCase

FIXTURE = Path(__file__).parent / "fixtures" / "replay" / "2026-10-30_scoring-run-1.json"


@pytest.fixture
def no_network(monkeypatch):
    def refuse(*args: object, **kwargs: object) -> None:
        msg = "Netzzugriff im Replay"
        raise AssertionError(msg)

    for name in ("socket", "create_connection", "getaddrinfo"):
        monkeypatch.setattr(socket, name, refuse)


@pytest.fixture
def sleeps(monkeypatch):
    calls: list[float] = []
    monkeypatch.setattr("va_market_data.application.fetch.time.sleep", calls.append)
    return calls


@pytest.fixture
def replay_settings(settings):
    return settings.model_copy(update={"replay_source": FIXTURE, "smtp_plain": True})


def test_universe_comes_from_the_fixture(replay_settings, no_network):
    expected = ReplayCase.from_json(FIXTURE.read_text(encoding="utf-8")).snapshots
    universe = build_adapters(replay_settings).load_universe()
    assert universe.source == "Replay"
    assert [t.symbol for t in universe.tickers] == list(expected["symbol"])
    # ISIN aus der Fallback-CSV: fuer die bekannten Titel vorhanden
    assert sum(t.isin is not None for t in universe.tickers) > 80


def test_fetch_returns_the_stored_snapshots_without_pause(replay_settings, no_network, sleeps):
    adapters = build_adapters(replay_settings)
    tickers = adapters.load_universe().tickers
    seen = []
    frame = adapters.fetch(tickers, on_result=seen.append, history={})
    expected = ReplayCase.from_json(FIXTURE.read_text(encoding="utf-8")).snapshots
    assert [f.symbol for f in seen] == list(expected["symbol"])
    assert all(f.raw is None for f in seen)
    assert frame["market_cap"].tolist() == pytest.approx(
        expected["market_cap"].tolist(), nan_ok=True
    )
    assert set(sleeps) == {0.0}
