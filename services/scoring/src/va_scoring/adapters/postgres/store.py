"""``ScoringStore`` ueber PostgreSQL (Schema ``scoring``), vorher Teil des BatchRecorders."""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from dataclasses import asdict
from typing import TYPE_CHECKING, Any

import pandas as pd

from va_contracts.events.v1.ranking import ANCHOR_KEYS
from va_platform.db import session_scope
from va_platform.serialization import to_python

from ...application.ports import Reference
from ...domain.profile import DEFAULT_PROFILE_NAME, ScoringProfileParams
from .repository import AnchorRow, FactorScoreRow, ScoreRow, ScoringRepository

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy import Engine

    from va_contracts.events.v1 import PlacementV1

    from ...domain.profile import ProfileVersionRef
    from ...domain.scoring import ScoringConfig

log = logging.getLogger(__name__)

DEFAULT_PROFILE_COMMENT = "Startwerte aus ENV (VALUE_WEIGHT, QUALITY_WEIGHT, MIN_MARKET_CAP)"


class PostgresScoringStore:
    def __init__(self, engine: Engine, *, app_version: str) -> None:
        self._engine = engine
        self._app_version = app_version

    def record_scoring(
        self,
        fetch_run_id: int,
        df_all: pd.DataFrame,
        scored: pd.DataFrame,
        cfg: ScoringConfig,
        profile: ProfileVersionRef | None = None,
        instrument_ids: Mapping[str, int] | None = None,
    ) -> int:
        """Speichert Scores fuer *alle* Titel - gefilterte mit ``passed_filter=False``.

        ``instrument_ids`` kommen seit P5.3 mit dem Snapshot-Event; ohne sie (Batch, alte Events)
        liest der Speicher sie aus ``market_data.instrument``, was die Rolle von scoring nicht darf.
        """
        with session_scope(self._engine) as s:
            repo = ScoringRepository(s)
            symbols = scoring_symbols(df_all, scored)
            ids = (
                _known_ids(instrument_ids, symbols)
                if instrument_ids
                else repo.get_instrument_ids(symbols)
            )
            scoring_run_id = repo.write_scoring_run(
                fetch_run_id=fetch_run_id,
                config=asdict(cfg),
                app_version=self._app_version,
                profile_id=None if profile is None else profile.profile_id,
                profile_version=None if profile is None else profile.version,
            )
            repo.write_score_results(scoring_run_id, score_rows(df_all, scored, ids))
            repo.write_factor_scores(scoring_run_id, factor_rows(scored, ids, cfg))
            repo.write_anchor_values(scoring_run_id, anchor_rows(scored, ids))
            # P5.1a: eigene Kopie der Eingangsdaten fuer die Vorschau
            repo.write_input_snapshot(fetch_run_id, input_rows(df_all))
            return scoring_run_id

    def record_placements(self, scoring_run_id: int, placements: Sequence[PlacementV1]) -> None:
        """D4.1: die Einordnungen der Depot-Aktien zu einem Bewertungslauf."""
        if not placements:
            return
        with session_scope(self._engine) as s:
            ScoringRepository(s).write_placements(
                scoring_run_id, [placement.model_dump() for placement in placements]
            )

    def latest_reference(self) -> Reference | None:
        """D4.6: der juengste Bewertungslauf (ohne Rescores) mit Eingangsdaten und Profil."""
        with session_scope(self._engine) as s:
            repo = ScoringRepository(s)
            run = repo.get_latest_scoring_run()
            if run is None or run.fetch_run_id is None or run.profile_id is None:
                return None
            version = repo.get_profile_version(run.profile_id, run.profile_version or 0)
            frame = repo.get_input_frame(run.fetch_run_id)
        if version is None or frame.empty:
            return None
        config = ScoringProfileParams.model_validate(version.params).to_config()
        return Reference(run.id, frame, config)

    def ensure_default_profile(self, params: Mapping[str, Any]) -> ProfileVersionRef:
        """Legt "Standard" einmalig an (ENV nur als Startwerte), liefert die aktive Version."""
        with session_scope(self._engine) as s:
            active, created = ScoringRepository(s).ensure_profile(
                DEFAULT_PROFILE_NAME, params, comment=DEFAULT_PROFILE_COMMENT
            )
        # Nur das Anlegen ist eine Meldung; mit welchem Profil gerechnet wird, meldet der Handler
        if created:
            log.info(
                "Profil %s aus den ENV-Werten angelegt (aktiv: %s)",
                DEFAULT_PROFILE_NAME,
                active.label,
            )
        else:
            log.debug("Aktives Scoring-Profil: %s", active.label)
        return active


