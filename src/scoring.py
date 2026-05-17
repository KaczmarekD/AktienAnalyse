"""Composite Value & Quality Scoring.

Methodik (Cross-Sektional, alle Faktoren werden auf das gefilterte
Universum gerankt):

1. Marktkapitalisierungsfilter ``ScoringConfig.min_market_cap``.
2. Fuer jede Value-Kennzahl Perzentilrang - direction='low' invertiert
   (niedriger Multiple = besser).
3. Quality-Kennzahlen analog, Verschuldungsmetriken invertiert.
4. Composite = ``value_weight * value + quality_weight * quality``.
5. Value-Trap-Flag, wenn Value im oberen
   ``value_trap_value_threshold``-Perzentil und Quality im unteren
   ``value_trap_quality_threshold``-Perzentil.

Robust gegen fehlende Werte: Faktoren, die fuer einen Titel nicht
vorliegen, werden aus dem Mittel ausgenommen (nicht mit 0 bestraft).
Negative Bewertungsmultiplikatoren (Verluste) werden vom Value-Ranking
ausgeschlossen, damit Pleitekandidaten nicht als Schnaeppchen erscheinen.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)


# (column_name, direction). direction='low' bedeutet "niedriger Wert ist besser"
ValueFactor = tuple[str, str]
QualityFactor = tuple[str, str]

DEFAULT_VALUE_FACTORS: dict[str, ValueFactor] = {
    "ev_ebit": ("ev_ebit", "low"),
    "pb": ("pb_ratio", "low"),
    "p_fcf": ("p_fcf", "low"),
    "shareholder_yield": ("shareholder_yield", "high"),
}

DEFAULT_QUALITY_FACTORS: dict[str, QualityFactor] = {
    "roic": ("roic", "high"),
    "fcf_margin": ("fcf_margin", "high"),
    "operating_margin": ("operating_margin", "high"),
    "net_debt_ebitda": ("net_debt_ebitda", "low"),
    "earnings_stability": ("earnings_stability", "high"),
}


@dataclass
class ScoringConfig:
    """Alle frueher hartcodierten Schwellen sind hier zentralisiert."""

    min_market_cap: float = 300_000_000.0
    value_weight: float = 0.6
    quality_weight: float = 0.4

    # Mindestens X von N Faktoren muessen vorliegen, sonst kein Score:
    min_value_factor_share: float = 0.5
    min_quality_factor_share: float = 0.5

    # Value-Trap: oberes Value-Quartil + unteres Quality-Quartil
    value_trap_value_threshold: float = 0.70
    value_trap_quality_threshold: float = 0.30

    drop_negative_value_metrics: bool = True

    value_factors: dict[str, ValueFactor] = field(
        default_factory=lambda: dict(DEFAULT_VALUE_FACTORS),
    )
    quality_factors: dict[str, QualityFactor] = field(
        default_factory=lambda: dict(DEFAULT_QUALITY_FACTORS),
    )


def _percentile_rank(series: pd.Series, direction: str, drop_non_positive: bool) -> pd.Series:
    """Perzentilrang. NaN bleibt NaN. direction='low' -> niedrig wird zu hohem Score."""
    s = series.astype(float)
    valid = s.notna()
    if direction == "low" and drop_non_positive:
        valid = valid & (s > 0)
    ranks = s[valid].rank(pct=True, method="average")
    if direction == "low":
        ranks = 1.0 - ranks
    out = pd.Series(np.nan, index=series.index, dtype=float)
    out.loc[ranks.index] = ranks
    return out


def _composite_mean(rank_df: pd.DataFrame, min_share: float) -> pd.Series:
    """Mittelwert ueber alle vorhandenen Faktor-Ranks (NaN-tolerant)."""
    if rank_df.empty:
        return pd.Series(dtype=float)
    available = rank_df.notna().sum(axis=1)
    min_required = max(2, math.ceil(rank_df.shape[1] * min_share))
    score = rank_df.mean(axis=1, skipna=True)
    score[available < min_required] = np.nan
    return score


def score(df: pd.DataFrame, cfg: ScoringConfig | None = None) -> pd.DataFrame:
    cfg = cfg or ScoringConfig()
    out = df.copy()

    before = len(out)
    mask = out["market_cap"].fillna(0) >= cfg.min_market_cap
    out = out[mask].reset_index(drop=True)
    log.info("Marktkapitalisierungs-Filter: %d -> %d Werte", before, len(out))

    if out.empty:
        return out

    value_ranks = pd.DataFrame(index=out.index)
    for name, (col, direction) in cfg.value_factors.items():
        if col in out.columns:
            value_ranks[f"rank_{name}"] = _percentile_rank(
                out[col],
                direction,
                cfg.drop_negative_value_metrics,
            )

    quality_ranks = pd.DataFrame(index=out.index)
    for name, (col, direction) in cfg.quality_factors.items():
        if col in out.columns:
            quality_ranks[f"rank_{name}"] = _percentile_rank(
                out[col],
                direction,
                drop_non_positive=False,
            )

    out["value_score"] = _composite_mean(value_ranks, cfg.min_value_factor_share)
    out["quality_score"] = _composite_mean(quality_ranks, cfg.min_quality_factor_share)

    v = out["value_score"]
    q = out["quality_score"]
    composite = pd.Series(np.nan, index=out.index, dtype=float)
    both = v.notna() & q.notna()
    composite[both] = cfg.value_weight * v[both] + cfg.quality_weight * q[both]
    only_v = v.notna() & q.isna()
    composite[only_v] = v[only_v]
    only_q = v.isna() & q.notna()
    composite[only_q] = q[only_q]
    out["composite_score"] = composite

    out["value_trap_flag"] = (out["value_score"].fillna(0) >= cfg.value_trap_value_threshold) & (
        out["quality_score"].fillna(1) <= cfg.value_trap_quality_threshold
    )

    out = pd.concat([out, value_ranks, quality_ranks], axis=1)
    out = out.sort_values("composite_score", ascending=False, na_position="last").reset_index(
        drop=True
    )
    out["rank_overall"] = np.arange(1, len(out) + 1)

    log.info(
        "Scoring fertig: %d bewertet, %d mit Value-Trap-Flag",
        int(out["composite_score"].notna().sum()),
        int(out["value_trap_flag"].sum()),
    )
    return out
