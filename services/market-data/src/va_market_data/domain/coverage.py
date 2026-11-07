"""Abdeckung (D2.2, WP-05, WP-09; docs/architecture/depot/wertpapiere.md#abdeckung-und-abrufe).

Die Abdeckung ist die Menge der Wertpapiere, fuer die market-data ausser dem Referenzuniversum
Daten holt: alles, was in einem Depot oder einer Beobachtungsliste steht. market-data kennt nur ISIN,
Anlageklasse und Symbole, nie Nutzer oder Mengen.

- Fundamentaldaten vom Heimat-Listing (dort berichtet das Unternehmen, Yahoo hat die Abschluesse),
  Kurse von Xetra, falls vorhanden; deutsche Aktien beides von Xetra.
- Im Wochenlauf nur Aktien ausserhalb des Referenzuniversums (nach Symbol und ISIN): Ein Depot-Titel
  aus DAX/MDAX hat seine Daten schon.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable, Sequence
from dataclasses import dataclass

from va_contracts.securities import AssetClass

from .securities import XETRA, Listing
from .universe import Ticker

# Kein Referenzuniversum: Platzhalter fuer IdentityV1.index (Pflichtfeld, Contract additiv)
COVERAGE_INDEX = "-"
# Boersenplaetze in Deutschland (OpenFIGI-Codes); keiner davon ist das Heimat-Listing einer
# auslaendischen Aktie
GERMAN_EXCHANGES = frozenset({"GY", "GF", "GD", "GM", "GS", "GH", "GB", "GR", "GI"})


@dataclass(frozen=True)
class CoverageItem:
    isin: str
    asset_class: AssetClass
    fundamentals_symbol: str | None  # nur Aktien: dort holt der Wochenlauf die Kennzahlen
    price_symbol: str | None  # Tageskurse (D2.3); Anleihen oft ohne
    name: str | None = None


def _is_xetra(listing: Listing) -> bool:
    return listing.exchange == XETRA or (listing.symbol or "").endswith(".DE")


def coverage_symbols(
    isin: str, asset_class: AssetClass, listings: Sequence[Listing]
) -> tuple[str | None, str | None]:
    """(Symbol fuer Fundamentaldaten, Symbol fuer Kurse) aus den Listings eines Wertpapiers."""
    with_symbol = [listing for listing in listings if listing.symbol]
    xetra = next((listing.symbol for listing in with_symbol if _is_xetra(listing)), None)
    home = next(
        (listing.symbol for listing in with_symbol if listing.exchange not in GERMAN_EXCHANGES),
        None,
    )
    first = with_symbol[0].symbol if with_symbol else None
    price = xetra or home or first
    if asset_class != "equity":
        return None, price
    fundamentals = xetra if isin.startswith("DE") and xetra else (home or xetra or first)
    return fundamentals, price


def coverage_tickers(
    items: Iterable[CoverageItem],
    *,
    universe_symbols: Collection[str],
    universe_isins: Collection[str],
) -> list[Ticker]:
    """Die Aktien der Abdeckung, die der Wochenlauf zusaetzlich abruft, je Symbol einmal."""
    tickers: list[Ticker] = []
    seen: set[str] = set()
    for item in items:
        symbol = item.fundamentals_symbol
        if item.asset_class != "equity" or not symbol:
            continue
        if symbol in universe_symbols or item.isin in universe_isins or symbol in seen:
            continue
        seen.add(symbol)
        tickers.append(Ticker(symbol, item.name or item.isin, COVERAGE_INDEX, item.isin))
    return tickers