def _known_ids(instrument_ids: Mapping[str, int], symbols: list[str]) -> dict[str, int]:
    missing = [s for s in symbols if s not in instrument_ids]
    if missing:
        msg = f"IDs fehlen im Snapshot-Event: {', '.join(missing)}"
        raise LookupError(msg)
    return {s: instrument_ids[s] for s in symbols}


def input_rows(df_all: pd.DataFrame) -> list[dict[str, Any]]:
    """Die flachen Zeilen als JSON: NaN wird null, Zeitpunkte ISO-Text (P5.1a)."""
    if df_all.empty:
        return []
    return json.loads(df_all.to_json(orient="records", date_format="iso"))


def scoring_symbols(df_all: pd.DataFrame, scored: pd.DataFrame) -> list[str]:
    """Alle Titel eines Bewertungslaufs, ohne Doppelte, in der Reihenfolge des Snapshots."""
    return list(dict.fromkeys([*_symbols(df_all), *_symbols(scored)]))


def score_rows(
    df_all: pd.DataFrame, scored: pd.DataFrame, ids: Mapping[str, int]
) -> list[ScoreRow]:
    """Eine Zeile je Titel: bewertete mit ihren Scores, am Groessenfilter gescheiterte mit
    ``passed_filter=False``. Die Replay-Regression bildet ihre Zeilen genauso."""
    results = [_score_row(ids[str(r["symbol"])], r) for r in scored.to_dict("records")]
    passed = set(_symbols(scored))
    results += [
        ScoreRow(ids[sym], False, None, None, None, None, None)
        for sym in dict.fromkeys(_symbols(df_all))
        if sym not in passed
    ]
    return results


def anchor_rows(scored: pd.DataFrame, ids: Mapping[str, int]) -> list[AnchorRow]:
    """Die Anker (F3.1) im Long-Format, nur Werte, die es gibt."""
    rows: list[AnchorRow] = []
    present = [key for key in ANCHOR_KEYS if key in scored.columns]
    for record in scored.to_dict("records"):
        for key in present:
            value = to_python(record.get(key))
            if value is not None:
                rows.append(AnchorRow(ids[str(record["symbol"])], key, float(value)))
    return rows


def _symbols(df: pd.DataFrame) -> list[str]:
    return [str(s) for s in df.get("symbol", pd.Series(dtype=str)).dropna()]


def _score_row(instrument_id: int, row: Mapping[Any, Any]) -> ScoreRow:
    flag = to_python(row.get("value_trap_flag"))
    rank = to_python(row.get("rank_overall"))
    return ScoreRow(
        instrument_id=instrument_id,
        passed_filter=True,
        value_score=to_python(row.get("value_score")),
        quality_score=to_python(row.get("quality_score")),
        composite_score=to_python(row.get("composite_score")),
        value_trap_flag=None if flag is None else bool(flag),
        rank_overall=None if rank is None else int(rank),
        value_trap_reason=to_python(row.get("value_trap_reason")),
    )


def factor_rows(
    scored: pd.DataFrame, ids: Mapping[str, int], cfg: ScoringConfig
) -> list[FactorScoreRow]:
    """Rohwert und Perzentilrang je Titel und Faktor; Faktoren ohne beides fehlen."""
    factors = [("value", k, v) for k, v in cfg.value_factors.items()]
    factors += [("quality", k, v) for k, v in cfg.quality_factors.items()]
    rows: list[FactorScoreRow] = []
    for record in scored.to_dict("records"):
        for category, key, (column, direction) in factors:
            raw = to_python(record.get(column))
            rank = to_python(record.get(f"rank_{key}"))
            if raw is None and rank is None:
                continue
            rows.append(
                FactorScoreRow(
                    ids[str(record["symbol"])], key, category, column, direction, raw, rank
                )
            )
    return rows
