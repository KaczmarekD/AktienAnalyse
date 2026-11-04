"""Settings von scoring (P5.1a): Startwerte des Profils "Standard". Der Batch erbt sie.

Gewichte und Groessenfilter gelten nur fuer das erste Profil (ADR-0009); danach rechnet scoring
mit dem aktiven Profil aus der Datenbank.
"""

from __future__ import annotations

from pydantic import Field

from va_platform.service import ServiceSettings


class ScoringSettings(ServiceSettings):
    min_market_cap: float = Field(default=300_000_000.0, ge=0)
    value_weight: float = Field(default=0.6, ge=0, le=1)
    quality_weight: float = Field(default=0.4, ge=0, le=1)

    def model_post_init(self, __context: object) -> None:
        # Summe von value + quality muss ~1 sein - sonst stillschweigend skalieren
        total = self.value_weight + self.quality_weight
        if total <= 0:
            msg = "value_weight + quality_weight muss > 0 sein"
            raise ValueError(msg)
        if abs(total - 1.0) > 0.01:
            # __dict__ ist bei Pydantic v2 ein MappingProxy - object.__setattr__ umgeht das
            object.__setattr__(self, "value_weight", self.value_weight / total)
            object.__setattr__(self, "quality_weight", self.quality_weight / total)
