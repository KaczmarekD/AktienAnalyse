"""Einordnung ins Referenzuniversum (D4.1, ANA-01 bis 03; docs/architecture/depot/analyse.md).

Ein Depot mit zehn Aktien taugt nicht als Vergleichsgruppe. Deshalb bleibt DAX/MDAX das
Referenzuniversum, und jede andere Aktie bekommt den Perzentilrang, den sie hätte, wenn man sie
**allein** dem Referenzuniversum hinzufügte. Die Ränge der Referenztitel ändern sich dadurch nicht,
Ranking, CSV und Mail bleiben gleich.

- Je Faktor gelten Richtung und Ausschlüsse wie in ``score()``: negative Multiples zählen nicht,
  die Branchenregel nimmt dieselben Kennzahlen heraus.
- Value-, Quality- und Composite-Score, Mindestanteil der Faktoren und Value-Trap folgen denselben
  Regeln und Gewichten. Der Composite entsteht nur aus beiden Teilscores (M1); ohne nennt
  ``reason`` den Grund (``no_value``, ``no_quality``, ``no_data``).
- Der Größenfilter gilt hier nicht (ANA-03): Eine Aktie im Depot wird auch eingeordnet, wenn sie
  zu klein für das Ranking ist.
- ``composite_percentile``: der Rang des Composite unter allen Referenztiteln mit Composite, für
  einen Kandidaten wieder „Referenz plus dieser eine“. Der Composite selbst streut eng um 0,5.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

from .scoring import (
    NON_MULTIPLE_FACTORS,
    _composite_mean,
    _industry_rule_inputs,
    _momentum_trap,
    _percentile_rank,
)

if TYPE_CHECKING:
    from .scoring import ScoringConfig

# Spalten der Ausgabe außer den Faktor-Rängen (``rank_<name>``)
PLACEMENT_COLUMNS = (
    "symbol",
    "value_score",
    "quality_score",
    "composite_score",
    "composite_percentile",
    "value_trap_flag",
    "value_trap_reason",
    "industry_rule",
    "reason",
)


def composite_percentiles(composite: pd.Series) -> pd.Series:
    """Perzentilrang des Composite unter allen Titeln mit Composite; ohne bleibt NaN."""
    values = composite.astype(float)
    valid = values[np.isfinite(values)]
    out = pd.Series(np.nan, index=composite.index, dtype=float)
    out.loc[valid.index] = valid.rank(pct=True, method="average")
    return out


def _reason(value: float, quality: float) -> str | None:
    if np.isnan(value) and np.isnan(quality):
        return "no_data"
    if np.isnan(value):
        return "no_value"
    if np.isnan(quality):
        return "no_quality"
    return None


def _place_one(
    reference: pd.DataFrame, candidate: pd.Series, cfg: ScoringConfig
) -> dict[str, object]:
    """Ein Kandidat in „Referenz plus dieser eine“; der Kandidat ist die letzte Zeile."""
    combined = pd.concat([reference, candidate.to_frame().T], ignore_index=True)
    ruled, inputs = _industry_rule_inputs(combined, cfg)
    last = combined.index[-1]

    def ranks(factors: dict[str, tuple[str, str]], *, value: bool) -> pd.DataFrame:
        frame = pd.DataFrame(index=combined.index)
        for name, (col, direction) in factors.items():
            if col in inputs.columns:
                drop = (
                    value and cfg.drop_negative_value_metrics and name not in NON_MULTIPLE_FACTORS
                )
                frame[f"rank_{name}"] = _percentile_rank(inputs[col], direction, drop)
        return frame

    value_ranks = ranks(cfg.value_factors, value=True)
    quality_ranks = ranks(cfg.quality_factors, value=False)
    # Nur die Zeile des Kandidaten: Mittel und Mindestanteil wie im Ranking
    value = (
        float(
            _composite_mean(
                value_ranks.loc[[last]], cfg.min_value_factor_share, cfg.min_factor_count
            ).iloc[0]
        )
        if not value_ranks.empty
        else float("nan")
    )
    quality = (
        float(
            _composite_mean(
                quality_ranks.loc[[last]], cfg.min_quality_factor_share, cfg.min_factor_count
            ).iloc[0]
        )
        if not quality_ranks.empty
        else float("nan")
    )
    composite = cfg.value_weight * value + cfg.quality_weight * quality

    reference_composite = reference.get("composite_score")
    percentile = float("nan")
    if not np.isnan(composite) and reference_composite is not None:
        with_candidate = pd.concat(
            [reference_composite.astype(float), pd.Series([composite])], ignore_index=True
        )
        percentile = float(composite_percentiles(with_candidate).iloc[-1])

    quality_trap = (0.0 if np.isnan(value) else value) >= cfg.value_trap_value_threshold and (
        1.0 if np.isnan(quality) else quality
    ) <= cfg.value_trap_quality_threshold
    momentum_rank = (
        _percentile_rank(inputs["momentum_12_1"], "high", drop_non_positive=False)
        if "momentum_12_1" in inputs.columns
        else pd.Series(np.nan, index=combined.index, dtype=float)
    )
    momentum_trap = bool(
        _momentum_trap(
            pd.Series([value], index=[last]),
            momentum_rank.loc[[last]],
            inputs.loc[[last]],
            ruled.loc[[last]],
            cfg,
        ).iloc[0]
    )
    trap_reason = "quality" if quality_trap else ("momentum" if momentum_trap else None)

    row: dict[str, object] = {
        "symbol": candidate.get("symbol"),
        "value_score": value,
        "quality_score": quality,
        "composite_score": composite,
        "composite_percentile": percentile,
        "value_trap_flag": bool(quality_trap or momentum_trap),
        "value_trap_reason": trap_reason,
        "industry_rule": bool(ruled.loc[last]),
        "reason": _reason(value, quality),
    }
    for frame in (value_ranks, quality_ranks):
        row.update(frame.loc[last].astype(float).to_dict())
    return row


def place(reference: pd.DataFrame, candidates: pd.DataFrame, cfg: ScoringConfig) -> pd.DataFrame:
    """Ordnet ``candidates`` einzeln in ``reference`` ein.

    ``reference``: das bewertete Referenzuniversum, die Ausgabe von ``score()`` (Rohwerte und
    Ränge, nur Titel über dem Größenfilter). ``candidates``: flache Zeilen wie die Eingabe von
    ``score()``. Ergebnis: je Kandidat eine Zeile mit ``PLACEMENT_COLUMNS`` und ``rank_<faktor>``,
    in der Reihenfolge der Kandidaten. Ohne Referenz oder Kandidaten leer.
    """
    if reference.empty or candidates.empty:
        return pd.DataFrame(columns=list(PLACEMENT_COLUMNS))
    raw = reference.reindex(columns=candidates.columns.union(reference.columns, sort=False))
    rows = [_place_one(raw, candidate, cfg) for _, candidate in candidates.iterrows()]
    return pd.DataFrame(rows)
