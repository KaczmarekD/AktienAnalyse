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

Branchenregel (F2.4, ADR-0011 Punkt 3, nur mit ``industry_rules``): Bei Banken, Versicherern,
"Capital Markets" und Immobilien sagen EV-, FCF- und Margen-Kennzahlen nichts aus. Sie fallen
vor dem Ranking aus dem Querschnitt; die Titel landen meist unter dem Mindestanteil und ohne
Composite. Alle Raenge bleiben global, innerhalb einer Branche wird nicht gerankt.

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

from va_contracts.profile import DEFAULT_INDUSTRY_PREFIXES

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


# Faktoren, die die Branchenregel ausschliesst (ADR-0011, Punkt 3). F2.1 ergaenzt F-Score,
# Accruals und CFO/Bilanzsumme.
INDUSTRY_RULE_EXCLUDED: frozenset[str] = frozenset(
    {"ev_ebit", "p_fcf", "fcf_margin", "net_debt_ebitda", "operating_margin", "roic"}
)


def industry_rule_applies(industry: object, prefixes: tuple[str, ...]) -> bool:
    """Faellt eine Branche (Yahoo-``industry``) unter die Branchenregel?"""
    return isinstance(industry, str) and industry.startswith(prefixes) and bool(prefixes)


@dataclass
class ScoringConfig:
    """Alle frueher hartcodierten Schwellen sind hier zentralisiert."""

    min_market_cap: float = 300_000_000.0
    value_weight: float = 0.6
    quality_weight: float = 0.4

    # Mindestens X von N Faktoren muessen vorliegen, sonst kein Score:
    min_value_factor_share: float = 0.5
    min_quality_factor_share: float = 0.5
    # ... und je Gruppe mindestens so viele, egal wie klein der Anteil ist
    min_factor_count: int = 2

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

    # Branchenregel (F2.4) und die Parameter des gerechtfertigten KBV im Abschnitt "Finanzwerte"
    industry_rules: bool = False
    industry_prefixes: tuple[str, ...] = DEFAULT_INDUSTRY_PREFIXES
    cost_of_capital: float = 0.08
    terminal_growth: float = 0.02


def _percentile_rank(series: pd.Series, direction: str, drop_non_positive: bool) -> pd.Series:
    """Perzentilrang. NaN bleibt NaN. direction='low' -> niedrig wird zu hohem Score."""
    s = series.astype(float)
    # +/-inf ist kein Messwert (Ueberlauf) - wie NaN nicht ranken, egal woher es kommt
    valid = np.isfinite(s)
    if direction == "low" and drop_non_positive:
        valid = valid & (s > 0)
    ranks = s[valid].rank(pct=True, method="average")
    if direction == "low":
        ranks = 1.0 - ranks
    out = pd.Series(np.nan, index=series.index, dtype=float)
    out.loc[ranks.index] = ranks
    return out


def _composite_mean(rank_df: pd.DataFrame, min_share: float, min_count: int) -> pd.Series:
    """Mittelwert ueber alle vorhandenen Faktor-Ranks (NaN-tolerant).

    Ein Score entsteht nur mit genug Faktoren: Anteil ``min_share`` und mindestens
    ``min_count`` Stueck.
    """
    if rank_df.empty:
        return pd.Series(dtype=float)
    available = rank_df.notna().sum(axis=1)
    min_required = max(min_count, math.ceil(rank_df.shape[1] * min_share))
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

    # Gerankt wird auf einer Kopie ohne die Kennzahlen, die die Branchenregel ausschliesst; die
    # Ausgabe behaelt die Rohwerte (CSV, Speicherung)
    ruled, inputs = _industry_rule_inputs(out, cfg)

    value_ranks = pd.DataFrame(index=out.index)
    for name, (col, direction) in cfg.value_factors.items():
        if col in inputs.columns:
            value_ranks[f"rank_{name}"] = _percentile_rank(
                inputs[col],
                direction,
                cfg.drop_negative_value_metrics,
            )

    quality_ranks = pd.DataFrame(index=out.index)
    for name, (col, direction) in cfg.quality_factors.items():
        if col in inputs.columns:
            quality_ranks[f"rank_{name}"] = _percentile_rank(
                inputs[col],
                direction,
                drop_non_positive=False,
            )

    out["value_score"] = _composite_mean(
        value_ranks, cfg.min_value_factor_share, cfg.min_factor_count
    )
    out["quality_score"] = _composite_mean(
        quality_ranks, cfg.min_quality_factor_share, cfg.min_factor_count
    )

    # Nur aus beiden Teilscores (M1): Fehlt einer, gibt es kein Urteil. Sonst stuende ein
    # Titel ohne Quality-Daten besser da als einer mit mittelmaessiger Quality.
    v = out["value_score"]
    q = out["quality_score"]
    out["composite_score"] = cfg.value_weight * v + cfg.quality_weight * q

    out["value_trap_flag"] = (out["value_score"].fillna(0) >= cfg.value_trap_value_threshold) & (
        out["quality_score"].fillna(1) <= cfg.value_trap_quality_threshold
    )

    out["industry_rule"] = ruled
    out = pd.concat([out, value_ranks, quality_ranks], axis=1)
    # Feste Reihenfolge: bei gleichem oder fehlendem Composite nach Symbol. Sonst hinge der
    # Rang von der Reihenfolge der Eingabe ab (Abruf: Universum, Wiederverwendung: DB).
    out = out.sort_values(
        ["composite_score", "symbol"], ascending=[False, True], na_position="last", kind="stable"
    ).reset_index(drop=True)
    out["rank_overall"] = np.arange(1, len(out) + 1)

    if cfg.industry_rules:
        log.info("Branchenregel: %d Titel ohne EV-, FCF- und Margen-Kennzahlen", int(ruled.sum()))
    log.info(
        "Scoring fertig: %d bewertet, %d mit Value-Trap-Flag",
        int(out["composite_score"].notna().sum()),
        int(out["value_trap_flag"].sum()),
    )
    return out


def _industry_rule_inputs(out: pd.DataFrame, cfg: ScoringConfig) -> tuple[pd.Series, pd.DataFrame]:
    """Maske der Titel unter der Branchenregel und die Eingabe fuers Ranking.

    Die Eingabe ist eine Kopie, in der bei diesen Titeln die ausgeschlossenen Kennzahlen fehlen.
    Ohne ``industry_rules`` ist die Maske leer und die Eingabe ``out`` selbst.
    """
    if not cfg.industry_rules or "industry" not in out.columns:
        return pd.Series(False, index=out.index, dtype=bool), out
    mask = out["industry"].map(lambda value: industry_rule_applies(value, cfg.industry_prefixes))
    mask = mask.astype(bool)
    inputs = out.copy()
    catalog = cfg.value_factors | cfg.quality_factors
    for key, (col, _direction) in catalog.items():
        if key in INDUSTRY_RULE_EXCLUDED and col in inputs.columns:
            inputs[col] = inputs[col].astype(float).mask(mask)
    return mask, inputs
