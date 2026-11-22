"""Anwendungsfall Abdeckung im Wochenlauf (D2.2, WP-05, WP-07).

Nach dem Referenzuniversum holt der Wochenlauf die Fundamentaldaten der Aktien in der Abdeckung,
im selben Abruf, gespeichert mit ``role = 'coverage'``. Sie gehen nicht ins Ranking.

Robustheit vor Vollstaendigkeit: Ist die Abdeckung nicht lesbar oder scheitert ihr Abruf, fehlt nur
sie; der Wochenlauf mit Mail laeuft weiter. Ein Titel, der sich nicht speichern laesst, faellt nur
selbst heraus. Wird der Abruf des Tages wiederverwendet, holt der Lauf nur, was noch fehlt.

Seit D3.3 kommt die Menge von portfolio (``portfolio.coverage.changed``, ``follow_portfolio``):
- Bekannte Eintraege bleiben, wie sie sind (auch ein Symbol, das das Kommando gewaehlt hat).
- Neue ISINs loest market-data selbst auf: zuerst aus den eigenen Wertpapieren (die Suche hat sie
  meist schon gespeichert), sonst ueber ESMA FIRDS und OpenFIGI. Ein Eintrag ohne Kurs-Symbol wird
  bei jeder Meldung neu aufgeloest (OpenFIGI kann beim ersten Mal ausgefallen sein).
- Eine ISIN, die sich nicht aufloesen laesst, fehlt vorerst. portfolio meldet die ganze Menge
  taeglich, dann folgt der naechste Versuch. Nach ``RESOLVE_BUDGET`` fragt die Meldung keine
  Quelle mehr (der Consumer von market-data wartet sonst, auch ein Wochenlauf); der Rest folgt
  mit der naechsten Meldung.
- Eine Meldung, die aelter ist als die juengste Fassung, aendert nichts (Zustellung nach einem
  Fehler in anderer Reihenfolge). Gespeichert wird sie mit ihrem Zeitpunkt.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import timedelta
from typing import TYPE_CHECKING, Protocol

import pandas as pd

from ..domain.coverage import CoverageItem, coverage_symbols, coverage_tickers

if TYPE_CHECKING:
    from collections.abc import Collection, Sequence
    from datetime import datetime

    from va_contracts.securities import AssetClass

    from ..domain.fundamentals import Fundamentals
    from ..domain.history import HistoryState
    from ..domain.securities import Listing, SecurityHit
    from ..domain.universe import Ticker
    from .ports import Fetch
    from .securities import ResolvedSecurity

log = logging.getLogger(__name__)

PORTFOLIO_SOURCE = "portfolio"  # Quelle der Fassung (D3.3); das Kommando schreibt "command"
# Hoechstens so lange loest eine Meldung neue ISINs auf (OpenFIGI ohne Schluessel: 25 Anfragen je
# Minute); danach kommen die Stammdaten (bis REFRESH_BUDGET) dazu
RESOLVE_BUDGET = timedelta(minutes=5)


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


class CoverageWriter(Protocol):
    """Was die Uebernahme aus portfolio braucht (D3.3)."""

    def coverage(self) -> list[CoverageItem]: ...

    def coverage_as_of(self) -> datetime | None:
        """Zeitpunkt der juengsten Fassung; ``None`` ohne Fassung."""
        ...

    def write_coverage(
        self, items: Sequence[CoverageItem], *, source: str, at: datetime
    ) -> bool: ...


@dataclass(frozen=True)
class CoverageUpdate:
    """Ergebnis einer Meldung von portfolio (D3.3)."""

    changed: bool  # neue Fassung gespeichert
    added: list[CoverageItem] = field(default_factory=list)  # neu oder neu aufgeloest
    unresolved: list[str] = field(default_factory=list)  # fehlen vorerst


def coverage_item(
    isin: str,
    asset_class: AssetClass,
    listings: Sequence[Listing],
    *,
    name: str | None,
    price_symbol: str | None = None,
) -> CoverageItem:
    """Ein Eintrag der Abdeckung mit den Symbolen aus den Listings; ``price_symbol`` waehlt das
    Listing fuer die Kurse (Kommando ``ISIN=SYMBOL``)."""
    fundamentals, price = coverage_symbols(isin, asset_class, listings)
    return CoverageItem(
        isin=isin,
        asset_class=asset_class,
        fundamentals_symbol=fundamentals,
        price_symbol=price_symbol or price,
        name=name,
    )


def follow_portfolio(
    isins: Sequence[str],
    *,
    as_of: datetime,
    store: CoverageWriter,
    known: Callable[[str], SecurityHit | None],
    resolve: Callable[[str], ResolvedSecurity | None],
    budget: timedelta = RESOLVE_BUDGET,
    timer: Callable[[], float] = time.monotonic,
) -> CoverageUpdate:
    """Die Menge von portfolio als neue Fassung, sofern sie sich aendert.

    ``known``: die eigenen Wertpapiere (``SecurityCatalog.get``); ``resolve``: FIRDS und OpenFIGI
    (``SecurityService.resolve``, speichert das Wertpapier). Wirft nur, wenn die Abdeckung selbst
    nicht lesbar oder schreibbar ist; dann stellt der Bus erneut zu.
    """
    newest = store.coverage_as_of()
    if newest is not None and as_of < newest:
        log.info(
            "Abdeckung von %s ist aelter als die Fassung von %s - uebersprungen", as_of, newest
        )
        return CoverageUpdate(changed=False)
    current = {item.isin: item for item in store.coverage()}
    deadline = timer() + budget.total_seconds()
    items: list[CoverageItem] = []
    added: list[CoverageItem] = []
    unresolved: list[str] = []
    for isin in sorted(set(isins)):
        item = current.get(isin)
        if item is None or item.price_symbol is None:
            ask = resolve if timer() < deadline else _no_source
            fresh = _new_item(isin, known, ask)
            if fresh is None and item is None:
                unresolved.append(isin)
                continue
            if fresh is not None and fresh != item:
                added.append(fresh)
                item = fresh
        assert item is not None
        items.append(item)
    if unresolved:
        log.warning(
            "Abdeckung: %d ISINs nicht aufgeloest, fehlen bis zur naechsten Meldung: %s",
            len(unresolved),
            ", ".join(unresolved),
        )
    changed = store.write_coverage(items, source=PORTFOLIO_SOURCE, at=as_of)
    log.info(
        "Abdeckung von portfolio: %d Wertpapiere, %d neu, %s",
        len(items),
        len(added),
        "neue Fassung" if changed else "unveraendert",
    )
    return CoverageUpdate(changed, added if changed else [], unresolved)


def _no_source(isin: str) -> ResolvedSecurity | None:
    """Nach dem Budget: nur noch die eigenen Wertpapiere."""
    del isin
    return None


def _new_item(
    isin: str,
    known: Callable[[str], SecurityHit | None],
    resolve: Callable[[str], ResolvedSecurity | None],
) -> CoverageItem | None:
    """Eigene Wertpapiere mit Listings zuerst, sonst FIRDS und OpenFIGI; ein bekanntes ohne
    Listings bleibt ohne Symbol (Stammdaten und Bundesanleihen gehen ueber die ISIN)."""
    try:
        hit = known(isin)
    except Exception:
        log.warning("Eigene Wertpapiere nicht lesbar (%s)", isin, exc_info=True)
        hit = None
    if hit is not None and hit.listings:
        return coverage_item(isin, hit.asset_class, hit.listings, name=hit.name)
    try:
        resolved = resolve(isin)
    except ValueError as e:  # falsche Pruefziffer: kommt so nie zurueck
        log.warning("Abdeckung: %s", e)
        return None
    except Exception:
        log.warning("%s nicht aufgeloest", isin, exc_info=True)
        resolved = None
    if resolved is not None:
        master = resolved.master
        return coverage_item(isin, master.asset_class, resolved.listings, name=master.name)
    if hit is not None:
        return coverage_item(isin, hit.asset_class, (), name=hit.name)
    return None


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
