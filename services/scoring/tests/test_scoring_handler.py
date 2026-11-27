"""Handler von scoring am Bus: marketdata.snapshot.completed -> scoring.run.completed (P1.8)."""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Any

import pytest

from va_contracts import Envelope, new_envelope
from va_contracts.events.v1 import (
    RUN_FAILED,
    SCORING_RUN_COMPLETED,
    SNAPSHOT_COMPLETED,
    FundamentalsV1,
    ProfileRefV1,
    RunOptionsV1,
    SnapshotCompletedV1,
    UniverseInfoV1,
    UniverseMemberV1,
)
from va_platform.bus import InProcessBus
from va_scoring.application.profiles import FixedProfile
from va_scoring.domain.profile import ActiveProfile, ProfileVersionRef
from va_scoring.domain.scoring import ScoringConfig, score
from va_scoring.entrypoints.handlers import SnapshotCompletedHandler

if TYPE_CHECKING:
    import pandas as pd

UNIVERSE = UniverseInfoV1(
    source="iShares",
    as_of=date(2026, 10, 16),
    size=8,
    added=[UniverseMemberV1(symbol="NEU.DE", name="Neu AG", index="MDAX")],
)


class FakeStore:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[dict[str, Any]] = []
        self.placements: list[tuple[int, list[Any]]] = []

    def record_scoring(self, fetch_run_id, df_all, scored, cfg, profile=None, instrument_ids=None):
        if self.error:
            raise self.error
        self.calls.append(
            {
                "fetch_run_id": fetch_run_id,
                "df_all": df_all,
                "scored": scored,
                "cfg": cfg,
                "profile": profile,
                "instrument_ids": instrument_ids,
            }
        )
        return 20

    def record_placements(self, scoring_run_id, placements):
        self.placements.append((scoring_run_id, list(placements)))


@pytest.fixture
def bus() -> InProcessBus:
    return InProcessBus(max_deliver=1)


def _probe(bus: InProcessBus) -> list[Envelope[Any]]:
    seen: list[Envelope[Any]] = []
    bus.subscribe(SCORING_RUN_COMPLETED, "probe-completed", seen.append)
    bus.subscribe(RUN_FAILED, "probe-failed", seen.append)
    return seen


def _snapshot(
    bus: InProcessBus,
    frame: pd.DataFrame,
    covered: pd.DataFrame | None = None,
    isins: dict[str, str] | None = None,
    **options: bool,
) -> Envelope[SnapshotCompletedV1]:
    env = new_envelope(
        SNAPSHOT_COMPLETED,
        SnapshotCompletedV1(
            run_id=1,
            trigger="scheduled",
            options=RunOptionsV1(**options),
            fetch_run_id=10,
            as_of=date(2026, 10, 17),
            success_share=1.0,
            universe=UNIVERSE,
            fundamentals=[FundamentalsV1.from_flat(r) for r in frame.to_dict("records")],
            instrument_ids={str(s): i for i, s in enumerate(frame["symbol"], start=1)},
            covered=[]
            if covered is None
            else [FundamentalsV1.from_flat(r) for r in covered.to_dict("records")],
            isins=isins or {},
        ),
        source="va/test",
        correlationid="1",
    )
    bus.publish(env)
    return env


def _subscribe(bus, store, cfg=None) -> None:
    profile = FixedProfile(cfg or ScoringConfig())
    SnapshotCompletedHandler(bus, store=store, profile=profile).subscribe()


def test_scores_stores_and_publishes_the_ranking(bus, mock_universe_df):
    store = FakeStore()
    _subscribe(bus, store)
    seen = _probe(bus)
    snapshot = _snapshot(bus, mock_universe_df, dry_run=True)

    assert [e.type for e in seen] == [SCORING_RUN_COMPLETED.type]
    env = seen[0]
    assert (env.source, env.correlationid, env.causationid) == ("va/scoring", "1", snapshot.id)
    data = env.data
    assert (data.run_id, data.trigger, data.scoring_run_id, data.fetch_run_id) == (
        1,
        "scheduled",
        20,
        10,
    )
    assert data.options.dry_run is True
    assert data.as_of == date(2026, 10, 17)
    assert data.universe == UNIVERSE
    assert (data.value_weight, data.quality_weight) == (0.6, 0.4)

    expected = score(mock_universe_df, ScoringConfig())
    assert [r.fundamentals.symbol for r in data.ranking] == list(expected["symbol"])
    assert [r.rank_overall for r in data.ranking] == list(expected["rank_overall"])
    assert data.ranking[0].composite_score == pytest.approx(expected["composite_score"].iloc[0])
    assert data.ranking[0].factor_ranks  # Raenge je Faktor reisen mit

    call = store.calls[0]
    assert call["fetch_run_id"] == 10
    # P5.3: die IDs aus dem Event, scoring liest market_data.instrument nicht
    assert call["instrument_ids"] == snapshot.data.instrument_ids
    assert set(call["df_all"]["symbol"]) == set(mock_universe_df["symbol"])
    assert list(call["scored"]["symbol"]) == list(expected["symbol"])


