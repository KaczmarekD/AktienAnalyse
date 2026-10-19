"""Uebergang bis P1.8: verdrahtet den Yahoo-Adapter fuer den Batch.

Abruf und Kennzahlen liegen in ``va_market_data`` (Adapter ``yahoo``, Schleife
``application.fetch``, Kennzahlen ``domain.metrics``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from va_market_data.adapters.yahoo import FetcherConfig, YahooFundamentals
from va_market_data.application.fetch import fetch_all as _fetch_all

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping

    import pandas as pd

    from va_market_data.domain.fundamentals import Fundamentals
    from va_market_data.domain.history import HistoryState
    from va_market_data.domain.universe import Ticker


def fetch_all(
    tickers: Iterable[Ticker],
    cfg: FetcherConfig | None = None,
    on_result: Callable[[Fundamentals], None] | None = None,
    history: Mapping[str, HistoryState] | None = None,
) -> pd.DataFrame:
    """Alle Titel ueber Yahoo; Schnittstelle wie vor P1.4."""
    cfg = cfg or FetcherConfig()
    return _fetch_all(
        tickers,
        YahooFundamentals(cfg),
        sleep_between=cfg.sleep_between,
        on_result=on_result,
        history=history,
    )
