"""Die Abrufschleife: alle Titel nacheinander ueber einen ``FundamentalsProvider``.

Persistenz: ``on_result`` bekommt jedes Ergebnis sofort (im Batch: Schreiben in
PostgreSQL), bevor der naechste Titel abgerufen wird.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

import pandas as pd

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping

    from ..domain.fundamentals import Fundamentals
    from ..domain.history import HistoryState
    from ..domain.universe import Ticker
    from .ports import FundamentalsProvider

log = logging.getLogger(__name__)


def fetch_all(
    tickers: Iterable[Ticker],
    provider: FundamentalsProvider,
    *,
    sleep_between: float,
    on_result: Callable[[Fundamentals], None] | None = None,
    history: Mapping[str, HistoryState] | None = None,
) -> pd.DataFrame:
    """Holt alle Titel und liefert einen flachen DataFrame.

    Fehler im Callback brechen den Batch ab: lieber keinen Report als Daten, die nicht
    in der Historie landen. ``history``: gespeicherter Stand je Symbol; fehlt ein
    Symbol, gilt die ganze Historie. ``sleep_between`` schont den Provider.
    """
    history = history or {}
    ticker_list = list(tickers)
    rows: list[dict[str, Any]] = []
    for i, t in enumerate(ticker_list, 1):
        log.info("(%d/%d) %s", i, len(ticker_list), t.symbol)
        fund = provider.fetch(t, history.get(t.symbol))
        if on_result is not None:
            on_result(fund)
        rows.append(fund.to_flat_dict())
        time.sleep(sleep_between)
    return pd.DataFrame(rows)


def success_share(df: pd.DataFrame) -> float:
    """Anteil der Zeilen mit Marktkapitalisierung - fehlt sie, ist der Abruf gescheitert."""
    if df.empty or "market_cap" not in df.columns:
        return 0.0
    return float(df["market_cap"].notna().mean())
