"""ETFs rechnen (D4.3, ANA-05, ANA-06; docs/architecture/depot/analyse.md, Abschnitt ETFs).

Reine Rechnung aus den Stammdaten eines Fonds (``EtfV1``: TER, Positionen mit Gewicht in
Prozent, ``complete``):

- **Laufende Kosten** = Positionswert x TER / 100, auf Cent (kaufmaennisch).
- **Durchschau**: Anteil eines Titels am Depot = direkt gehalten + Summe (Anteil des ETF am
  Depot x Gewicht des Titels im ETF). Gezaehlt werden Positionen mit ISIN und positivem Gewicht;
  dieselbe ISIN in mehreren Zeilen (etwa Aktiengattungen) zaehlt zusammen.
- **Ueberschneidung** zweier ETFs = Summe min(Gewicht in A, Gewicht in B) ueber gemeinsame ISINs.
- **Look-through-Score** = Summe (Gewicht x Composite) / Summe Gewicht ueber die Titel mit
  Composite, nur wenn sie mindestens ``min_covered`` des Fondsgewichts ausmachen (Standard 50 %).
- Kennt die Quelle nur die groessten Positionen (``complete`` falsch), sind Durchschau,
  Ueberschneidung und der bewertete Anteil Untergrenzen; das UI schreibt dann "mindestens".

Anteile sind Bruchteile (0,05 = 5 %), Gewichte der Quelle Prozent. Die Waehrung eines ETF ist
seine Fondswaehrung, nicht das Waehrungsrisiko seiner Bestaende.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")
HUNDRED = Decimal(100)
MIN_COVERED = 0.5


@dataclass(frozen=True)
class FundHolding:
    isin: str | None
    weight: float  # Prozent des Fondsvermoegens, bei Geldmarkt auch negativ


@dataclass(frozen=True)
class Fund:
    holdings: Sequence[FundHolding]
    complete: bool  # alle Positionen oder nur die groessten


@dataclass(frozen=True)
class Exposure:
    """Anteil je ISIN am Depot; ``lower_bound``: mindestens ein ETF nur mit den groessten."""

    weights: dict[str, float]
    lower_bound: bool


@dataclass(frozen=True)
class FundScore:
    """``covered``: Anteil des Fondsgewichts mit Composite; ``score`` nur ab ``min_covered``."""

    score: float | None
    covered: float
    lower_bound: bool


def running_costs(value_eur: Decimal | None, ter: float | None) -> Decimal | None:
    """Laufende Kosten pro Jahr in EUR; ohne Wert oder TER ``None``."""
    if value_eur is None or ter is None:
        return None
    return (value_eur * Decimal(str(ter)) / HUNDRED).quantize(CENT, ROUND_HALF_UP)


def _shares(fund: Fund) -> dict[str, float]:
    """Je ISIN der Anteil am Fonds (Bruchteil), nur positive Gewichte mit ISIN."""
    shares: dict[str, float] = defaultdict(float)
    for holding in fund.holdings:
        if holding.isin and holding.weight > 0:
            shares[holding.isin] += holding.weight / 100
    return dict(shares)


def look_through(direct: Mapping[str, float], funds: Sequence[tuple[float, Fund]]) -> Exposure:
    """``direct``: Anteil je ISIN der direkt gehaltenen Titel; ``funds``: (Anteil, ETF)."""
    weights: dict[str, float] = defaultdict(float, direct)
    for share, fund in funds:
        for isin, inside in _shares(fund).items():
            weights[isin] += share * inside
    return Exposure(dict(weights), lower_bound=any(not fund.complete for _, fund in funds))


def overlap(a: Fund, b: Fund) -> tuple[float, bool]:
    """Ueberschneidung als Bruchteil und ob sie nur eine Untergrenze ist."""
    left, right = _shares(a), _shares(b)
    common = left.keys() & right.keys()
    return sum(min(left[i], right[i]) for i in common), not (a.complete and b.complete)


def look_through_score(
    fund: Fund, composites: Mapping[str, float], *, min_covered: float = MIN_COVERED
) -> FundScore:
    """Mittel der Composites, gewichtet mit dem Anteil der Titel im Fonds."""
    shares = _shares(fund)
    scored = {i: s for i, s in shares.items() if i in composites}
    covered = sum(scored.values())
    score = (
        sum(s * composites[i] for i, s in scored.items()) / covered
        if scored and covered >= min_covered
        else None
    )
    return FundScore(score=score, covered=covered, lower_bound=not fund.complete)
