"""scoring am Bus: ``marketdata.snapshot.completed`` -> ``scoring.run.completed``.

Ohne bewertbare Titel endet der Run mit ``screening.run.failed`` und ``reason="no_data"``
(kein leeres Ranking). Jeder andere Fehler wird ebenfalls zu ``screening.run.failed``.

Seit D4.1 ordnet er die Aktien der Depots ins Referenzuniversum ein (``place()``): die Abdeckung
(``covered[]``) und die Universumstitel unter dem Größenfilter. Sie gehen als ``placements[]`` mit
dem Event und nach ``scoring.placement``; Ranking, CSV und Mail bleiben gleich. Die Ranking-Zeilen
tragen dazu ISIN und Composite-Perzentil. Ein Fehler beim Einordnen kostet nur die Einordnung.
"""

from __future__ import annotations

import logging
import re
import traceback
from typing import TYPE_CHECKING, Any

import pandas as pd

from va_contracts.base import missing_to_none
from va_contracts.events.v1 import (
    COVERAGE_FETCHED,
    PLACEMENTS_UPDATED,
    REASON_NO_DATA,
    RUN_FAILED,
    SCORING_RUN_COMPLETED,
    SNAPSHOT_COMPLETED,
    FundamentalsV1,
    IdentityV1,
    PlacementsUpdatedV1,
    PlacementV1,
    ProfileRefV1,
    RankingRowV1,
    RunFailedV1,
    ScoringRunCompletedV1,
)
from va_contracts.profile import ProfileParamsV1
from va_contracts.securities import ISIN_PATTERN
from va_platform.bus import follow_up

from ..domain.anchors import add_anchors
from ..domain.placement import composite_percentiles, place
from ..domain.profile import ScoringProfileParams
from ..domain.scoring import ScoringConfig, score

if TYPE_CHECKING:
    from collections.abc import Mapping

    from va_contracts import Envelope
    from va_contracts.events.v1 import CoverageFetchedV1, SnapshotCompletedV1
    from va_platform.bus import EventBus

    from ..application.ports import ProfileSource, ReferenceSource, ScoringStore
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
            # Die Anker (F3.1) kommen nach score() und gehen nicht in den Composite ein
            scored = add_anchors(score(frame, cfg), cfg) if snap.fundamentals else frame.iloc[0:0]
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
            placements = self._placements(snap, frame, scored, cfg)
            try:
                self._store.record_placements(scoring_run_id, placements)
            except Exception:
                log.warning(
                    "Einordnung nicht gespeichert - sie fehlt nur im Speicher", exc_info=True
                )
            scored = scored.assign(
                composite_percentile=composite_percentiles(scored["composite_score"])
            )
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
                # Track G (G3): die Parameter dieses Laufs, fuer Tooltips im UI
                params=_params(cfg),
                ranking=[
                    _ranking_row(row, contracts.get(str(row["symbol"])), snap.isins)
                    for row in scored.to_dict("records")
                ],
                placements=placements,
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

    def _placements(
        self,
        snap: SnapshotCompletedV1,
        frame: pd.DataFrame,
        scored: pd.DataFrame,
        cfg: ScoringConfig,
    ) -> list[PlacementV1]:
        """Abdeckung und Universumstitel unter dem Größenfilter, eingeordnet; wirft nicht."""
        try:
            covered = pd.DataFrame([f.to_flat() for f in snap.covered], columns=_FLAT_COLUMNS)
            below = frame[frame["market_cap"].fillna(0) < cfg.min_market_cap]
            candidates = pd.concat([covered, below], ignore_index=True)
            small = set(below["symbol"])
            sectors = dict(zip(candidates["symbol"], candidates["sector"], strict=True))
            placed = place(scored, candidates, cfg)
        except Exception:
            log.warning(
                "Einordnung der Depot-Aktien fehlgeschlagen - das Ranking bleibt", exc_info=True
            )
            return []
        return _to_placements(
            placed,
            isins=snap.isins,
            instrument_ids=snap.instrument_ids,
            small=small,
            sectors=sectors,
        )

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


def _ranking_row(
    row: Mapping[Any, Any], fundamentals: FundamentalsV1 | None, isins: Mapping[str, str]
) -> RankingRowV1:
    """Eine Zeile des Rankings, seit D4.1 mit ISIN und Composite-Perzentil."""
    ranking = RankingRowV1.from_flat(row, fundamentals=fundamentals)
    # Über den Konstruktor, damit die neuen Felder geprüft werden (model_copy prüft nicht)
    return RankingRowV1(
        **{
            **dict(ranking),
            "isin": _isin(isins, str(row["symbol"])),
            "composite_percentile": missing_to_none(row.get("composite_percentile")),
        }
    )


