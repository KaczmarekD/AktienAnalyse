"""Quelle iShares: Holdings der ETFs EXS1 (DAX) und EXS3 (MDAX).

Liefert Emittententicker und ISIN; ``ticker + ".DE"`` ist das Yahoo-Symbol. Die API ist
undokumentiert und brach im September 2026 schon einmal still weg (HTML mit HTTP 200).
Bei einer Umbenennung durch den Anbieter nur die Konstanten anpassen.

Rechtliches: kein ausdruecklich erlaubter automatisierter Abruf; robots.txt sperrt den
Pfad nicht. Privat, 1x pro Woche.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from ..application.ports import LiveUniverse
from ..domain.universe import (
    YAHOO_SUFFIX,
    SourceError,
    Ticker,
    UniverseConfig,
    check_count,
)
from .http import http_get

ISHARES_URL = (
    "https://www.blackrock.com/varnish-api/uk-retail01-product-data/product-data/api/v2/"
    "get-product-data"
)
ISHARES_PARAMS = {
    "appType": "PRODUCT_PAGE",
    "appSubType": "ISHARES",
    "targetSite": "de-ishares-v2",
    "locale": "de_DE",
    "component": "holdings",
    "userType": "individual",
}
ISHARES_PORTFOLIO_IDS = {"DAX": "251464", "MDAX": "251845"}  # EXS1, EXS3
ISHARES_EQUITY_CLASS = "Aktien"


def fetch_ishares_json(index: str, timeout: float) -> dict[str, Any]:
    params = {**ISHARES_PARAMS, "portfolioId": ISHARES_PORTFOLIO_IDS[index]}
    response = http_get(ISHARES_URL, params=params, timeout=timeout)
    try:
        return response.json()
    except ValueError as e:
        msg = f"iShares {index}: kein JSON ({e})"
        raise SourceError(msg) from e


def parse_ishares(
    payload: dict[str, Any],
    index: str,
    known_names: dict[str, str],
    cfg: UniverseConfig,
    today: date,
) -> tuple[list[Ticker], date]:
    """Spaltenweise iShares-Antwort -> Ticker. Nur ``assetClass == "Aktien"``."""
    try:
        points = payload["componentsByNameMap"]["holdings"]["containersByNameMap"]["all"][
            "dataPointsByNameMap"
        ]
        columns = zip(
            points["ticker"]["value"],
            points["isin"]["value"],
            points["issueName"]["value"],
            points["assetClass"]["value"],
            strict=True,
        )
        as_of = datetime.strptime(str(points["asOfDate"]["value"]), "%Y%m%d").date()
    except (KeyError, TypeError, ValueError) as e:
        msg = f"iShares {index}: unerwartete Struktur ({e!r})"
        raise SourceError(msg) from e

    age = (today - as_of).days
    if not -1 <= age <= cfg.max_age_days:
        msg = f"iShares {index}: Stichtag {as_of} unplausibel ({age} Tage alt)"
        raise SourceError(msg)

    tickers = [
        Ticker(
            symbol=f"{ticker}{YAHOO_SUFFIX}",
            name=known_names.get(isin) or str(issue_name),
            index=index,
            isin=isin,
        )
        for ticker, isin, issue_name, asset_class in columns
        if asset_class == ISHARES_EQUITY_CLASS and ticker and isin
    ]
    check_count(len(tickers), index, "iShares", cfg)
    return tickers, as_of


class IsharesSource:
    """``UniverseSource``: alle Indizes aus iShares, Stichtag = der aelteste der Indizes."""

    name = "iShares"

    def load(self, fallback: list[Ticker], cfg: UniverseConfig, today: date) -> LiveUniverse:
        known_names = {t.isin: t.name for t in fallback if t.isin}
        tickers: list[Ticker] = []
        as_of_dates: list[date] = []
        for index in cfg.expected_counts:
            index_tickers, as_of = parse_ishares(
                fetch_ishares_json(index, cfg.timeout), index, known_names, cfg, today
            )
            tickers.extend(index_tickers)
            as_of_dates.append(as_of)
        return LiveUniverse(tickers=tickers, as_of=min(as_of_dates))
