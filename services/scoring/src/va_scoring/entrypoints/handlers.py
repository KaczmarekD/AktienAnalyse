"""scoring am Bus: ``marketdata.snapshot.completed`` -> ``scoring.run.completed``.

Ohne bewertbare Titel endet der Run mit ``screening.run.failed`` und ``reason="no_data"``
(kein leeres Ranking). Jeder andere Fehler wird ebenfalls zu ``screening.run.failed``.
"""

from __future__ import annotations

import logging
import traceback
from typing import TYPE_CHECKING

import pandas as pd

from va_contracts.events.v1 import (
    REASON_NO_DATA,
    RUN_FAILED,
    SCORING_RUN_COMPLETED,
    SNAPSHOT_COMPLETED,
    FundamentalsV1,
    IdentityV1,
    ProfileRefV1,
    RankingRowV1,
    RunFailedV1,
    ScoringRunCompletedV1,
)
from va_platform.bus import follow_up

from ..domain.scoring import score

if TYPE_CHECKING:
    from va_contracts import Envelope
    from va_contracts.events.v1 import SnapshotCompletedV1
    from va_platform.bus import EventBus

    from ..application.ports import ProfileSource, ScoringStore
    from ..domain.profile import ProfileVersionRef

log = logging.getLogger(__name__)

CONSUMER = "scoring"
SOURCE = "va/scoring"

# Spalten eines leeren Snapshots, damit Speicher und score() dieselbe Form sehen
_FLAT_COLUMNS = list(FundamentalsV1(identity=IdentityV1(symbol="", name="", index="")).to_flat())


class SnapshotCompletedHandler:
    def __init__(self, bus: EventBus, *, store: ScoringStore, profile: ProfileSource) -> None:
        self._bus = bus
        self._store = store
        self._profile = profile

    def subscribe(self) -> None:
        self._bus.subscribe(SNAPSHOT_COMPLETED, CONSUMER, self)

    def __call__(self, env: Envelope[SnapshotCompletedV1]) -> None:
        snap = env.data
        scoring_run_id: int | None = None
        try:
            # Das aktive Profil gilt fuer diesen Lauf (P2b.3); ohne Profil keine Bewertung
            active = self._profile.active()
            cfg = active.config
            if active.label is not None:
                log.info("Scoring mit Profil %s", active.label)
            frame = pd.DataFrame([f.to_flat() for f in snap.fundamentals], columns=_FLAT_COLUMNS)
            scored = score(frame, cfg) if snap.fundamentals else frame.iloc[0:0]
            scoring_run_id = self._store.record_scoring(
                snap.fetch_run_id,
                frame,
                scored,
                cfg,
                profile=active.ref,
                instrument_ids=snap.instrument_ids or None,  # P5.3, sonst liest der Speicher
            )
            if scored.empty or int(scored["composite_score"].notna().sum()) == 0:
                log.error("Keine bewertbaren Datenpunkte - Abbruch.")
                self._fail(env, REASON_NO_DATA, scoring_run_id=scoring_run_id)
                return
            contracts = {f.symbol: f for f in snap.fundamentals}
            completed = ScoringRunCompletedV1(
                run_id=snap.run_id,
                trigger=snap.trigger,
                options=snap.options,
                scoring_run_id=scoring_run_id,
                fetch_run_id=snap.fetch_run_id,
                as_of=snap.as_of,
                universe=snap.universe,
                value_weight=cfg.value_weight,
                quality_weight=cfg.quality_weight,
                profile=_profile_ref(active.ref),
                ranking=[
                    RankingRowV1.from_flat(row, fundamentals=contracts.get(str(row["symbol"])))
                    for row in scored.to_dict("records")
                ],
            )
        except Exception as e:
            log.exception("Scoring fehlgeschlagen")
            self._fail(
                env,
                str(e) or type(e).__name__,
                detail=traceback.format_exc(),
                scoring_run_id=scoring_run_id,
            )
            return
        self._bus.publish(follow_up(env, SCORING_RUN_COMPLETED, completed, source=SOURCE))

    def _fail(
        self,
        env: Envelope[SnapshotCompletedV1],
        reason: str,
        *,
        scoring_run_id: int | None,
        detail: str | None = None,
    ) -> None:
        snap = env.data
        failed = RunFailedV1(
            run_id=snap.run_id,
            trigger=snap.trigger,
            options=snap.options,
            stage="scoring",
            reason=reason,
            detail=detail,
            scoring_run_id=scoring_run_id,
        )
        self._bus.publish(follow_up(env, RUN_FAILED, failed, source=SOURCE))


def _profile_ref(ref: ProfileVersionRef | None) -> ProfileRefV1 | None:
    if ref is None:
        return None
    return ProfileRefV1(profile_id=ref.profile_id, version=ref.version, name=ref.name)
