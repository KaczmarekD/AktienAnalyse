"""Zugriffe auf ``scoring``: Bewertungslaeufe, Ergebnisse und Faktor-Raenge."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

import pandas as pd
from sqlalchemy import insert, select

from ..models import FactorScore, Instrument, ScoreResult, ScoringRun
from ..serialization import json_safe, to_python

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


@dataclass(frozen=True)
class ScoreRow:
    instrument_id: int
    passed_filter: bool
    value_score: float | None
    quality_score: float | None
    composite_score: float | None
    value_trap_flag: bool | None
    rank_overall: int | None


@dataclass(frozen=True)
class FactorScoreRow:
    instrument_id: int
    factor_key: str
    category: str
    source_column: str
    direction: str
    raw_value: float | None
    percentile_rank: float | None


def config_hash(config: dict[str, Any] | None) -> str | None:
    if config is None:
        return None
    canonical = json.dumps(json_safe(config), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class ScoringRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    # --- write -------------------------------------------------------------

    def write_scoring_run(
        self,
        *,
        fetch_run_id: int | None,
        config: dict[str, Any] | None,
        app_version: str,
        origin: str = "live",
        note: str | None = None,
        created_at: datetime | None = None,
    ) -> int:
        safe_config = json_safe(config) if config is not None else None
        values: dict[str, Any] = {
            "fetch_run_id": fetch_run_id,
            "origin": origin,
            "config": safe_config,
            "config_hash": config_hash(safe_config),
            "app_version": app_version,
            "note": note,
        }
        if created_at is not None:
            values["created_at"] = created_at
        stmt = insert(ScoringRun).values(**values).returning(ScoringRun.id)
        return self.session.execute(stmt).scalar_one()

    def write_score_results(self, scoring_run_id: int, rows: Sequence[ScoreRow]) -> None:
        if rows:
            self.session.execute(
                insert(ScoreResult),
                [{"scoring_run_id": scoring_run_id, **_clean(asdict(r))} for r in rows],
            )

    def write_factor_scores(self, scoring_run_id: int, rows: Sequence[FactorScoreRow]) -> None:
        if rows:
            self.session.execute(
                insert(FactorScore),
                [{"scoring_run_id": scoring_run_id, **_clean(asdict(r))} for r in rows],
            )

    # --- get ---------------------------------------------------------------

    def get_scoring_run(self, scoring_run_id: int) -> ScoringRun | None:
        return self.session.get(ScoringRun, scoring_run_id)

    def get_scores_df(self, scoring_run_id: int) -> pd.DataFrame:
        columns = [
            "passed_filter",
            "value_score",
            "quality_score",
            "composite_score",
            "value_trap_flag",
            "rank_overall",
        ]
        stmt = (
            select(Instrument.symbol, *(getattr(ScoreResult, c) for c in columns))
            .join(Instrument, Instrument.id == ScoreResult.instrument_id)
            .where(ScoreResult.scoring_run_id == scoring_run_id)
            .order_by(ScoreResult.rank_overall.asc().nulls_last(), Instrument.symbol)
        )
        return _frame(self.session, stmt, ["symbol", *columns])

    def get_factor_scores_df(self, scoring_run_id: int) -> pd.DataFrame:
        columns = [
            "factor_key",
            "category",
            "source_column",
            "direction",
            "raw_value",
            "percentile_rank",
        ]
        stmt = (
            select(Instrument.symbol, *(getattr(FactorScore, c) for c in columns))
            .join(Instrument, Instrument.id == FactorScore.instrument_id)
            .where(FactorScore.scoring_run_id == scoring_run_id)
            .order_by(Instrument.symbol, FactorScore.factor_key)
        )
        return _frame(self.session, stmt, ["symbol", *columns])

    def get_score_history(self, symbol: str) -> pd.DataFrame:
        columns = [
            "passed_filter",
            "value_score",
            "quality_score",
            "composite_score",
            "value_trap_flag",
            "rank_overall",
        ]
        stmt = (
            select(
                ScoringRun.id,
                ScoringRun.created_at,
                ScoringRun.origin,
                *(getattr(ScoreResult, c) for c in columns),
            )
            .join(ScoreResult, ScoreResult.scoring_run_id == ScoringRun.id)
            .join(Instrument, Instrument.id == ScoreResult.instrument_id)
            .where(Instrument.symbol == symbol)
            .order_by(ScoringRun.created_at, ScoringRun.id)
        )
        return _frame(self.session, stmt, ["scoring_run_id", "created_at", "origin", *columns])


def _clean(row: dict[str, Any]) -> dict[str, Any]:
    return {k: to_python(v) for k, v in row.items()}


def _frame(session: Session, stmt: Any, columns: list[str]) -> pd.DataFrame:
    return pd.DataFrame([tuple(r) for r in session.execute(stmt).all()], columns=columns)
