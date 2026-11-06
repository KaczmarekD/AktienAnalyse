"""Scoring-Profile (ADR-0009): die Parameter des Scorings, versioniert in der Datenbank.

Jedes Speichern erzeugt eine neue, unveraenderliche Version. Aktiv ist genau eine. Die heutigen
ENV-Werte legen einmalig das Profil "Standard" an (P2b.1). ``ScoringProfileParams`` prueft die
Parameter und bildet sie auf ``score()`` ab (P2b.2). Seit P2b.3 rechnet jeder Bewertungslauf mit
dem aktiven Profil und speichert dessen Version. Details: docs/architecture/scoring-profile.md.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from va_contracts.profile import (
    MIN_ACTIVE_FACTORS,
    ProfileParamsV1,
    QualityFactorKey,
    ValueFactorKey,
)

from .scoring import DEFAULT_QUALITY_FACTORS, DEFAULT_VALUE_FACTORS, ScoringConfig

__all__ = [
    "DEFAULT_PROFILE_NAME",
    "FACTOR_INFO",
    "MIN_ACTIVE_FACTORS",
    "ActiveProfile",
    "ProfileVersionRef",
    "QualityFactorKey",
    "ScoringProfileParams",
    "ValueFactorKey",
    "profile_params",
]

DEFAULT_PROFILE_NAME = "Standard"

# Fuer das UI (P3.3): Name und Methodik-Hinweis je Faktor. Die Richtung steht im Katalog, das UI
# haengt sie an. Seit Track G (G2) mit den Texten aus dem Katalog der Spec
# (docs/architecture/ui-neugestaltung.md) und Labels wie im Glossar des UI; die Mail nutzt sie nicht.
FACTOR_INFO: dict[str, tuple[str, str]] = {
    "ev_ebit": (
        "EV/EBIT",
        "Unternehmenswert (Börsenwert plus Nettoschulden) geteilt durch den operativen Gewinn. "
        "Negative Werte zählen nicht.",
    ),
    "pb": (
        "KBV",
        "Kurs-Buchwert-Verhältnis: Börsenwert geteilt durch das Eigenkapital laut Bilanz. "
        "Negative Werte zählen nicht.",
    ),
    "p_fcf": (
        "Kurs/FCF",
        "Börsenwert geteilt durch den Free Cashflow, also das Geld, das nach Investitionen übrig "
        "bleibt. Schwerer zu schönen als der Gewinn.",
    ),
    "shareholder_yield": (
        "Shareholder Yield",
        "Dividenden plus Aktienrückkäufe im Verhältnis zum Börsenwert: Wie viel fließt an die "
        "Aktionäre zurück?",
    ),
    "roic": (
        "ROIC",
        "Return on Invested Capital: Rendite nach Steuern auf das eingesetzte Eigen- und "
        "Fremdkapital.",
    ),
    "fcf_margin": ("FCF-Marge", "Free Cashflow je Euro Umsatz."),
    "operating_margin": ("Operative Marge", "Operativer Gewinn (EBIT) je Euro Umsatz."),
    "net_debt_ebitda": (
        "Net Debt/EBITDA",
        "Nettoschulden geteilt durch den Gewinn vor Zinsen, Steuern und Abschreibungen: in wie "
        "vielen Jahren die Schulden getilgt wären.",
    ),
    "earnings_stability": (
        "Gewinnstabilität",
        "Wie wenig der Nettogewinn über die letzten fünf Geschäftsjahre schwankt. 1 heißt sehr "
        "stabil.",
    ),
}


class ScoringProfileParams(ProfileParamsV1):
    """Die Parameter mit ihrer Abbildung auf ``score()`` (P2b.2).

    Felder und Regeln stehen im Contract ``ProfileParamsV1`` (P3.3), denn das web-api braucht
    sie fuer OpenAPI und die Pruefung, darf scoring aber nicht importieren.
    """

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
                "industry_rules": cfg.industry_rules,
                "industry_prefixes": tuple(cfg.industry_prefixes),
                "cost_of_capital": cfg.cost_of_capital,
                "terminal_growth": cfg.terminal_growth,
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
            industry_rules=self.industry_rules,
            industry_prefixes=tuple(self.industry_prefixes),
            cost_of_capital=self.cost_of_capital,
            terminal_growth=self.terminal_growth,
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


@dataclass(frozen=True)
class ActiveProfile:
    """Damit rechnet ein Bewertungslauf. ``ref`` fehlt nur ohne gespeichertes Profil (Replay)."""

    config: ScoringConfig
    ref: ProfileVersionRef | None = None

    @property
    def label(self) -> str | None:
        return None if self.ref is None else self.ref.label


def profile_params(cfg: ScoringConfig) -> dict[str, Any]:
    """Die Parameter eines Profils aus einer ``ScoringConfig``, geprueft und als reines JSON."""
    return ScoringProfileParams.from_config(cfg).model_dump(mode="json")
