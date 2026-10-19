"""``ScoringStore`` ueber PostgreSQL (Schema ``scoring``), vorher Teil des BatchRecorders."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict
from typing import TYPE_CHECKING, Any

import pandas as pd

from va_platform.db import session_scope
from va_platform.serialization import to_python

from .repository import FactorScoreRow, ScoreRow, ScoringRepository

if TYPE_CHECKING:
    from sqlalchemy import Engine

    from ...domain.scoring import ScoringConfig


class PostgresScoringStore:
    def __init__(self, engine: Engine, *, app_version: str) -> None:
        self._engine = engine
        self._app_version = app_version

    def record_scoring(
        self, fetch_run_id: int, df_all: pd.DataFrame, scored: pd.DataFrame, cfg: ScoringConfig
    ) -> int:
        """Speichert Scores fuer *alle* Titel - gefilterte mit ``passed_filter=False``."""
        symbols = [str(s) for s in df_all.get("symbol", pd.Series(dtype=str)).dropna()]
        scored_symbols = [str(s) for s in scored.get("symbol", pd.Series(dtype=str)).dropna()]
        with session_scope(self._engine) as s:
            repo = ScoringRepository(s)
            ids = repo.get_instrument_ids([*symbols, *scored_symbols])
            scoring_run_id = repo.write_scoring_run(
                fetch_run_id=fetch_run_id,
                config=asdict(cfg),
                app_version=self._app_version,
            )
            results = [_score_row(ids[str(r["symbol"])], r) for r in scored.to_dict("records")]
            passed = set(scored_symbols)
            results += [
                ScoreRow(ids[sym], False, None, None, None, None, None)
                for sym in dict.fromkeys(symbols)
                if sym not in passed
            ]
            repo.write_score_results(scoring_run_id, results)
            repo.write_factor_scores(scoring_run_id, _factor_rows(scored, ids, cfg))
            return scoring_run_id


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


def _factor_rows(
    scored: pd.DataFrame, ids: dict[str, int], cfg: ScoringConfig
) -> list[FactorScoreRow]:
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
