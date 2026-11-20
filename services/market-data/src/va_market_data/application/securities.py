"""Wertpapiere suchen und aufloesen (D2.1, WP-02, WP-03, WP-04, WP-07).

- **Suche:** eigene Wertpapiere zuerst, dann OpenFIGI (ISIN, WKN), dann die Suche von Yahoo
  (Name, Symbol). Faellt eine Quelle aus, kommen die Treffer der anderen. Treffer bleiben 24 h im
  Speicher (Tippen im Suchfeld trifft so keine Rate-Limits), Fehler nicht. Die Suche schreibt
  nichts.
- **Aufloesung:** Stammdaten aus ESMA FIRDS (Name, Anlageklasse, LEI, Anleihe-Ausstattung),
  Listings aus OpenFIGI. Fehlt FIRDS, nennt OpenFIGI Name und Anlageklasse. Gespeichert werden
  Wertpapier, Stammdaten und Listings. Ohne beide Quellen ist die ISIN unbekannt. Seit D2.4
  bringt ein ETF seine zuletzt gespeicherte Zusammensetzung mit.
- **Aktualisierung im Wochenlauf (D2.4, ``refresh_securities``):** Stammdaten und ETF-Daten
  aller Wertpapiere der Abdeckung, fuer ``marketdata.securities.updated``.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Protocol

from ..domain.etf import EtfComposition
from ..domain.securities import (
    AssetClass,
    Listing,
    SecurityHit,
    SecurityMaster,
    choose_listing,
    classify_query,
    isin_from_wkn,
    valid_isin,
)
from ..domain.universe import SourceError

if TYPE_CHECKING:
    from ..domain.coverage import CoverageItem

log = logging.getLogger(__name__)

CACHE_TTL = timedelta(hours=24)
CACHE_SIZE = 2000  # Eintraege je Speicher; danach fallen die aeltesten weg
SEARCH_LIMIT = 10
# Eine vollstaendige Liste geht vor einer unvollstaendigen, gespeichert bis zu diesem Alter
COMPLETE_STAYS = timedelta(days=31)
# Hoechstens so lange fragt die Aktualisierung im Wochenlauf die Quellen; danach gilt, was
# gespeichert ist. Universum und Abdeckung brauchen rund 15 Minuten, der Watchdog des web-api
# meldet einen Abruf nach WATCHDOG_FETCH_MINUTES (Standard 45) als gescheitert. Wer diese Grenze
# senkt, muss Abruf plus dieses Budget darunter halten (Runbook, Abschnitt Watchdog).
REFRESH_BUDGET = timedelta(minutes=10)


@dataclass(frozen=True)
class LookupResult:
    """Was OpenFIGI zu einer ISIN weiss."""

    name: str
    asset_class: AssetClass
    listings: tuple[Listing, ...]


@dataclass(frozen=True)
class ResolvedSecurity:
    master: SecurityMaster
    listings: tuple[Listing, ...]
    listing: Listing | None  # fuer den Datenabruf (WP-03)
    etf: EtfComposition | None = None  # D2.4: nur bei ETFs, sofern bekannt


@dataclass(frozen=True)
class RefreshResult:
    """Stammdaten der Abdeckung (D2.4); ``missing``: ISINs ohne Stammdaten."""

    securities: list[ResolvedSecurity] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)


class SecurityCatalog(Protocol):
    """Die eigenen Wertpapiere im Schema ``market_data``."""

    def find(self, text: str, limit: int) -> list[SecurityHit]: ...

    def get(self, isin: str) -> SecurityHit | None: ...

    def save(
        self, master: SecurityMaster, listings: tuple[Listing, ...], *, at: datetime
    ) -> None: ...


class ListingLookup(Protocol):
    """ISIN -> Name, Anlageklasse, Listings (OpenFIGI). Wirft bei Ausfall."""

    def lookup(self, isin: str) -> LookupResult | None: ...


class TextSearch(Protocol):
    """Name oder Symbol -> Treffer ohne ISIN (Yahoo). Wirft bei Ausfall."""

    def search(self, text: str, limit: int) -> list[SecurityHit]: ...


class MasterSource(Protocol):
    """ISIN -> Stammdaten (ESMA FIRDS). Wirft bei Ausfall."""

    def master(self, isin: str) -> SecurityMaster | None: ...


class CompositionReader(Protocol):
    """Gespeicherte ETF-Zusammensetzungen (D2.4)."""

    def latest_composition(
        self, isin: str, *, complete_only: bool = False
    ) -> EtfComposition | None:
        """Der juengste Stand; ``complete_only``: der juengste mit allen Positionen."""
        ...


class CompositionStore(CompositionReader, Protocol):
    def write_composition(self, composition: EtfComposition, *, at: datetime) -> bool:
        """``False``, wenn derselbe Stand dieser Quelle schon gespeichert ist."""
        ...


class EtfSource(Protocol):
    """ISIN (und Symbol) -> Zusammensetzung eines Fonds; ``None``, wenn die Quelle ihn nicht
    kennt. Wirft bei Ausfall."""

    name: str

    def composition(self, isin: str, symbol: str | None) -> EtfComposition | None: ...


class RefreshCatalog(Protocol):
    """Was die Aktualisierung vom Katalog braucht."""

    def get(self, isin: str) -> SecurityHit | None: ...

    def master(self, isin: str) -> SecurityMaster | None: ...

    def save(
        self, master: SecurityMaster, listings: tuple[Listing, ...], *, at: datetime
    ) -> None: ...


def _utcnow() -> datetime:
    return datetime.now(UTC)


class SecurityService:
    def __init__(
        self,
        *,
        catalog: SecurityCatalog,
        lookup: ListingLookup,
        text: TextSearch,
        master: MasterSource,
        clock: Callable[[], datetime] = _utcnow,
        cache_ttl: timedelta = CACHE_TTL,
        limit: int = SEARCH_LIMIT,
        compositions: CompositionReader | None = None,
    ) -> None:
        self._catalog = catalog
        self._lookup = lookup
        self._text = text
        self._master = master
        self._compositions = compositions
        self._clock = clock
        self._ttl = cache_ttl
        self._limit = limit
        self._cache: dict[tuple[str, str], tuple[datetime, list[SecurityHit]]] = {}
        self._resolved: dict[tuple[str, str | None], tuple[datetime, ResolvedSecurity]] = {}
        self._lock = threading.Lock()  # RPC-Anfragen laufen in Threads

    def _remember[K, V](self, store: dict[K, tuple[datetime, V]], key: K, value: V) -> None:
        """Merkt sich ``value``; abgelaufene Eintraege fallen weg, hoechstens ``CACHE_SIZE``."""
        now = self._clock()
        with self._lock:
            for old in [k for k, (at, _) in store.items() if now - at >= self._ttl]:
                del store[old]
            while len(store) >= CACHE_SIZE:
                del store[next(iter(store))]  # in Einfuegereihenfolge: der aelteste
            store[key] = (now, value)

    def _recall[K, V](self, store: dict[K, tuple[datetime, V]], key: K) -> V | None:
        with self._lock:
            found = store.get(key)
        if found is None or self._clock() - found[0] >= self._ttl:
            return None
        return found[1]

    # --- Suche ------------------------------------------------------------------------

    def search(self, query: str) -> list[SecurityHit]:
        parsed = classify_query(query)
        if parsed is None:
            return []
        key = (parsed.kind, parsed.value.lower())
        cached = self._recall(self._cache, key)
        if cached is not None:
            return list(cached)
        if parsed.kind == "text":
            hits, complete = self._search_text(parsed.value)
        else:
            isin = parsed.value if parsed.kind == "isin" else isin_from_wkn(parsed.value)
            hits, complete = self._search_isin(isin)
            if parsed.kind == "wkn" and complete and not hits:
                # Auch ein Symbol kann wie eine WKN aussehen (sechs Zeichen mit Ziffer)
                hits, complete = self._search_text(parsed.value)
        if complete:
            self._remember(self._cache, key, hits)
        return hits

    def _search_isin(self, isin: str) -> tuple[list[SecurityHit], bool]:
        try:
            own = self._catalog.get(isin)
        except Exception:
            log.warning("Eigene Wertpapiere nicht lesbar", exc_info=True)
            own = None
        if own is not None:
            return [own], True
        try:
            found = self._lookup.lookup(isin)
        except Exception:
            log.warning("OpenFIGI fuer %s nicht erreichbar", isin, exc_info=True)
            return [], False
        if found is None:
            return [], True
        return [SecurityHit(isin, found.name, found.asset_class, found.listings, "openfigi")], True

    def _search_text(self, text: str) -> tuple[list[SecurityHit], bool]:
        try:
            own = self._catalog.find(text, self._limit)
        except Exception:
            log.warning("Eigene Wertpapiere nicht lesbar", exc_info=True)
            return [], False
        try:
            external = self._text.search(text, self._limit)
        except Exception:
            log.warning("Suche von Yahoo nicht erreichbar", exc_info=True)
            return own, False
        known = {listing.symbol for hit in own for listing in hit.listings if listing.symbol}
        extra = [
            hit
            for hit in external
            if not any(listing.symbol in known for listing in hit.listings if listing.symbol)
        ]
        # Ohne Treffer von Yahoo nicht behalten: yfinance meldet manche Fehler als leere Liste
        return (own + extra)[: self._limit], bool(external)

    # --- Aufloesung -------------------------------------------------------------------

    def resolve(self, isin: str, symbol: str | None = None) -> ResolvedSecurity | None:
        """Stammdaten und Listings holen und speichern; ``None`` fuer eine unbekannte ISIN.

        Wirft ``ValueError`` bei falscher Pruefziffer.
        """
        if not valid_isin(isin):
            msg = f"Keine gueltige ISIN: {isin!r}"
            raise ValueError(msg)
        # Einen Tag im Speicher: Jeder Abruf der Seite fragte sonst FIRDS und OpenFIGI neu
        # (ohne Schluessel 25 Anfragen je Minute)
        cached = self._recall(self._resolved, (isin, symbol))
        if cached is not None:
            return cached
        master = _safe(self._master.master, isin, "ESMA FIRDS")
        found = _safe(self._lookup.lookup, isin, "OpenFIGI")
        if master is None and found is None:
            return None
        if master is None:
            assert found is not None
            master = SecurityMaster(
                isin=isin, name=found.name, asset_class=found.asset_class, source="openfigi"
            )
        listings = found.listings if found is not None else ()
        self._catalog.save(master, listings, at=self._clock())
        etf = None
        if master.asset_class == "etf" and self._compositions is not None:
            etf = stored_composition(self._compositions, isin, today=self._clock().date())
        resolved = ResolvedSecurity(
            master, listings, choose_listing(listings, preferred=symbol), etf
        )
        self._remember(self._resolved, (isin, symbol), resolved)
        return resolved


def _safe[T](fetch: Callable[[str], T | None], isin: str, source: str) -> T | None:
    try:
        return fetch(isin)
    except Exception:
        log.warning("%s fuer %s nicht erreichbar", source, isin, exc_info=True)
        return None


# --- Aktualisierung im Wochenlauf (D2.4) ------------------------------------------------


def stored_composition(
    store: CompositionReader, isin: str, *, today: date
) -> EtfComposition | None:
    """Die gespeicherte Zusammensetzung, die gilt: die juengste vollstaendige, wenn sie hoechstens
    ``COMPLETE_STAYS`` alt ist (iShares faellt eine Woche aus, yfinance kennt nur zehn
    Positionen), sonst die juengste. Ein Lesefehler ergibt ``None``."""
    complete = _safe(
        lambda i: store.latest_composition(i, complete_only=True), isin, "Gespeicherte ETF-Daten"
    )
    if complete is not None and today - complete.as_of <= COMPLETE_STAYS:
        return complete
    return _safe(store.latest_composition, isin, "Gespeicherte ETF-Daten")


class _Budget:
    """Zeitbudget der Aktualisierung; meldet die Ueberschreitung einmal."""

    def __init__(self, budget: timedelta, timer: Callable[[], float]) -> None:
        self._seconds = budget.total_seconds()
        self._timer = timer
        self._start = timer()
        self._reported = False

    def left(self) -> bool:
        if self._timer() - self._start < self._seconds:
            return True
        if not self._reported:
            log.warning(
                "Stammdaten: Zeitbudget von %s erschoepft - fuer den Rest gelten die gespeicherten",
                timedelta(seconds=self._seconds),
            )
            self._reported = True
        return False


def refresh_securities(
    items: Sequence[CoverageItem],
    *,
    catalog: RefreshCatalog,
    master: MasterSource,
    etf_sources: Sequence[EtfSource],
    compositions: CompositionStore,
    clock: Callable[[], datetime] = _utcnow,
    budget: timedelta = REFRESH_BUDGET,
    timer: Callable[[], float] = time.monotonic,
) -> RefreshResult:
    """Stammdaten und ETF-Daten jedes Wertpapiers der Abdeckung; wirft nicht (WP-07).

    - Stammdaten aus FIRDS, gespeichert (der Katalog legt nur bei Aenderung eine Zeile an);
      ohne FIRDS die gespeicherten; ohne beides steht die ISIN in ``missing``.
    - ETFs: die Quellen der Reihe nach, siehe ``_composition``.
    - Nach ``budget`` fragt sie keine Quelle mehr und nimmt nur noch Gespeichertes: Haengen FIRDS
      oder iShares, wartet ``snapshot.completed`` sonst bis zum Watchdog.
    """
    now = clock()
    in_budget = _Budget(budget, timer).left
    result = RefreshResult()
    seen: set[str] = set()
    for item in items:
        if item.isin in seen:
            continue
        seen.add(item.isin)
        current = _current_master(
            item.isin, catalog=catalog, master=master, now=now, fetch=in_budget()
        )
        if current is None:
            result.missing.append(item.isin)
            continue
        hit = _safe(catalog.get, item.isin, "Gespeicherte Listings")
        listings = hit.listings if hit is not None else ()
        etf = None
        if "etf" in (current.asset_class, item.asset_class):
            etf = _composition(item, etf_sources, compositions, now=now, in_budget=in_budget)
        result.securities.append(
            ResolvedSecurity(
                current, listings, choose_listing(listings, preferred=item.price_symbol), etf
            )
        )
    log.info(
        "Stammdaten: %d Wertpapiere, %d ohne Stammdaten",
        len(result.securities),
        len(result.missing),
    )
    return result


def _current_master(
    isin: str, *, catalog: RefreshCatalog, master: MasterSource, now: datetime, fetch: bool
) -> SecurityMaster | None:
    fresh = _safe(master.master, isin, "ESMA FIRDS") if fetch else None
    if fresh is None:
        return _safe(catalog.master, isin, "Gespeicherte Stammdaten")
    try:
        catalog.save(fresh, (), at=now)
    except Exception:
        log.warning("Stammdaten von %s nicht gespeichert", isin, exc_info=True)
    return fresh


def _composition(
    item: CoverageItem,
    sources: Sequence[EtfSource],
    store: CompositionStore,
    *,
    now: datetime,
    in_budget: Callable[[], bool],
) -> EtfComposition | None:
    """Die erste vollstaendige frische Zusammensetzung; sonst eine gespeicherte vollstaendige bis
    ``COMPLETE_STAYS``; sonst die frische unvollstaendige; sonst die zuletzt gespeicherte. Jede
    frische wird gespeichert."""
    fresh: EtfComposition | None = None
    for source in sources:
        if not in_budget():
            break
        try:
            found = source.composition(item.isin, item.price_symbol)
        except SourceError as e:  # erwartbar (Struktur, Alter, Fondsliste weg): ohne Traceback
            log.warning("%s fuer %s: %s", source.name, item.isin, e)
            continue
        except Exception:
            log.warning("%s fuer %s nicht erreichbar", source.name, item.isin, exc_info=True)
            continue
        if found is None:
            continue
        try:
            store.write_composition(found, at=now)
        except Exception:
            log.warning("ETF-Daten von %s nicht gespeichert", item.isin, exc_info=True)
        if found.complete:
            return found
        fresh = fresh or found
    stored = stored_composition(store, item.isin, today=now.date())
    if stored is not None and stored.complete:
        return stored
    return fresh or stored
