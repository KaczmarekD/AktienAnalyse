"""Die Kette der Universum-Quellen (P1.4) mit Fake-Quellen, ganz ohne Netz.

Die erste gueltige Quelle gewinnt, ungueltige fallen durch, die Fallback-CSV kommt zuletzt.
Die echten Quellen (iShares, Deka) testet test_universe_sources.py.
"""

from __future__ import annotations

from datetime import date

import pytest

from va_market_data.application.ports import LiveUniverse, UniverseSource
from va_market_data.application.universe import load_universe
from va_market_data.domain.universe import (
    FALLBACK_SOURCE,
    SourceError,
    Ticker,
    UniverseConfig,
)

TODAY = date(2026, 9, 30)
CFG = UniverseConfig(expected_counts={"DAX": 2, "MDAX": 1})
FALLBACK = [
    Ticker("SAP.DE", "SAP", "DAX", "DE0007164600"),
    Ticker("SIE.DE", "Siemens", "DAX", "DE0007236101"),
    Ticker("BOSS.DE", "Hugo Boss", "MDAX", "DE000A1PHFF7"),
]
LIVE = [FALLBACK[0], FALLBACK[1], Ticker("SAX.DE", "Stroeer", "MDAX", "DE0007493991")]


class FakeSource:
    """Eine Quelle, die ein festes Ergebnis liefert oder scheitert."""

    def __init__(self, name: str, result: LiveUniverse | Exception) -> None:
        self.name = name
        self.calls: list[tuple[list[Ticker], UniverseConfig, date]] = []
        self._result = result

    def load(self, fallback: list[Ticker], cfg: UniverseConfig, today: date) -> LiveUniverse:
        self.calls.append((list(fallback), cfg, today))
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


def _ok(name: str, as_of: date | None = date(2026, 9, 29)) -> FakeSource:
    return FakeSource(name, LiveUniverse(tickers=list(LIVE), as_of=as_of))


def _broken(name: str) -> FakeSource:
    return FakeSource(name, SourceError(f"{name} kaputt"))


def _load(*sources: UniverseSource, force_fallback: bool = False):
    return load_universe(list(sources), FALLBACK, CFG, TODAY, force_fallback=force_fallback)


class TestChain:
    def test_first_valid_source_wins(self):
        first, second = _ok("iShares"), _ok("Deka", as_of=None)
        uni = _load(first, second)
        assert (uni.source, uni.as_of) == ("iShares", date(2026, 9, 29))
        assert [t.symbol for t in uni.tickers] == ["SAP.DE", "SIE.DE", "SAX.DE"]
        assert second.calls == []

    def test_invalid_source_falls_through(self):
        uni = _load(_broken("iShares"), _ok("Deka", as_of=None))
        assert (uni.source, uni.as_of) == ("Deka", None)

    @pytest.mark.parametrize("error", [SourceError("ungueltig"), OSError("Netz"), KeyError("x")])
    def test_any_error_of_a_source_falls_through(self, error):
        assert _load(FakeSource("iShares", error), _ok("Deka")).source == "Deka"

    def test_csv_comes_last(self):
        uni = _load(_broken("iShares"), _broken("Deka"))
        assert uni.source == FALLBACK_SOURCE
        assert uni.tickers == FALLBACK
        assert (uni.as_of, uni.added, uni.removed) == (None, [], [])

    def test_without_sources_the_csv_is_used(self):
        assert _load().source == FALLBACK_SOURCE

    def test_force_fallback_asks_no_source(self):
        source = _ok("iShares")
        assert _load(source, force_fallback=True).source == FALLBACK_SOURCE
        assert source.calls == []

    def test_sources_get_fallback_config_and_day(self):
        source = _ok("iShares")
        _load(source)
        assert source.calls == [(FALLBACK, CFG, TODAY)]


class TestDiffAgainstCsv:
    def test_added_and_removed(self):
        uni = _load(_ok("iShares"))
        assert [t.symbol for t in uni.added] == ["SAX.DE"]
        assert [t.symbol for t in uni.removed] == ["BOSS.DE"]

    def test_live_tickers_are_deduplicated(self):
        doubled = LiveUniverse(tickers=[*LIVE, Ticker("SAP.DE", "SAP 2", "MDAX")], as_of=None)
        uni = _load(FakeSource("iShares", doubled))
        assert [t.symbol for t in uni.tickers] == ["SAP.DE", "SIE.DE", "SAX.DE"]

    def test_fallback_is_deduplicated(self):
        doubled = [*FALLBACK, Ticker("SAP.DE", "SAP 2", "MDAX")]
        uni = load_universe([], doubled, CFG, TODAY)
        assert uni.tickers == FALLBACK
