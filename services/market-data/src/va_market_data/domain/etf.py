"""ETF-Zusammensetzung (D2.4, WP-10; docs/architecture/depot/wertpapiere.md).

Rein, ohne Ein-/Ausgabe. Die Quellen (iShares, yfinance ``funds_data``) liefern Rohdaten, die
Adapter bilden sie auf diese Typen ab.

- Gewichte in Prozent des Fondsvermoegens, wie die Anbieter sie nennen. Ein Anleihe-ETF fuehrt
  Geldmarkt-Positionen auch mit negativem Gewicht; die Summe liegt dann ueber 100.
- ``complete``: alle Positionen (Anbieterdatei) oder nur die groessten (yfinance). Die Durchschau
  (D5) zeigt den Hinweis.
- Die Bezeichnungen von Sektor, Land und Anlageklasse bleiben die der Quelle (``source``); die
  Durchschau ordnet sie zu.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date
from typing import Literal, get_args

Distribution = Literal["accumulating", "distributing"]
DISTRIBUTIONS: tuple[str, ...] = get_args(Distribution)
Dimension = Literal["sector", "country", "asset_class"]
DIMENSIONS: tuple[str, ...] = get_args(Dimension)

UNKNOWN = "-"  # ohne Angabe der Quelle
TOP_HOLDINGS = 10  # so viele nennt yfinance; das Event nennt nicht mehr
_DIGITS = 6  # Rundung der Summen, sonst haengen Gleitkomma-Reste an

__all__ = [
    "DIMENSIONS",
    "DISTRIBUTIONS",
    "TOP_HOLDINGS",
    "UNKNOWN",
    "Dimension",
    "Distribution",
    "EtfComposition",
    "FundFacts",
    "Holding",
    "composition_from_holdings",
    "weights",
]


@dataclass(frozen=True)
class Holding:
    """Eine Position des Fonds."""

    name: str
    weight: float  # in Prozent des Fondsvermoegens
    isin: str | None = None
    ticker: str | None = None
    asset_class: str | None = None
    sector: str | None = None
    country: str | None = None
    currency: str | None = None


@dataclass(frozen=True)
class FundFacts:
    """Fondsdaten des Anbieters."""

    name: str | None = None
    ter: float | None = None  # laufende Kosten in Prozent pro Jahr
    fund_size: float | None = None  # in Millionen der Fondswaehrung
    currency: str | None = None  # Fondswaehrung
    distribution: Distribution | None = None
    provider: str | None = None
    effective_duration: float | None = None  # Anleihe-ETFs, in Jahren


@dataclass(frozen=True)
class EtfComposition:
    """Stand eines Fonds bei einer Quelle: Fondsdaten, Positionen, Gewichte."""

    isin: str
    source: str  # ishares, yahoo
    as_of: date
    complete: bool
    facts: FundFacts
    holdings: tuple[Holding, ...] = ()
    sectors: dict[str, float] = field(default_factory=dict)
    countries: dict[str, float] = field(default_factory=dict)
    asset_classes: dict[str, float] = field(default_factory=dict)

    @property
    def holdings_count(self) -> int:
        return len(self.holdings)

    def top(self, n: int = TOP_HOLDINGS) -> tuple[Holding, ...]:
        """Die ``n`` groessten Positionen, bei gleichem Gewicht in der Reihenfolge der Quelle."""
        return tuple(sorted(self.holdings, key=lambda h: -h.weight)[:n])


def weights(holdings: Iterable[Holding], dimension: str) -> dict[str, float]:
    """Summe der Gewichte je Bezeichnung (ohne Angabe ``UNKNOWN``), die groesste zuerst."""
    if dimension not in DIMENSIONS:
        msg = f"Unbekannte Dimension {dimension!r}, erlaubt: {', '.join(DIMENSIONS)}"
        raise ValueError(msg)
    sums: dict[str, float] = {}
    for holding in holdings:
        label = getattr(holding, dimension) or UNKNOWN
        sums[label] = sums.get(label, 0.0) + holding.weight
    ordered = sorted(sums.items(), key=lambda item: -item[1])
    return {label: round(weight, _DIGITS) for label, weight in ordered}


def composition_from_holdings(
    isin: str, source: str, as_of: date, facts: FundFacts, holdings: Iterable[Holding]
) -> EtfComposition:
    """Eine vollstaendige Liste: die Gewichte ergeben sich aus den Positionen."""
    held = tuple(holdings)
    return EtfComposition(
        isin=isin,
        source=source,
        as_of=as_of,
        complete=True,
        facts=facts,
        holdings=held,
        sectors=weights(held, "sector"),
        countries=weights(held, "country"),
        asset_classes=weights(held, "asset_class"),
    )
