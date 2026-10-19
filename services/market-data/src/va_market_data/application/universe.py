"""Die Kette der Universum-Quellen: die erste gueltige gewinnt, die Fallback-CSV kommt zuletzt.

Weicht die Live-Quelle von der CSV ab, meldet ``Universe.added/removed`` das - der Report
zeigt dann einen Hinweis, die CSV zu pflegen. Die CSV wird bewusst nicht automatisch
ueberschrieben.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ..domain.universe import FALLBACK_SOURCE, Universe, dedupe, diff

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import date

    from ..domain.universe import Ticker, UniverseConfig
    from .ports import UniverseSource

log = logging.getLogger(__name__)


def load_universe(
    sources: Sequence[UniverseSource],
    fallback: list[Ticker],
    cfg: UniverseConfig,
    today: date,
    *,
    force_fallback: bool = False,
) -> Universe:
    """Universum aus der ersten gueltigen Quelle, dedupliziert, sonst aus der CSV."""
    fallback = dedupe(fallback)
    if force_fallback:
        log.info("Force-Fallback aktiv - lese aus CSV")
    else:
        for source in sources:
            try:
                live = source.load(fallback, cfg, today)
            except Exception as e:
                log.warning("%s-Quelle ungueltig (%s) - naechste Quelle", source.name, e)
                continue
            return _live_universe(live.tickers, source.name, live.as_of, fallback)

    log.info("Universum aus Fallback-CSV: %d Ticker", len(fallback))
    return Universe(tickers=fallback, source=FALLBACK_SOURCE)


def _live_universe(
    tickers: list[Ticker], source: str, as_of: date | None, fallback: list[Ticker]
) -> Universe:
    unique = dedupe(tickers)
    added, removed = diff(unique, fallback)
    log.info("Universum aus %s: %d Ticker (Stand %s)", source, len(unique), as_of or "-")
    if added or removed:
        log.warning(
            "Fallback-CSV veraltet: +%s / -%s",
            [t.symbol for t in added],
            [t.symbol for t in removed],
        )
    return Universe(tickers=unique, source=source, as_of=as_of, added=added, removed=removed)
