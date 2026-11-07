"""OpenFIGI: ISIN -> Yahoo-Symbol ueber das Xetra-Listing (fuer Neuaufnahmen ohne CSV-Eintrag).

Ohne API-Key, hoechstens 10 ISINs je Anfrage. Seit D2.1 auch Name, Anlageklasse und Listings je
ISIN fuer die Suche nach Wertpapieren (``OpenFigiLookup``).
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Any

import requests
from tenacity import retry, stop_after_attempt, wait_exponential

from ..application.securities import LookupResult
from ..domain.securities import Listing, asset_class_from_figi, yahoo_symbol
from ..domain.universe import YAHOO_SUFFIX

log = logging.getLogger(__name__)

OPENFIGI_URL = "https://api.openfigi.com/v3/mapping"
OPENFIGI_EXCHANGE = "GY"  # Xetra
OPENFIGI_BATCH = 10  # Limit ohne API-Key


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=2, max=20))
def openfigi_post(jobs: list[dict[str, str]], timeout: float = 30.0) -> Any:
    response = requests.post(OPENFIGI_URL, json=jobs, timeout=timeout)
    response.raise_for_status()
    return response.json()


def resolve_isins_openfigi(isins: Iterable[str], timeout: float = 30.0) -> dict[str, str]:
    """ISIN -> Yahoo-Symbol. Fehler ergeben Luecken, keine Exception."""
    isins = list(isins)
    result: dict[str, str] = {}
    for start in range(0, len(isins), OPENFIGI_BATCH):
        batch = isins[start : start + OPENFIGI_BATCH]
        jobs = [{"idType": "ID_ISIN", "idValue": i, "exchCode": OPENFIGI_EXCHANGE} for i in batch]
        try:
            answers = openfigi_post(jobs, timeout)
        except Exception as e:
            log.warning("OpenFIGI nicht erreichbar: %s", e)
            continue
        if not isinstance(answers, list):
            log.warning("OpenFIGI: unerwartete Antwort %r", answers)
            continue
        for isin, answer in zip(batch, answers, strict=False):
            ticker = _figi_ticker(answer)
            if ticker:
                result[isin] = f"{ticker}{YAHOO_SUFFIX}"
    return result


def _figi_ticker(answer: Any) -> str | None:
    data = answer.get("data") if isinstance(answer, dict) else None
    if not isinstance(data, list) or not data or not isinstance(data[0], dict):
        return None
    ticker = data[0].get("ticker")
    return ticker if isinstance(ticker, str) and ticker else None


# --- D2.1: Listings je ISIN fuer Suche und Aufloesung (Port ``ListingLookup``) -----------

MAX_LISTINGS = 10  # ohne exchCode liefert OpenFIGI bis zu 300 Listings je Aktie


def lookup_from_figi(*answers: Any) -> LookupResult | None:
    """Antworten von OpenFIGI (zuerst die mit ``exchCode`` Xetra, dann die ohne) -> Name,
    Anlageklasse und Listings. Nur Listings mit Yahoo-Symbol, ausser es gibt keines (Anleihe)."""
    entries = [
        entry
        for answer in answers
        if isinstance(answer, dict) and isinstance(answer.get("data"), list)
        for entry in answer["data"]
        if isinstance(entry, dict)
    ]
    if not entries:
        return None
    first = entries[0]
    listings: list[Listing] = []
    seen: set[tuple[str | None, str | None]] = set()
    for entry in entries:
        ticker, exchange = entry.get("ticker"), entry.get("exchCode")
        symbol = yahoo_symbol(ticker, exchange)
        key = (symbol, None if symbol else exchange)
        if key in seen:
            continue
        seen.add(key)
        listings.append(Listing(symbol=symbol, ticker=ticker, exchange=exchange))
    with_symbol = [listing for listing in listings if listing.symbol]
    return LookupResult(
        name=str(first.get("name") or first.get("ticker") or ""),
        asset_class=asset_class_from_figi(first.get("securityType2")),
        listings=tuple((with_symbol or listings)[:MAX_LISTINGS]),
    )


class OpenFigiLookup:
    """``ListingLookup`` ueber OpenFIGI, ohne API-Key. Wirft bei Ausfall.

    Ein Versuch mit kurzem Timeout, ohne die Wiederholungen von ``openfigi_post``: Die Anfrage kommt
    per Request/Reply aus dem UI, das web-api wartet nicht laenger, und die Anfragen an market-data
    laufen nacheinander.
    """

    def __init__(self, *, timeout: float = 8.0) -> None:
        self._timeout = timeout

    def lookup(self, isin: str) -> LookupResult | None:
        jobs = [
            {"idType": "ID_ISIN", "idValue": isin, "exchCode": OPENFIGI_EXCHANGE},
            {"idType": "ID_ISIN", "idValue": isin},
        ]
        response = requests.post(OPENFIGI_URL, json=jobs, timeout=self._timeout)
        response.raise_for_status()
        answers = response.json()
        if not isinstance(answers, list):
            msg = f"OpenFIGI: unerwartete Antwort {answers!r}"
            raise TypeError(msg)
        return lookup_from_figi(*answers)