def test_anchors_are_stored_and_published(bus, mock_universe_df):
    """F3.1: Anker nach score(), im Speicher und im Event; der Composite bleibt gleich."""
    store = FakeStore()
    _subscribe(bus, store)
    seen = _probe(bus)
    _snapshot(bus, mock_universe_df)
    scored = store.calls[0]["scored"]
    assert "implied_fcf_growth" in scored.columns
    expected = score(mock_universe_df, ScoringConfig())
    assert list(scored["composite_score"]) == pytest.approx(
        list(expected["composite_score"]), nan_ok=True
    )
    with_growth = [r for r in seen[0].data.ranking if r.anchors.get("implied_fcf_growth")]
    assert with_growth  # die Mock-Titel haben Börsenwert und Kurs/FCF


def test_weights_come_from_the_config(bus, mock_universe_df):
    _subscribe(bus, FakeStore(), ScoringConfig(value_weight=0.5, quality_weight=0.5))
    seen = _probe(bus)
    _snapshot(bus, mock_universe_df)
    assert (seen[0].data.value_weight, seen[0].data.quality_weight) == (0.5, 0.5)


def test_the_event_carries_the_parameters_of_the_run(bus, mock_universe_df):
    # Track G (G3): das web-api nennt Schwellen und Faktoren des Laufs in Tooltips
    cfg = ScoringConfig(value_weight=0.5, quality_weight=0.5, value_trap_value_threshold=0.8)
    _subscribe(bus, FakeStore(), cfg)
    seen = _probe(bus)
    _snapshot(bus, mock_universe_df)
    params = seen[0].data.params
    assert params is not None
    assert (params.value_weight, params.value_trap_value_threshold) == (0.5, 0.8)
    assert params.min_market_cap == cfg.min_market_cap
    assert set(params.value_factors) == set(cfg.value_factors)
    assert set(params.quality_factors) == set(cfg.quality_factors)


def test_without_scoreable_data_the_run_fails_with_no_data(bus, mock_universe_df):
    store = FakeStore()
    _subscribe(bus, store)
    seen = _probe(bus)
    tiny = mock_universe_df.assign(market_cap=1.0)  # alle scheitern am Groessenfilter
    _snapshot(bus, tiny)
    assert [e.type for e in seen] == [RUN_FAILED.type]
    failed = seen[0].data
    assert (failed.stage, failed.reason, failed.scoring_run_id) == ("scoring", "no_data", 20)
    assert len(store.calls) == 1  # der Bewertungslauf ist trotzdem gespeichert


def test_empty_snapshot_is_no_data(bus, mock_universe_df):
    store = FakeStore()
    _subscribe(bus, store)
    seen = _probe(bus)
    _snapshot(bus, mock_universe_df.iloc[0:0])
    assert seen[0].data.reason == "no_data"
    assert store.calls[0]["df_all"].empty


def test_error_becomes_run_failed(bus, mock_universe_df):
    _subscribe(bus, FakeStore(error=ConnectionError("db weg")))
    seen = _probe(bus)
    _snapshot(bus, mock_universe_df)
    failed = seen[0].data
    assert (failed.stage, failed.scoring_run_id) == ("scoring", None)
    assert "db weg" in failed.reason
    assert failed.detail is not None
    assert "ConnectionError" in failed.detail


# --- P2b.3: das aktive Profil ----------------------------------------------------------------

OWN = ProfileVersionRef(3, "Eigenes", 2, {"value_weight": 0.5})


class FakeProfile:
    """``ProfileSource``: ein festes aktives Profil, oder ein Fehler beim Lesen."""

    def __init__(self, active: ActiveProfile | None = None, error: Exception | None = None) -> None:
        self._active = active
        self._error = error

    def active(self) -> ActiveProfile:
        if self._error is not None:
            raise self._error
        assert self._active is not None
        return self._active


def test_without_profile_the_event_names_none(bus, mock_universe_df):
    store = FakeStore()
    _subscribe(bus, store)
    seen = _probe(bus)
    _snapshot(bus, mock_universe_df)
    assert seen[0].data.profile is None
    assert store.calls[0]["profile"] is None


def test_active_profile_is_used_stored_and_named(bus, mock_universe_df):
    store = FakeStore()
    cfg = ScoringConfig(value_weight=0.5, quality_weight=0.5)
    SnapshotCompletedHandler(
        bus, store=store, profile=FakeProfile(ActiveProfile(cfg, OWN))
    ).subscribe()
    seen = _probe(bus)
    _snapshot(bus, mock_universe_df)

    data = seen[0].data
    assert (data.value_weight, data.quality_weight) == (0.5, 0.5)
    assert data.profile == ProfileRefV1(profile_id=3, version=2, name="Eigenes")
    assert (store.calls[0]["cfg"], store.calls[0]["profile"]) == (cfg, OWN)
    expected = score(mock_universe_df, cfg)
    assert [r.fundamentals.symbol for r in data.ranking] == list(expected["symbol"])


