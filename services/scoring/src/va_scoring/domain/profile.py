"""Scoring-Profile (ADR-0009): die Parameter des Scorings, versioniert in der Datenbank.

Jedes Speichern erzeugt eine neue, unveraenderliche Version. Aktiv ist genau eine. Die heutigen
ENV-Werte legen einmalig das Profil "Standard" an (P2b.1). ``ScoringProfileParams`` prueft die
Parameter und bildet sie auf ``score()`` ab (P2b.2). Bis P2b.3 rechnet das Scoring noch mit der
``ScoringConfig`` aus ENV. Details: docs/architecture/scoring-profile.md.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Self, get_args

from pydantic import BaseModel, ConfigDict, Field, field_serializer, model_validator

from .scoring import DEFAULT_QUALITY_FACTORS, DEFAULT_VALUE_FACTORS, ScoringConfig

DEFAULT_PROFILE_NAME = "Standard"

# Der Faktor-Katalog als Schluessel. Spalte und Richtung stehen in DEFAULT_*_FACTORS und sind im
# UI nicht aenderbar; ein Test haelt beide Listen gleich.
ValueFactorKey = Literal["ev_ebit", "pb", "p_fcf", "shareholder_yield"]
QualityFactorKey = Literal[
    "roic", "fcf_margin", "operating_margin", "net_debt_ebitda", "earnings_stability"
]

# _composite_mean braucht je Gruppe mindestens zwei vorhandene Faktoren
MIN_ACTIVE_FACTORS = 2


class ScoringProfileParams(BaseModel):
    """Die Parameter eines Profils mit ihren Regeln, an genau einer Stelle (ADR-0009).

    Die Grenzen stehen am Feld und landen so spaeter in OpenAPI und im Formular. Regeln ueber
    mehrere Felder stehen im Validator. Unbekannte Felder sind ein Fehler: Ein Tippfehler in
    gespeicherten params darf nicht still wegfallen.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    value_weight: float = Field(default=0.6, ge=0, le=1)
    min_market_cap: float = Field(default=300_000_000.0, ge=0)
    min_value_factor_share: float = Field(default=0.5, ge=0, le=1)
    min_quality_factor_share: float = Field(default=0.5, ge=0, le=1)
    # Im UI nicht aenderbar; steht drin, damit ein Profil das Scoring vollstaendig beschreibt
    min_factor_count: int = Field(default=2, ge=1)
    value_trap_value_threshold: float = Field(default=0.70, ge=0, le=1)
    value_trap_quality_threshold: float = Field(default=0.30, ge=0, le=1)
    drop_negative_value_metrics: bool = True
    value_factors: frozenset[ValueFactorKey] = Field(
        default_factory=lambda: frozenset(get_args(ValueFactorKey))
    )
    quality_factors: frozenset[QualityFactorKey] = Field(
        default_factory=lambda: frozenset(get_args(QualityFactorKey))
    )

    @model_validator(mode="after")
    def _enough_factors(self) -> Self:
        for group, factors in (
            ("value_factors", self.value_factors),
            ("quality_factors", self.quality_factors),
        ):
            if len(factors) < MIN_ACTIVE_FACTORS:
                msg = f"{group}: mindestens {MIN_ACTIVE_FACTORS} aktive Faktoren"
                raise ValueError(msg)
            if len(factors) < self.min_factor_count:
                msg = (
                    f"{group}: {len(factors)} aktive Faktoren, aber min_factor_count ist "
                    f"{self.min_factor_count} - es entstuende nie ein Score"
                )
                raise ValueError(msg)
        return self

    @field_serializer("value_factors", "quality_factors")
    def _sorted(self, factors: frozenset[str]) -> list[str]:
        # Feste Reihenfolge: gleicher Hash fuer gleiche Parameter, lesbarer Diff
        return sorted(factors)

    @property
    def quality_weight(self) -> float:
        return 1.0 - self.value_weight

    @classmethod
    def from_config(cls, cfg: ScoringConfig) -> ScoringProfileParams:
        """Die Parameter einer ``ScoringConfig``, etwa aus den ENV-Werten (Profil "Standard")."""
        return cls.model_validate(
            {
                "value_weight": cfg.value_weight,
                "min_market_cap": cfg.min_market_cap,
                "min_value_factor_share": cfg.min_value_factor_share,
                "min_quality_factor_share": cfg.min_quality_factor_share,
                "min_factor_count": cfg.min_factor_count,
                "value_trap_value_threshold": cfg.value_trap_value_threshold,
                "value_trap_quality_threshold": cfg.value_trap_quality_threshold,
                "drop_negative_value_metrics": cfg.drop_negative_value_metrics,
                # Ein Faktor ausserhalb des Katalogs faellt hier auf
                "value_factors": list(cfg.value_factors),
                "quality_factors": list(cfg.quality_factors),
            }
        )

    def to_config(self) -> ScoringConfig:
        """Die ``ScoringConfig`` fuer ``score()``. Faktoren in der Reihenfolge des Katalogs."""
        return ScoringConfig(
            min_market_cap=self.min_market_cap,
            value_weight=self.value_weight,
            quality_weight=self.quality_weight,
            min_value_factor_share=self.min_value_factor_share,
            min_quality_factor_share=self.min_quality_factor_share,
            min_factor_count=self.min_factor_count,
            value_trap_value_threshold=self.value_trap_value_threshold,
            value_trap_quality_threshold=self.value_trap_quality_threshold,
            drop_negative_value_metrics=self.drop_negative_value_metrics,
            value_factors={
                key: factor
                for key, factor in DEFAULT_VALUE_FACTORS.items()
                if key in self.value_factors
            },
            quality_factors={
                key: factor
                for key, factor in DEFAULT_QUALITY_FACTORS.items()
                if key in self.quality_factors
            },
        )


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
    """Die Parameter eines Profils aus einer ``ScoringConfig``, geprueft und als reines JSON."""
    return ScoringProfileParams.from_config(cfg).model_dump(mode="json")
