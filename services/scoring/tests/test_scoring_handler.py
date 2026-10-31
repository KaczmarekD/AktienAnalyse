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

    def record_scoring(self, fetch_run_id, df_all, scored, cfg, profile=None):
        if self.error:
            raise self.error
        self.calls.append(
            {
                "fetch_run_id": fetch_run_id,
                "df_all": df_all,
                "scored": scored,
                "cfg": cfg,
                "profile": profile,
            }
        )
        return 20


@pytest.fixture
def bus() -> InProcessBus:
    return InProcessBus(max_deliver=1)


def _probe(bus: InProcessBus) -> list[Envelope[Any]]:
    seen: list[Envelope[Any]] = []
    bus.subscribe(SCORING_RUN_COMPLETED, "probe-completed", seen.append)
    bus.subscribe(RUN_FAILED, "probe-failed", seen.append)
    return seen


def _snapshot(
    bus: InProcessBus, frame: pd.DataFrame, **options: bool
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
    assert set(call["df_all"]["symbol"]) == set(mock_universe_df["symbol"])
    assert list(call["scored"]["symbol"]) == list(expected["symbol"])


def test_weights_come_from_the_config(bus, mock_universe_df):
    _subscribe(bus, FakeStore(), ScoringConfig(value_weight=0.5, quality_weight=0.5))
    seen = _probe(bus)
    _snapshot(bus, mock_universe_df)
    assert (seen[0].data.value_weight, seen[0].data.quality_weight) == (0.5, 0.5)


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