def test_unreadable_profile_fails_the_run_before_scoring(bus, mock_universe_df):
    store = FakeStore()
    SnapshotCompletedHandler(
        bus, store=store, profile=FakeProfile(error=ConnectionError("db weg"))
    ).subscribe()
    seen = _probe(bus)
    _snapshot(bus, mock_universe_df)
    failed = seen[0].data
    assert (failed.stage, failed.scoring_run_id) == ("scoring", None)
    assert "db weg" in failed.reason
    assert store.calls == []


# --- D4.1: Einordnung ---------------------------------------------------------------------------

APPLE = "US0378331005"
SMALL = "DE0000000001"


def _covered(mock_universe_df: pd.DataFrame) -> pd.DataFrame:
    row = mock_universe_df[mock_universe_df["symbol"] == "VAL.DE"].copy()
    row["symbol"] = "AAPL"
    row["index"] = "-"
    return row


def test_depot_stocks_are_placed_into_the_reference(bus, mock_universe_df):
    store = FakeStore()
    _subscribe(bus, store)
    seen = _probe(bus)
    _snapshot(
        bus,
        mock_universe_df,
        covered=_covered(mock_universe_df),
        isins={"AAPL": APPLE, "SMALL.DE": SMALL},
    )
    data = seen[0].data
    placements = {p.symbol: p for p in data.placements}
    # Die Abdeckung und der Universumstitel unter dem Groessenfilter, sonst keiner
    assert set(placements) == {"AAPL", "SMALL.DE"}
    assert placements["AAPL"].isin == APPLE
    assert placements["AAPL"].below_size_filter is False
    assert placements["SMALL.DE"].below_size_filter is True
    assert placements["SMALL.DE"].instrument_id is not None
    assert placements["AAPL"].composite_score is not None
    assert placements["AAPL"].factor_ranks
    assert store.placements == [(20, data.placements)]


def test_the_ranking_stays_the_same_with_placements(bus, mock_universe_df):
    _subscribe(bus, FakeStore())
    seen = _probe(bus)
    _snapshot(bus, mock_universe_df)
    _snapshot(bus, mock_universe_df, covered=_covered(mock_universe_df))
    without, with_covered = (env.data for env in seen)
    strip = {"isin", "composite_percentile"}
    assert [r.model_dump(exclude=strip) for r in without.ranking] == [
        r.model_dump(exclude=strip) for r in with_covered.ranking
    ]


def test_ranking_rows_carry_isin_and_composite_percentile(bus, mock_universe_df):
    _subscribe(bus, FakeStore())
    seen = _probe(bus)
    _snapshot(bus, mock_universe_df, isins={"VAL.DE": "DE0000000002"})
    ranking = seen[0].data.ranking
    top = ranking[0]
    assert (top.fundamentals.symbol, top.isin) == ("VAL.DE", "DE0000000002")
    assert top.composite_percentile == 1.0
    with_composite = [r for r in ranking if r.composite_score is not None]
    assert all(r.composite_percentile is not None for r in with_composite)
    assert all(r.composite_percentile is None for r in ranking if r.composite_score is None)
    # Nicht in der flachen Zeile: Mail und CSV bleiben gleich
    assert "composite_percentile" not in top.to_flat()
    assert "isin" not in top.to_flat()


def test_a_malformed_isin_costs_only_the_isin(bus, mock_universe_df):
    """``snapshot.isins`` ist nicht geprüft: Eine kaputte ISIN darf den Lauf nicht kosten."""
    _subscribe(bus, FakeStore())
    seen = _probe(bus)
    _snapshot(
        bus,
        mock_universe_df,
        covered=_covered(mock_universe_df),
        isins={"VAL.DE": "kaputt", "AAPL": "us0378331005"},
    )
    assert seen[0].type == SCORING_RUN_COMPLETED.type
    by_symbol = {r.fundamentals.symbol: r for r in seen[0].data.ranking}
    assert by_symbol["VAL.DE"].isin is None
    [apple] = [p for p in seen[0].data.placements if p.symbol == "AAPL"]
    assert apple.isin is None


def test_a_failed_placement_keeps_the_ranking(bus, mock_universe_df, monkeypatch):
    def broken(*args, **kwargs):
        msg = "kaputt"
        raise ValueError(msg)

    monkeypatch.setattr("va_scoring.entrypoints.handlers.place", broken)
    _subscribe(bus, FakeStore())
    seen = _probe(bus)
    _snapshot(bus, mock_universe_df, covered=_covered(mock_universe_df))
    assert seen[0].type == SCORING_RUN_COMPLETED.type
    assert seen[0].data.placements == []
