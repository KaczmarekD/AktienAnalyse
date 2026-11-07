"""Wertpapiere suchen und aufloesen (D2.1, WP-02, WP-03, WP-04, WP-07).

- **Suche:** eigene Wertpapiere zuerst, dann OpenFIGI (ISIN, WKN), dann die Suche von Yahoo
  (Name, Symbol). Faellt eine Quelle aus, kommen die Treffer der anderen. Treffer bleiben 24 h im
  Speicher (Tippen im Suchfeld trifft so keine Rate-Limits), Fehler nicht. Die Suche schreibt
  nichts.
- **Aufloesung:** Stammdaten aus ESMA FIRDS (Name, Anlageklasse, LEI, Anleihe-Ausstattung),
  Listings aus OpenFIGI. Fehlt FIRDS, nennt OpenFIGI Name und Anlageklasse. Gespeichert werden
  Wertpapier, Stammdaten und Listings. Ohne beide Quellen ist die ISIN unbekannt.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

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

log = logging.getLogger(__name__)

CACHE_TTL = timedelta(hours=24)
CACHE_SIZE = 2000  # Eintraege je Speicher; danach fallen die aeltesten weg
SEARCH_LIMIT = 10


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
    ) -> None:
        self._catalog = catalog
        self._lookup = lookup
        self._text = text
        self._master = master
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
        master = self._safe(self._master.master, isin, "ESMA FIRDS")
        found = self._safe(self._lookup.lookup, isin, "OpenFIGI")
        if master is None and found is None:
            return None
        if master is None:
            assert found is not None
            master = SecurityMaster(
                isin=isin, name=found.name, asset_class=found.asset_class, source="openfigi"
            )
        listings = found.listings if found is not None else ()
        self._catalog.save(master, listings, at=self._clock())
        resolved = ResolvedSecurity(master, listings, choose_listing(listings, preferred=symbol))
        self._remember(self._resolved, (isin, symbol), resolved)
        return resolved

    @staticmethod
    def _safe[T](fetch: Callable[[str], T | None], isin: str, source: str) -> T | None:
        try:
            return fetch(isin)
        except Exception:
            log.warning("%s fuer %s nicht erreichbar", source, isin, exc_info=True)
            return None
