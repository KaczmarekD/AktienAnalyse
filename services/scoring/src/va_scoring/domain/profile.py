"""Scoring-Profile (P2b.1, ADR-0009): die Parameter des Scorings, versioniert in der Datenbank.

Jedes Speichern erzeugt eine neue, unveraenderliche Version. Aktiv ist genau eine. Die heutigen
ENV-Werte legen einmalig das Profil "Standard" an. Das Pydantic-Modell mit den Regeln folgt in
P2b.2 (docs/architecture/scoring-profile.md), bis P2b.3 rechnet das Scoring weiter mit
``ScoringConfig``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .scoring import ScoringConfig

DEFAULT_PROFILE_NAME = "Standard"


@dataclass(frozen=True)
class ProfileVersionRef:
    """Eine gespeicherte Version eines Profils mit ihren Parametern."""

    profile_id: int
    name: str
    version: int
    params: dict[str, Any]

    @property
    def label(self) -> str:
        return f"{self.name} v{self.version}"


def profile_params(cfg: ScoringConfig) -> dict[str, Any]:
    """Die Parameter eines Profils aus einer ``ScoringConfig``, als reines JSON.

    Die Faktoren stehen nur mit ihrem Schluessel drin: Katalog und Richtung bleiben im Code.
    ``quality_weight`` fehlt, es ist ``1 - value_weight``. ``min_factor_count`` steht mit drin,
    damit ein Profil das Scoring vollstaendig beschreibt, auch wenn das UI es nicht aendert.
    """
    return {
        "value_weight": float(cfg.value_weight),
        "min_market_cap": float(cfg.min_market_cap),
        "min_value_factor_share": float(cfg.min_value_factor_share),
        "min_quality_factor_share": float(cfg.min_quality_factor_share),
        "min_factor_count": int(cfg.min_factor_count),
        "value_trap_value_threshold": float(cfg.value_trap_value_threshold),
        "value_trap_quality_threshold": float(cfg.value_trap_quality_threshold),
        "drop_negative_value_metrics": bool(cfg.drop_negative_value_metrics),
        "value_factors": sorted(cfg.value_factors),
        "quality_factors": sorted(cfg.quality_factors),
    }
