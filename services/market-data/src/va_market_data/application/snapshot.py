"""Anwendungsfall Snapshot: alle Titel eines Laufs abrufen und speichern (oder wiederverwenden).

Vorher in ``src/main.py`` (``_execute``, ``_fetch_and_store``, ``_history_state``).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import date

    import pandas as pd

    from ..domain.fundamentals import Fundamentals
    from ..domain.history import HistoryState
    from ..domain.universe import Ticker
    from .ports import Fetch, SnapshotStore

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Snapshot:
    fetch_run_id: int
    frame: pd.DataFrame  # eine Zeile je Titel, wie ``Fundamentals.to_flat_dict``


def take_snapshot(
    tickers: list[Ticker],
    *,
    source: str,
    as_of: date | None,
    store: SnapshotStore,
    fetch: Fetch,
    today: date,
    force_refresh: bool,
    on_result: Callable[[Fundamentals], None] | None = None,
) -> Snapshot:
    """Nutzt einen Abruf vom selben Tag (ausser bei ``force_refresh``), sonst ruft er ab.

    Jeder Titel wird sofort gespeichert. Laesst sich einer auch nach Retries nicht
    speichern, faellt nur er aus dem Lauf - Report und Datenbank bleiben deckungsgleich.
    ``on_result`` bekommt jeden abgerufenen Titel danach (Fortschritt).
    """
    symbols = [t.symbol for t in tickers]
    fetch_run_id = None if force_refresh else store.find_reusable_fetch(today, symbols)
    if fetch_run_id is not None:
        log.info("Nutze Abruf #%d von heute aus der Datenbank", fetch_run_id)
        return Snapshot(fetch_run_id, store.load_snapshots(fetch_run_id, symbols))

    fetch_run_id = store.start_fetch(tickers, source, as_of)
    unsaved: set[str] = set()

    def stored(fund: Fundamentals) -> None:
        try:
            store.record_fundamentals(fetch_run_id, fund)
        except Exception:
            log.exception("%s konnte nicht gespeichert werden - Titel entfaellt", fund.symbol)
            unsaved.add(fund.symbol)
        if on_result is not None:
            on_result(fund)

    df = fetch(tickers, on_result=stored, history=_history_state(store, symbols))
    if unsaved and "symbol" in df.columns:
        df = df[~df["symbol"].isin(unsaved)].reset_index(drop=True)
    store.finish_fetch(fetch_run_id, df)
    return Snapshot(fetch_run_id, df)


def _history_state(store: SnapshotStore, symbols: list[str]) -> Mapping[str, HistoryState]:
    """Gespeicherter Stand der Zeitreihen je Titel.

    Ist er nicht lesbar, wird die ganze Historie geholt. Die Versionierung verhindert
    Dubletten, es kostet nur Zeit.
    """
    try:
        return store.history_state(symbols)
    except Exception:
        log.warning("Stand der Zeitreihen nicht lesbar - rufe die ganze Historie ab", exc_info=True)
        return {}
