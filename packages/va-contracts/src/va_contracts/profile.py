"""Parameter eines Scoring-Profils (ADR-0009): gespeichert als JSON, im UI bearbeitet.

Der gemeinsame Vertrag zwischen scoring, das damit rechnet, und dem web-api, das sie
entgegennimmt (P3.3). Die Regeln stehen hier genau einmal: Pydantic -> OpenAPI -> Zod im
Browser (docs/architecture/scoring-profile.md). Aenderungen nur additiv: Ein neuer Parameter
bekommt einen Standardwert, gespeicherte Versionen ohne ihn erhalten ihn beim Lesen.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal, Self, get_args

from pydantic import ConfigDict, Field, ValidationError, field_serializer, model_validator

from .base import Contract

# Der Faktor-Katalog als Schluessel. Spalte und Richtung stehen in scoring (DEFAULT_*_FACTORS)
# und sind im UI nicht aenderbar; ein Test dort haelt beide Listen gleich.
ValueFactorKey = Literal["ev_ebit", "pb", "p_fcf", "shareholder_yield"]
QualityFactorKey = Literal[
    "roic", "fcf_margin", "operating_margin", "net_debt_ebitda", "earnings_stability"
]

# Der Composite braucht je Gruppe mindestens zwei vorhandene Faktoren
MIN_ACTIVE_FACTORS = 2

# Branchenregel (ADR-0011, Punkt 3, mit den Ergaenzungen bei der Annahme am 06.11.2026): Anfaenge
# der Yahoo-``industry`` von Banken, Versicherern, "Capital Markets" und Immobilien
DEFAULT_INDUSTRY_PREFIXES = ("Banks", "Insurance", "Capital Markets", "Real Estate", "REIT")


class ProfileParamsV1(Contract):
    """Die Parameter eines Profils mit ihren Regeln.

    Unbekannte Felder sind ein Fehler, anders als bei Events: Ein Tippfehler in gespeicherten
    params oder im Formular darf nicht still wegfallen.
    """

    model_config = ConfigDict(extra="forbid")

    value_weight: float = Field(
        default=0.6, ge=0, le=1, description="Gewicht von Value; Quality ist der Rest"
    )
    min_market_cap: float = Field(
        default=300_000_000.0, ge=0, description="Mindest-Marktkapitalisierung (EUR)"
    )
    min_value_factor_share: float = Field(
        default=0.5, ge=0, le=1, description="Mindestanteil vorhandener Value-Faktoren"
    )
    min_quality_factor_share: float = Field(
        default=0.5, ge=0, le=1, description="Mindestanteil vorhandener Quality-Faktoren"
    )
    # Im UI nicht aenderbar; steht drin, damit ein Profil das Scoring vollstaendig beschreibt
    min_factor_count: int = Field(
        default=2, ge=1, description="Mindestzahl vorhandener Faktoren je Gruppe"
    )
    value_trap_value_threshold: float = Field(
        default=0.70, ge=0, le=1, description="Value-Trap ab diesem Value-Score"
    )
    value_trap_quality_threshold: float = Field(
        default=0.30, ge=0, le=1, description="Value-Trap bis zu diesem Quality-Score"
    )
    drop_negative_value_metrics: bool = Field(
        default=True, description="Negative Multiples aus dem Value-Ranking ausschliessen"
    )
    value_factors: frozenset[ValueFactorKey] = Field(
        default_factory=lambda: frozenset(get_args(ValueFactorKey)),
        description="Aktive Value-Faktoren, mindestens 2",
    )
    quality_factors: frozenset[QualityFactorKey] = Field(
        default_factory=lambda: frozenset(get_args(QualityFactorKey)),
        description="Aktive Quality-Faktoren, mindestens 2",
    )
    # F2.4 (ADR-0011, Punkt 3): zunaechst abgeschaltet, erst das Profil v2 (F2.5) schaltet sie an
    industry_rules: bool = Field(
        default=False,
        description="Branchenregel: EV-, FCF- und Margen-Kennzahlen zaehlen bei Finanzwerten nicht",
    )
    industry_prefixes: tuple[str, ...] = Field(
        default=DEFAULT_INDUSTRY_PREFIXES,
        description="Anfaenge der Branche (Yahoo), fuer die die Branchenregel gilt",
    )
    cost_of_capital: float = Field(
        default=0.08, gt=0, le=0.5, description="Kapitalkosten r fuer das gerechtfertigte KBV"
    )
    terminal_growth: float = Field(
        default=0.02,
        ge=-0.05,
        le=0.1,
        description="Langfristiges Wachstum g fuer das gerechtfertigte KBV",
    )

    @model_validator(mode="after")
    def _justified_pb_defined(self) -> Self:
        # Gerechtfertigtes KBV (ROE - g) / (r - g): nur mit r > g definiert
        if self.cost_of_capital <= self.terminal_growth:
            msg = "cost_of_capital muss groesser als terminal_growth sein"
            raise ValueError(msg)
        if any(not prefix.strip() for prefix in self.industry_prefixes):
            msg = "industry_prefixes: leere Eintraege sind nicht erlaubt"
            raise ValueError(msg)
        return self

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


def params_from_config(config: Mapping[str, Any] | None) -> ProfileParamsV1 | None:
    """Die Parameter eines Bewertungslaufs aus ``scoring.scoring_run.config`` (Track G, G3).

    Die Konfiguration ist ``asdict(ScoringConfig)``, JSON-sicher gespeichert: dieselben Namen wie
    hier, die Faktoren als ``{schluessel: [spalte, richtung]}``. Das web-api (ohne NATS) und der
    Backfill der Projektionen lesen so auch Laeufe, deren Profil-Version unbekannt ist. Fehlt die
    Konfiguration (importierte Altdaten) oder verletzt sie die Regeln, gibt es ``None``.
    """
    if not config or "value_weight" not in config:
        return None
    data = {
        name: config[name]
        for name in ProfileParamsV1.model_fields
        if name in config and name not in ("value_factors", "quality_factors")
    }
    for name in ("value_factors", "quality_factors"):
        if name in config:
            data[name] = list(config[name])  # Schluessel des Katalogs
    if "industry_prefixes" in config:
        data["industry_prefixes"] = tuple(config["industry_prefixes"])
    try:
        return ProfileParamsV1.model_validate(data)
    except ValidationError:
        return None