def _to_placements(
    placed: pd.DataFrame,
    *,
    isins: Mapping[str, str],
    instrument_ids: Mapping[str, int],
    small: set[str],
    sectors: Mapping[str, object],
) -> list[PlacementV1]:
    """Je Zeile von ``place()`` eine Einordnung; eine ungueltige kostet nur sich selbst."""
    placements: list[PlacementV1] = []
    for row in placed.to_dict("records"):
        symbol = str(row["symbol"])
        try:
            placements.append(
                PlacementV1.from_flat(
                    row,
                    isin=_isin(isins, symbol),
                    instrument_id=instrument_ids.get(symbol),
                    below_size_filter=symbol in small,
                    sector=sectors.get(symbol),  # type: ignore[arg-type]
                )
            )
        except ValueError:
            # Lieber einen Titel verlieren als die Einordnung (ValidationError ist ein ValueError)
            log.warning("Einordnung von %s ungueltig - sie fehlt", symbol, exc_info=True)
    return placements


class CoverageFetchedHandler:
    """D4.6: ``marketdata.coverage.fetched`` -> Einordnung gegen den letzten Bewertungslauf ->
    ``scoring.placements.updated``.

    Referenzuniversum und Profil sind die des juengsten Bewertungslaufs (``latest_reference``),
    gespeichert wird in ``scoring.placement`` zu dessen ID. Ranking, CSV und Mail bleiben
    unberuehrt. Ohne Bewertungslauf wartet die Einordnung auf den ersten; ist die Datenbank weg,
    stellt der Bus erneut zu; ein Fehler in der Rechnung kostet nur die Einordnung.
    """

    def __init__(self, bus: EventBus, *, store: ScoringStore, reference: ReferenceSource) -> None:
        self._bus = bus
        self._store = store
        self._reference = reference

    def subscribe(self) -> None:
        self._bus.subscribe(COVERAGE_FETCHED, CONSUMER, self)

    def __call__(self, env: Envelope[CoverageFetchedV1]) -> None:
        data = env.data
        reference = self._reference.latest_reference()
        if reference is None:
            log.info("Noch kein Bewertungslauf - die Einordnung wartet auf den ersten")
            return
        try:
            candidates = pd.DataFrame(
                [f.to_flat() for f in data.fundamentals], columns=_FLAT_COLUMNS
            )
            sectors = dict(zip(candidates["symbol"], candidates["sector"], strict=True))
            placed = place(score(reference.frame, reference.config), candidates, reference.config)
        except Exception:
            log.warning(
                "Sofortige Einordnung fehlgeschlagen - sie kommt mit dem Wochenlauf", exc_info=True
            )
            return
        placements = _to_placements(
            placed, isins=data.isins, instrument_ids={}, small=set(), sectors=sectors
        )
        if not placements:
            return
        self._store.record_placements(reference.scoring_run_id, placements)
        updated = PlacementsUpdatedV1(
            scoring_run_id=reference.scoring_run_id, as_of=data.as_of, placements=placements
        )
        self._bus.publish(follow_up(env, PLACEMENTS_UPDATED, updated, source=SOURCE))


def _isin(isins: Mapping[str, str], symbol: str) -> str | None:
    """Die ISIN aus dem Abruf, wenn sie die Form hat. ``isins`` prüft der Snapshot nicht; eine
    kaputte ISIN aus einer Quelle soll nicht den Lauf kosten, nur die ISIN dieser Zeile."""
    isin = isins.get(symbol)
    if isin is None or re.fullmatch(ISIN_PATTERN, isin):
        return isin
    log.warning("ISIN von %s hat nicht die Form einer ISIN - sie fehlt in der Zeile", symbol)
    return None


def _profile_ref(ref: ProfileVersionRef | None) -> ProfileRefV1 | None:
    if ref is None:
        return None
    return ProfileRefV1(profile_id=ref.profile_id, version=ref.version, name=ref.name)


def _params(cfg: ScoringConfig) -> ProfileParamsV1:
    """Die Parameter des Laufs als Vertrag, gleich ob aus einem Profil oder aus den ENV-Werten."""
    return ProfileParamsV1.model_validate(ScoringProfileParams.from_config(cfg).model_dump())
