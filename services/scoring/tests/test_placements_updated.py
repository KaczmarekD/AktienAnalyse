"""Neue Aktie sofort einordnen (D4.6): ``marketdata.coverage.fetched`` -> ``scoring.placements.updated``.

- Eingeordnet wird gegen den juengsten Bewertungslauf: seine Eingangsdaten und sein Profil.
- Die Einordnung kommt nach ``scoring.placement`` zu dessen ID und geht mit Sektor und ISIN an
  portfolio. Das Ranking bleibt unberuehrt.
- Ohne Bewertungslauf wartet sie; ein Fehler in der Rechnung kostet nur sie.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Any

import pytest

from va_contracts import Envelope, new_envelope
from va_contracts.events.v1 import (
    COVERAGE_FETCHED,
    PLACEMENTS_UPDATED,
    CoverageFetchedV1,
    FundamentalsV1,
)
from va_platform.bus import InProcessBus
from va_scoring.application.ports import Reference
from va_scoring.domain.placement import place
from va_scoring.domain.scoring import ScoringConfig, score
from va_scoring.entrypoints.handlers import CoverageFetchedHandler

if TYPE_CHECKING:
    import pandas as pd

APPLE = "US0378331005"
FRIDAY = date(2026, 11, 27)


class FakeStore:
    def __init__(self) -> None:
        self.placements: list[tuple[int, list[Any]]] = []

    def record_scoring(self, *args: Any, **kwargs: Any) -> int:  # pragma: no cover
        raise NotImplementedError

    def record_placements(self, scoring_run_id, placements) -> None:
        self.placements.append((scoring_run_id, list(placements)))


class FakeReference:
    def __init__(self, reference: Reference | None) -> None:
        self.reference = reference

    def latest_reference(self) -> Reference | None:
        return self.reference


def _apple(mock_universe_df: pd.DataFrame) -> pd.DataFrame:
    row = mock_universe_df[mock_universe_df["symbol"] == "VAL.DE"].copy()
    return row.assign(symbol="AAPL", index="-")


def _fetched(bus: InProcessBus, rows: pd.DataFrame) -> None:
    funds = [FundamentalsV1.from_flat(r) for r in rows.to_dict("records")]
    bus.publish(
        new_envelope(
            COVERAGE_FETCHED,
            CoverageFetchedV1(as_of=FRIDAY, fundamentals=funds, isins={"AAPL": APPLE}),
            source="va/market-data",
        )
    )


@pytest.fixture
def bus() -> InProcessBus:
    return InProcessBus(max_deliver=1)


def _probe(bus: InProcessBus) -> list[Envelope[Any]]:
    seen: list[Envelope[Any]] = []
    bus.subscribe(PLACEMENTS_UPDATED, "probe", seen.append)
    return seen


def test_placed_against_the_latest_scoring_run(bus, mock_universe_df):
    store = FakeStore()
    reference = Reference(8, mock_universe_df, ScoringConfig())
    CoverageFetchedHandler(bus, store=store, reference=FakeReference(reference)).subscribe()
    seen = _probe(bus)
    apple = _apple(mock_universe_df)
    _fetched(bus, apple)
    [event] = seen
    assert (event.data.scoring_run_id, event.data.as_of) == (8, FRIDAY)
    [placement] = event.data.placements
    assert (placement.symbol, placement.isin, placement.below_size_filter) == ("AAPL", APPLE, False)
    assert placement.sector == apple["sector"].iloc[0]
    # Dieselbe Rechnung wie im Bewertungslauf
    expected = place(score(mock_universe_df, ScoringConfig()), apple, ScoringConfig())
    assert placement.composite_score == pytest.approx(expected["composite_score"].iloc[0])
    assert store.placements == [(8, event.data.placements)]


def test_without_a_scoring_run_it_waits(bus, mock_universe_df):
    store = FakeStore()
    CoverageFetchedHandler(bus, store=store, reference=FakeReference(None)).subscribe()
    seen = _probe(bus)
    _fetched(bus, _apple(mock_universe_df))
    assert (seen, store.placements) == ([], [])


def test_a_failed_calculation_costs_only_the_placement(bus, mock_universe_df, monkeypatch):
    def broken(*args, **kwargs):
        msg = "kaputt"
        raise ValueError(msg)

    monkeypatch.setattr("va_scoring.entrypoints.handlers.place", broken)
    store = FakeStore()
    reference = Reference(8, mock_universe_df, ScoringConfig())
    CoverageFetchedHandler(bus, store=store, reference=FakeReference(reference)).subscribe()
    seen = _probe(bus)
    _fetched(bus, _apple(mock_universe_df))
    assert (seen, store.placements) == ([], [])
