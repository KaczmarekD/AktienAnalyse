"""Eine Zeile des Rankings, wie scoring sie im Event ``scoring.run.completed`` mitschickt."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from pydantic import Field

from ...base import Contract, PositiveId, missing_to_none
from ...securities import IsinStr
from .fundamentals import FundamentalsV1

# Spalten von score(), die keine Faktor-Raenge sind
_SCORE_COLUMNS = ("value_score", "quality_score", "composite_score")

# Welche Regel das Value-Trap-Flag gesetzt hat (F2.3): die bisherige (hoher Value-, niedriger
# Quality-Score) oder die mit Momentum und F-Score (ADR-0011, Punkt 5)
ValueTrapReason = Literal["quality", "momentum"]


class RankingRowV1(Contract):
    """Fundamentaldaten plus Bewertung. notification rendert Mail und CSV allein daraus.

    Value- und Quality-Score sind Perzentilraenge zwischen 0 und 1, ``None`` ohne genug
    Faktoren. Der Composite-Score ist ihr gewichtetes Mittel. Er hat bewusst keine
    Obergrenze: Die Gewichte werden erst ab 1 % Abweichung normiert, ein Wert knapp
    ueber 1 darf den Lauf nicht kippen. ``factor_ranks`` haelt die Raenge je Faktor,
    Schluessel wie im Scoring-Profil (z. B. ``ev_ebit``, ``roic``).
    """

    fundamentals: FundamentalsV1
    rank_overall: int = Field(ge=1)
    value_score: float | None = Field(default=None, ge=0, le=1)
    quality_score: float | None = Field(default=None, ge=0, le=1)
    composite_score: float | None = Field(default=None, ge=0)
    value_trap_flag: bool = False
    factor_ranks: dict[str, float | None] = Field(default_factory=dict)
    # F2.4 (additiv): Der Titel faellt unter die Branchenregel und steht im Abschnitt
    # "Finanzwerte" der Mail. Fehlt bei aelteren Events und gilt dann als nicht gesetzt.
    industry_rule: bool = False
    # F2.3 (additiv): Fehlt bei aelteren Events; ein Flag ohne Grund stammt von der bisherigen
    # Regel
    value_trap_reason: ValueTrapReason | None = None
    # D4.1 (additiv, nicht in ``to_flat``: Mail und CSV bleiben gleich): ISIN aus dem Abruf und
    # der Rang des Composite unter allen Titeln mit Composite, fuer die Depots (portfolio)
    isin: IsinStr | None = None
    composite_percentile: float | None = Field(default=None, ge=0, le=1)

    def to_flat(self) -> dict[str, Any]:
        """Eine Zeile wie die Ausgabe von ``score()``: Faktor-Raenge als ``rank_<name>``."""
        flat = self.fundamentals.to_flat()
        flat.update(
            value_score=self.value_score,
            quality_score=self.quality_score,
            composite_score=self.composite_score,
            value_trap_flag=self.value_trap_flag,
            value_trap_reason=self.value_trap_reason,
            rank_overall=self.rank_overall,
            industry_rule=self.industry_rule,
        )
        flat.update({f"rank_{name}": rank for name, rank in self.factor_ranks.items()})
        return flat

    @classmethod
    def from_flat(
        cls, flat: Mapping[Any, Any], fundamentals: FundamentalsV1 | None = None
    ) -> RankingRowV1:
        """Aus einer Zeile von ``score()``. NaN wird ``None``.

        ``fundamentals``: der Contract, den scoring empfangen hat. Dann bleiben die Fehler
        als Liste erhalten; ohne ihn entstehen die Fundamentaldaten aus der Zeile.
        """
        return cls(
            fundamentals=fundamentals or FundamentalsV1.from_flat(flat),
            rank_overall=int(flat["rank_overall"]),
            value_trap_flag=bool(flat.get("value_trap_flag", False)),
            value_trap_reason=missing_to_none(flat.get("value_trap_reason")),
            industry_rule=bool(flat.get("industry_rule", False)),
            factor_ranks={
                key.removeprefix("rank_"): missing_to_none(value)
                for key, value in flat.items()
                if isinstance(key, str) and key.startswith("rank_") and key != "rank_overall"
            },
            **{key: missing_to_none(flat.get(key)) for key in _SCORE_COLUMNS},
        )


# D4.1: Warum eine eingeordnete Aktie keinen Composite hat
PlacementReason = Literal["no_value", "no_quality", "no_data"]


class PlacementV1(Contract):
    """Eine Aktie aus den Depots, eingeordnet ins Referenzuniversum (D4.1, ANA-01 bis 03).

    Ihre Raenge sind die, die sie haette, wenn man sie allein dem Referenzuniversum hinzufuegte;
    die Raenge der Referenz aendern sich nicht. ``below_size_filter``: ein Titel des Universums
    unter dem Groessenfilter, sonst einer ausserhalb (Abdeckung). Ohne Composite nennt ``reason``
    den Grund. Ohne Nutzer und Mengen (WP-09).
    """

    symbol: str
    isin: IsinStr | None = None
    instrument_id: PositiveId | None = None
    value_score: float | None = Field(default=None, ge=0, le=1)
    quality_score: float | None = Field(default=None, ge=0, le=1)
    composite_score: float | None = Field(default=None, ge=0)
    composite_percentile: float | None = Field(default=None, ge=0, le=1)
    factor_ranks: dict[str, float | None] = Field(default_factory=dict)
    value_trap_flag: bool = False
    value_trap_reason: ValueTrapReason | None = None
    industry_rule: bool = False
    below_size_filter: bool = False
    reason: PlacementReason | None = None

    @classmethod
    def from_flat(
        cls,
        flat: Mapping[Any, Any],
        *,
        isin: str | None = None,
        instrument_id: int | None = None,
        below_size_filter: bool = False,
    ) -> PlacementV1:
        """Aus einer Zeile von ``place()``. NaN wird ``None``."""
        return cls(
            symbol=str(flat["symbol"]),
            isin=isin,
            instrument_id=instrument_id,
            value_trap_flag=bool(flat.get("value_trap_flag", False)),
            value_trap_reason=missing_to_none(flat.get("value_trap_reason")),
            industry_rule=bool(flat.get("industry_rule", False)),
            below_size_filter=below_size_filter,
            reason=missing_to_none(flat.get("reason")),
            factor_ranks={
                key.removeprefix("rank_"): missing_to_none(value)
                for key, value in flat.items()
                if isinstance(key, str) and key.startswith("rank_")
            },
            **{
                key: missing_to_none(flat.get(key))
                for key in (*_SCORE_COLUMNS, "composite_percentile")
            },
        )
