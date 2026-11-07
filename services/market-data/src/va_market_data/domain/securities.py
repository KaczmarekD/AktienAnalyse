"""Wertpapiere: Aktien, ETFs, Anleihen ueber die ISIN (D2.1, docs/architecture/depot/wertpapiere.md).

Rein, ohne Ein-/Ausgabe. Die Quellen (OpenFIGI, ESMA FIRDS, Yahoo) liefern Rohdaten, die Adapter
bilden sie auf diese Typen ab.

- WP-01: Ein Wertpapier ist ueber die ISIN eindeutig. WKN und Symbol sind Zusatzangaben.
- WP-03: Fuer den Datenabruf gilt Xetra, sonst die Heimatboerse; ein gewaehltes Listing geht vor.
- Anlageklasse aus dem CFI-Code (ISO 10962, erste Stelle), ersatzweise aus OpenFIGI.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Literal, get_args

from va_contracts.securities import AssetClass, valid_isin

QueryKind = Literal["isin", "wkn", "text"]
ASSET_CLASSES: tuple[str, ...] = get_args(AssetClass)

MIN_QUERY_LENGTH = 3  # das UI sucht erst ab drei Zeichen (wertpapiere.md, Suche)
# WKN: sechs Zeichen aus Ziffern und Grossbuchstaben ohne I und O
WKN_PATTERN = re.compile(r"[0-9A-HJ-NP-Z]{6}")
XETRA = "GY"  # OpenFIGI-Code fuer Xetra

# CFI-Code, erste Stelle: E Aktien, C Fonds (auch ETF), D Schuldtitel
_CFI_CLASSES: dict[str, AssetClass] = {"E": "equity", "C": "etf", "D": "bond"}
# OpenFIGI ``securityType2``
_FIGI_CLASSES: dict[str, AssetClass] = {
    "Common Stock": "equity",
    "Preference": "equity",
    "Depositary Receipt": "equity",
    "Mutual Fund": "etf",
    "ETP": "etf",
    "Govt": "bond",
    "Corp": "bond",
    "Muni": "bond",
}
# OpenFIGI-Boersencode -> Endung des Yahoo-Symbols; ohne Eintrag kein Yahoo-Symbol
EXCHANGE_SUFFIX: dict[str, str] = {
    "GY": ".DE",  # Xetra
    "GF": ".F",  # Frankfurt
    "GD": ".DU",  # Duesseldorf
    "GM": ".MU",  # Muenchen
    "GS": ".SG",  # Stuttgart
    "GH": ".HM",  # Hamburg
    "GB": ".BE",  # Berlin
    "US": "",
    "UN": "",  # NYSE
    "UW": "",  # Nasdaq
    "LN": ".L",
    "NA": ".AS",
    "FP": ".PA",
    "SW": ".SW",
    "IM": ".MI",
    "SM": ".MC",
    "BB": ".BR",
    "AV": ".VI",
    "DC": ".CO",
    "SS": ".ST",
    "FH": ".HE",
    "NO": ".OL",
    "ID": ".IR",
    "PL": ".LS",
}

__all__ = [
    "ASSET_CLASSES",
    "MIN_QUERY_LENGTH",
    "AssetClass",
    "BondTerms",
    "Listing",
    "Query",
    "SecurityHit",
    "SecurityMaster",
    "asset_class_from_cfi",
    "asset_class_from_figi",
    "choose_listing",
    "classify_query",
    "floating_rate",
    "isin_from_wkn",
    "looks_like_wkn",
    "valid_isin",
    "yahoo_symbol",
]


@dataclass(frozen=True)
class Listing:
    symbol: str | None  # Yahoo-Symbol, falls es eines gibt
    ticker: str | None = None
    exchange: str | None = None
    currency: str | None = None


@dataclass(frozen=True)
class SecurityHit:
    """Ein Treffer der Suche; Treffer der Yahoo-Suche haben keine ISIN."""

    isin: str | None
    name: str
    asset_class: AssetClass
    listings: tuple[Listing, ...]
    source: str  # catalog, openfigi, yahoo


@dataclass(frozen=True)
class BondTerms:
    coupon: float | None = None
    maturity: date | None = None
    denomination: float | None = None
    seniority: str | None = None
    floating: bool = False


@dataclass(frozen=True)
class SecurityMaster:
    """Stammdaten je Wertpapier (WP-04), aus ESMA FIRDS oder ersatzweise aus OpenFIGI."""

    isin: str
    name: str
    asset_class: AssetClass
    currency: str | None = None
    lei: str | None = None
    cfi: str | None = None
    bond: BondTerms | None = None
    source: str = "firds"  # firds, openfigi (Ersatz ohne FIRDS)


@dataclass(frozen=True)
class Query:
    kind: QueryKind
    value: str


def looks_like_wkn(value: str) -> bool:
    return WKN_PATTERN.fullmatch(value) is not None


def isin_from_wkn(wkn: str) -> str:
    """Deutsche ISIN aus der WKN: ``DE000`` + WKN + Pruefziffer. Fuer auslaendische Papiere mit
    WKN stimmt das nicht; die Suche findet dann nichts und faellt auf Text zurueck."""
    stem = f"DE000{wkn}"
    for digit in "0123456789":
        if valid_isin(stem + digit):
            return stem + digit
    msg = f"Keine ISIN zur WKN {wkn}"  # pragma: no cover - zu jedem Stamm passt genau eine Ziffer
    raise ValueError(msg)


def classify_query(raw: str) -> Query | None:
    """ISIN (mit gueltiger Pruefziffer), WKN oder Text; ``None`` unter drei Zeichen."""
    text = " ".join(raw.split())
    if len(text) < MIN_QUERY_LENGTH:
        return None
    upper = text.upper()
    if valid_isin(upper):
        return Query("isin", upper)
    if looks_like_wkn(upper) and any(c.isdigit() for c in upper):
        return Query("wkn", upper)
    return Query("text", text)


def asset_class_from_cfi(cfi: str | None) -> AssetClass | None:
    if not cfi:
        return None
    return _CFI_CLASSES.get(cfi[0].upper(), "other")


def asset_class_from_figi(security_type2: str | None) -> AssetClass:
    return _FIGI_CLASSES.get(security_type2 or "", "other")


def floating_rate(cfi: str | None) -> bool:
    """Dritte Stelle des CFI-Codes einer Anleihe: V variabel (auch kuendbare Stufenzinsen)."""
    if not cfi or len(cfi) < 3:
        return False
    return cfi[0].upper() == "D" and cfi[2].upper() == "V"


def yahoo_symbol(ticker: str | None, exchange: str | None) -> str | None:
    if not ticker or exchange not in EXCHANGE_SUFFIX or " " in ticker:
        return None
    return f"{ticker}{EXCHANGE_SUFFIX[exchange]}"


def choose_listing(listings: Sequence[Listing], preferred: str | None = None) -> Listing | None:
    """Das Listing fuer den Datenabruf (WP-03): gewaehlt, sonst Xetra, sonst das erste mit
    Yahoo-Symbol, sonst das erste."""
    if not listings:
        return None
    if preferred:
        for listing in listings:
            if listing.symbol == preferred:
                return listing
    for listing in listings:
        if listing.exchange == XETRA or (listing.symbol or "").endswith(".DE"):
            return listing
    return next((listing for listing in listings if listing.symbol), listings[0])
