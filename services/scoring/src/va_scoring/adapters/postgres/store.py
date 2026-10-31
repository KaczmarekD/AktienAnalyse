"""``ScoringStore`` ueber PostgreSQL (Schema ``scoring``), vorher Teil des BatchRecorders."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import asdict
from typing import TYPE_CHECKING, Any

import pandas as pd

from va_platform.db import session_scope
from va_platform.serialization import to_python

from ...domain.profile import DEFAULT_PROFILE_NAME
from .repository import FactorScoreRow, ScoreRow, ScoringRepository

if TYPE_CHECKING:
    from sqlalchemy import Engine

    from ...domain.profile import ProfileVersionRef
    from ...domain.scoring import ScoringConfig

log = logging.getLogger(__name__)

DEFAULT_PROFILE_COMMENT = "Startwerte aus ENV (VALUE_WEIGHT, QUALITY_WEIGHT, MIN_MARKET_CAP)"


class PostgresScoringStore:
    def __init__(self, engine: Engine, *, app_version: str) -> None:
        self._engine = engine
        self._app_version = app_version

    def record_scoring(
        self, fetch_run_id: int, df_all: pd.DataFrame, scored: pd.DataFrame, cfg: ScoringConfig
    ) -> int:
        """Speichert Scores fuer *alle* Titel - gefilterte mit ``passed_filter=False``."""
        with session_scope(self._engine) as s:
            repo = ScoringRepository(s)
            ids = repo.get_instrument_ids(scoring_symbols(df_all, scored))
            scoring_run_id = repo.write_scoring_run(
                fetch_run_id=fetch_run_id,
                config=asdict(cfg),
                app_version=self._app_version,
            )
            repo.write_score_results(scoring_run_id, score_rows(df_all, scored, ids))
            repo.write_factor_scores(scoring_run_id, factor_rows(scored, ids, cfg))
            return scoring_run_id

    def ensure_default_profile(self, params: Mapping[str, Any]) -> ProfileVersionRef:
        """Legt "Standard" einmalig an (ENV nur als Startwerte), liefert die aktive Version."""
        with session_scope(self._engine) as s:
            active, created = ScoringRepository(s).ensure_profile(
                DEFAULT_PROFILE_NAME, params, comment=DEFAULT_PROFILE_COMMENT
            )
        # Bis P2b.3 rechnet das Scoring noch mit den ENV-Werten: nur das Anlegen ist eine Meldung
        if created:
            log.info(
                "Profil %s aus den ENV-Werten angelegt (aktiv: %s)",
                DEFAULT_PROFILE_NAME,
                active.label,
            )
        else:
            log.debug("Aktives Scoring-Profil: %s", active.label)
        return active


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
