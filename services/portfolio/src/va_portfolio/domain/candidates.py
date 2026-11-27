"""Pruefkandidaten zu einer Aktie (D5.5, HIN-06; docs/architecture/depot/analyse.md).

Zu einer Aktie mit HIN-Q01 oder HIN-Q02 bis zu drei Titel **zum Vergleich**: aus dem
Referenzuniversum desselben Bewertungslaufs, aus demselben Sektor, mit hoeherem Composite, ohne
Value-Trap-Flag und nicht schon im Depot. Das ist dieselbe Information wie das Ranking, nur
gefiltert; keine Empfehlung, etwas zu ersetzen.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .valuation import Score

MAX_CANDIDATES = 3


def candidates(
    stock: Score,
    universe: Iterable[Score],
    held: Collection[str],
    *,
    limit: int = MAX_CANDIDATES,
) -> list[Score]:
    """Hoechstens ``limit`` Titel, bester Composite zuerst, bei Gleichstand nach Symbol.

    Ohne Sektor oder Composite der Aktie gibt es keinen Vergleich. ``universe`` sind die Titel
    des Rankings eines Bewertungslaufs; andere Einordnungen zaehlen nicht mit.
    """
    if stock.sector is None or stock.composite_score is None:
        return []
    own = stock.composite_score
    pool = [
        title
        for title in universe
        if title.reference == "universe"
        and title.scoring_run_id == stock.scoring_run_id
        and title.sector == stock.sector
        and title.composite_score is not None
        and title.composite_score > own
        and not title.value_trap_flag
        and title.isin != stock.isin
        and title.isin not in held
    ]
    pool.sort(key=lambda title: (-(title.composite_score or 0.0), title.symbol))
    return pool[:limit]
