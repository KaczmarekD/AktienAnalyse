"""Eine Zeile des Rankings, wie scoring sie im Event ``scoring.run.completed`` mitschickt."""

from __future__ import annotations

from typing import Any

from pydantic import Field

from ...base import Contract
from .fundamentals import FundamentalsV1


class RankingRowV1(Contract):
    """Fundamentaldaten plus Bewertung. notification rendert Mail und CSV allein daraus.

    Die Scores sind Perzentilraenge zwischen 0 und 1, ``None`` ohne genug Faktoren.
    ``factor_ranks`` haelt die Raenge je Faktor, Schluessel wie im Scoring-Profil
    (z. B. ``ev_ebit``, ``roic``).
    """

    fundamentals: FundamentalsV1
    rank_overall: int = Field(ge=1)
    value_score: float | None = Field(default=None, ge=0, le=1)
    quality_score: float | None = Field(default=None, ge=0, le=1)
    composite_score: float | None = Field(default=None, ge=0, le=1)
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
