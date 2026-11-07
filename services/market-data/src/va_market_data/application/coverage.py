"""Anwendungsfall Abdeckung im Wochenlauf (D2.2, WP-05, WP-07).

Nach dem Referenzuniversum holt der Wochenlauf die Fundamentaldaten der Aktien in der Abdeckung,
im selben Abruf, gespeichert mit ``role = 'coverage'``. Sie gehen nicht ins Ranking.

Robustheit vor Vollstaendigkeit: Ist die Abdeckung nicht lesbar oder scheitert ihr Abruf, fehlt nur
sie; der Wochenlauf mit Mail laeuft weiter. Ein Titel, der sich nicht speichern laesst, faellt nur
selbst heraus. Wird der Abruf des Tages wiederverwendet, holt der Lauf nur, was noch fehlt.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

import pandas as pd

from ..domain.coverage import CoverageItem, coverage_tickers

if TYPE_CHECKING:
    from collections.abc import Collection, Sequence

    from ..domain.fundamentals import Fundamentals
    from ..domain.history import HistoryState
    from ..domain.universe import Ticker
    from .ports import Fetch

log = logging.getLogger(__name__)


class CoverageStore(Protocol):
    """Abdeckung und ihre Snapshots im Schema ``market_data``."""

    def coverage(self) -> list[CoverageItem]: ...

    def covered_snapshots(self, fetch_run_id: int) -> pd.DataFrame:
        """Die schon gespeicherten Snapshots der Abdeckung in diesem Abruf."""
        ...

    def record_covered(self, fetch_run_id: int, fund: Fundamentals, isin: str | None) -> None:
        """Wie ``record_fundamentals``, aber mit ``role = 'coverage'`` und der ISIN."""
        ...

    def history_state(self, symbols: Collection[str]) -> Mapping[str, HistoryState]: ...


@dataclass(frozen=True)
class Covered:
    frame: pd.DataFrame  # eine Zeile je Aktie, wie ``Fundamentals.to_flat_dict``
    isins: dict[str, str] = field(default_factory=dict)  # Symbol -> ISIN


def plan_coverage(store: CoverageStore, universe: Sequence[Ticker]) -> list[Ticker]:
    """Die Aktien der Abdeckung, die der Lauf zusaetzlich abruft; leer, wenn sie nicht lesbar ist.

    ``universe``: das volle Referenzuniversum (auch bei DAX_ONLY), damit kein DAX- oder MDAX-Titel
    als Abdeckung abgerufen wird.
    """
    try:
        items = store.coverage()
    except Exception:
        log.warning("Abdeckung nicht lesbar - der Lauf geht ohne sie weiter", exc_info=True)
        return []
    return coverage_tickers(
        items,
        universe_symbols={t.symbol for t in universe},
        universe_isins={t.isin for t in universe if t.isin},
    )


def take_coverage(
    *,
    fetch_run_id: int,
    universe: Sequence[Ticker],
    store: CoverageStore,
    fetch: Fetch,
    reused: bool,
    tickers: list[Ticker] | None = None,
    on_result: Callable[[Fundamentals], None] | None = None,
) -> Covered:
    """Ruft die Aktien der Abdeckung ab und speichert sie; wirft nicht.

    ``tickers``: schon geplant (``plan_coverage``), sonst plant der Aufruf selbst. ``on_result``
    bekommt jeden abgerufenen Titel (Fortschritt). Bricht der Abruf ab, enthaelt das Ergebnis die
    bis dahin gespeicherten Titel, wie die Datenbank.
    """
    if tickers is None:
        tickers = plan_coverage(store, universe)
    if not tickers:
        return Covered(pd.DataFrame())
    isins = {t.symbol: t.isin for t in tickers if t.isin}
    try:
        done = store.covered_snapshots(fetch_run_id) if reused else pd.DataFrame()
    except Exception:
        log.warning("Gespeicherte Abdeckung nicht lesbar - alles neu", exc_info=True)
        done = pd.DataFrame()
    known = set(done["symbol"]) if "symbol" in done.columns else set()
    missing = [t for t in tickers if t.symbol not in known]
    fetched = _fetch(
        missing,
        fetch_run_id=fetch_run_id,
        store=store,
        fetch=fetch,
        isins=isins,
        on_result=on_result,
    )
    frames = [df for df in (done, fetched) if not df.empty]
    frame = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    log.info("Abdeckung: %d Aktien (%d neu abgerufen)", len(frame), len(fetched))
    return Covered(frame, isins)


def _fetch(
    tickers: list[Ticker],
    *,
    fetch_run_id: int,
    store: CoverageStore,
    fetch: Fetch,
    isins: Mapping[str, str],
    on_result: Callable[[Fundamentals], None] | None,
) -> pd.DataFrame:
    if not tickers:
        return pd.DataFrame()
    saved: list[dict[str, object]] = []

    def stored(fund: Fundamentals) -> None:
        try:
            store.record_covered(fetch_run_id, fund, isins.get(fund.symbol))
        except Exception:
            log.exception("%s (Abdeckung) konnte nicht gespeichert werden", fund.symbol)
        else:
            saved.append(fund.to_flat_dict())
        if on_result is not None:
            try:
                on_result(fund)
            except Exception:
                log.warning("Fortschritt fuer %s nicht gemeldet", fund.symbol, exc_info=True)

    symbols = [t.symbol for t in tickers]
    try:
        history = store.history_state(symbols)
    except Exception:
        log.warning("Stand der Zeitreihen nicht lesbar - ganze Historie", exc_info=True)
        history = {}
    try:
        fetch(tickers, on_result=stored, history=history)
    except Exception:
        log.warning(
            "Abruf der Abdeckung abgebrochen - %d von %d Titeln gespeichert",
            len(saved),
            len(tickers),
            exc_info=True,
        )
    # Genau die gespeicherten Titel: Event und Datenbank bleiben deckungsgleich
    return pd.DataFrame(saved)
