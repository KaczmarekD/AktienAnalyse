"""Eine Zeile des Rankings, wie scoring sie im Event ``scoring.run.completed`` mitschickt."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import Field

from ...base import Contract, missing_to_none
from .fundamentals import FundamentalsV1

# Spalten von score(), die keine Faktor-Raenge sind
_SCORE_COLUMNS = ("value_score", "quality_score", "composite_score")


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

    def to_flat(self) -> dict[str, Any]:
        """Eine Zeile wie die Ausgabe von ``score()``: Faktor-Raenge als ``rank_<name>``."""
        flat = self.fundamentals.to_flat()
        flat.update(
            value_score=self.value_score,
            quality_score=self.quality_score,
            composite_score=self.composite_score,
            value_trap_flag=self.value_trap_flag,
            rank_overall=self.rank_overall,
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
            factor_ranks={
                key.removeprefix("rank_"): missing_to_none(value)
                for key, value in flat.items()
                if isinstance(key, str) and key.startswith("rank_") and key != "rank_overall"
            },
            **{key: missing_to_none(flat.get(key)) for key in _SCORE_COLUMNS},
        )
