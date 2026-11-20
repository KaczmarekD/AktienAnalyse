"""Quelle iShares: Holdings der ETFs EXS1 (DAX) und EXS3 (MDAX), seit D2.4 aller iShares-Fonds.

Liefert Emittententicker und ISIN; ``ticker + ".DE"`` ist das Yahoo-Symbol. Die API ist
undokumentiert und brach im September 2026 schon einmal still weg (HTML mit HTTP 200).
Bei einer Umbenennung durch den Anbieter nur die Konstanten anpassen.

D2.4 (WP-10): Der Produkt-Screener der Website nennt alle Fonds mit ISIN, ``portfolioId`` und
Fondsdaten; dieselbe Schnittstelle wie fuer EXS1/EXS3 liefert die Positionen je ``portfolioId``.

Rechtliches: kein ausdruecklich erlaubter automatisierter Abruf; robots.txt sperrt den
Pfad nicht. Privat, 1x pro Woche.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from ..application.ports import LiveUniverse
from ..domain.etf import EtfComposition, FundFacts, Holding, composition_from_holdings
from ..domain.universe import (
    YAHOO_SUFFIX,
    SourceError,
    Ticker,
    UniverseConfig,
    check_count,
)
from .http import http_get

log = logging.getLogger(__name__)

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

# D2.4: Fondsliste der Website (rund 1.330 Fonds, 3,8 MB), Schluessel ist die portfolioId
ISHARES_SCREENER_URL = (
    "https://www.ishares.com/varnish-api/blk-product-screener-server/api/v1/product-screener/"
    "product-data"
)
ISHARES_SCREENER_PARAMS = {
    "language": "de",
    "country": "de",
    "userType": "individual",
    "siteName": "de-ishares-v2",
}
# Felder je Fonds im Screener; Zahlen stehen als {"d": Anzeige, "r": Wert}, fehlende als "-"
SCREENER_FIELDS = {
    "isin": "isin",
    "portfolio_id": "portfolioId",
    "name": "fundName",
    "ter": "ter",  # in Prozent
    "fund_size": "totalFundSizeInMillions",  # in Millionen der Fondswaehrung
    "currency": "seriesBaseCurrencyCode",
    "distribution": "useOfProfits",
    "effective_duration": "effectiveDuration",
}
DISTRIBUTIONS = {"thesaurierend": "accumulating", "ausschüttend": "distributing"}
# Spalten der Positionen: Feld von ``Holding`` -> Spalte bei iShares
HOLDING_FIELDS = {
    "name": "issueName",
    "weight": "holdingPercent",  # in Prozent
    "isin": "isin",
    "ticker": "ticker",
    "asset_class": "assetClass",
    "sector": "sectorName",
    "country": "countryOfRisk",
    "currency": "marketCurrencyCode",
}
ISHARES_AS_OF = "asOfDate"  # YYYYMMDD
MAX_AGE_DAYS = 31  # aelter: kein aktueller Stand (aufgeloester Fonds, kaputte Antwort)
PROVIDER = "iShares"
SOURCE = "ishares"


def fetch_ishares_json(index: str, timeout: float) -> dict[str, Any]:
    params = {**ISHARES_PARAMS, "portfolioId": ISHARES_PORTFOLIO_IDS[index]}
    response = http_get(ISHARES_URL, params=params, timeout=timeout)
    try:
        return response.json()
    except ValueError as e:
        msg = f"iShares {index}: kein JSON ({e})"
        raise SourceError(msg) from e


def _data_points(payload: Any) -> dict[str, Any]:
    """Die Spalten der Positionen: ``{Feld: {"value": [...]}}``."""
    return payload["componentsByNameMap"]["holdings"]["containersByNameMap"]["all"][
        "dataPointsByNameMap"
    ]


def parse_ishares(
    payload: dict[str, Any],
    index: str,
    known_names: dict[str, str],
    cfg: UniverseConfig,
    today: date,
) -> tuple[list[Ticker], date]:
    """Spaltenweise iShares-Antwort -> Ticker. Nur ``assetClass == "Aktien"``."""
    try:
        points = _data_points(payload)
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


# --- D2.4: Fondsdaten und Positionen aller iShares-Fonds -----------------------------------

FetchJson = Callable[[str, dict[str, str]], Any]


@dataclass(frozen=True)
class IsharesFund:
    portfolio_id: str
    facts: FundFacts


def _number(value: Any) -> float | None:
    """``{"d": "0,20", "r": 0.2}`` oder eine Zahl -> Zahl; ``"-"`` und Leeres -> ``None``."""
    if isinstance(value, Mapping):
        value = value.get("r")
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return None if text in ("", "-") else text


def funds_from_screener(payload: Any) -> dict[str, IsharesFund]:
    """Fondsliste des Screeners -> ISIN -> Fonds. Eintraege ohne ISIN oder ``portfolioId``
    fallen weg; eine andere Struktur oder eine leere Liste ist ein Fehler der Quelle."""
    if not isinstance(payload, Mapping):
        msg = f"iShares-Fondsliste: unerwartete Struktur ({type(payload).__name__})"
        raise SourceError(msg)
    funds: dict[str, IsharesFund] = {}
    f = SCREENER_FIELDS
    for key, entry in payload.items():
        if not isinstance(entry, Mapping):
            log.warning("iShares-Fondsliste: Eintrag %r ist kein Fonds, uebersprungen", key)
            continue
        isin = _text(entry.get(f["isin"]))
        portfolio_id = _text(entry.get(f["portfolio_id"]))
        if isin is None or portfolio_id is None or len(isin) != 12:
            continue
        distribution = DISTRIBUTIONS.get((_text(entry.get(f["distribution"])) or "").lower())
        funds[isin] = IsharesFund(
            portfolio_id=portfolio_id,
            facts=FundFacts(
                name=_text(entry.get(f["name"])),
                ter=_number(entry.get(f["ter"])),
                fund_size=_number(entry.get(f["fund_size"])),
                currency=_text(entry.get(f["currency"])),
                distribution=distribution,  # type: ignore[arg-type] - Werte aus DISTRIBUTIONS
                provider=PROVIDER,
                effective_duration=_number(entry.get(f["effective_duration"])),
            ),
        )
    if not funds:
        msg = "iShares-Fondsliste: keine Fonds"
        raise SourceError(msg)
    return funds


def holdings_from_payload(payload: Any) -> tuple[date, tuple[Holding, ...]]:
    """Spaltenweise Positionen eines Fonds -> (Stand, Positionen). Ohne Gewicht faellt eine
    Position weg."""
    try:
        points = _data_points(payload)
        as_of = datetime.strptime(str(points[ISHARES_AS_OF]["value"]), "%Y%m%d").date()
        size = len(points[HOLDING_FIELDS["name"]]["value"])
        columns = {
            field: points[column]["value"] if column in points else [None] * size
            for field, column in HOLDING_FIELDS.items()
        }
        lengths = {len(values) for values in columns.values()}
    except (KeyError, TypeError, ValueError) as e:
        msg = f"iShares-Positionen: unerwartete Struktur ({e!r})"
        raise SourceError(msg) from e
    if len(lengths) != 1:
        msg = f"iShares-Positionen: Spalten ungleich lang ({sorted(lengths)})"
        raise SourceError(msg)
    holdings: list[Holding] = []
    for row in zip(*columns.values(), strict=True):
        values = dict(zip(columns, row, strict=True))
        weight = _number(values["weight"])
        if weight is None:
            continue
        isin, ticker = _text(values["isin"]), _text(values["ticker"])
        holdings.append(
            Holding(
                name=_text(values["name"]) or isin or ticker or "-",
                weight=weight,
                isin=isin,
                ticker=ticker,
                asset_class=_text(values["asset_class"]),
                sector=_text(values["sector"]),
                country=_text(values["country"]),
                currency=_text(values["currency"]),
            )
        )
    return as_of, tuple(holdings)


def _fetch_json(url: str, params: dict[str, str], timeout: float) -> Any:
    response = http_get(url, params=params, timeout=timeout)
    try:
        return response.json()
    except ValueError as e:
        msg = f"iShares: kein JSON von {url} ({e})"
        raise SourceError(msg) from e


class IsharesFunds:
    """``EtfSource`` (D2.4): alle Positionen eines iShares-Fonds, vollstaendig.

    Die Fondsliste wird einmal je Instanz gelesen (eine Instanz je Wochenlauf). Scheitert sie,
    wirft der erste Aufruf den Fehler, jeder weitere nur noch ``SourceError`` ohne erneuten Abruf
    (und ohne Traceback im Log je ETF). Positionen mit einem Stand aelter als ``MAX_AGE`` sind ein
    Fehler der Quelle: Ein aufgeloester Fonds nennt sonst eine alte Liste als vollstaendig.
    """

    name = SOURCE

    def __init__(
        self,
        *,
        fetch: FetchJson | None = None,
        timeout: float = 60.0,
        today: Callable[[], date] = date.today,
    ) -> None:
        self._fetch: FetchJson = fetch or (lambda url, params: _fetch_json(url, params, timeout))
        self._today = today
        self._funds: dict[str, IsharesFund] | None = None
        self._failed: str | None = None

    def funds(self) -> dict[str, IsharesFund]:
        if self._failed is not None:
            msg = f"iShares-Fondsliste in diesem Lauf nicht lesbar ({self._failed})"
            raise SourceError(msg)
        if self._funds is None:
            try:
                payload = self._fetch(ISHARES_SCREENER_URL, dict(ISHARES_SCREENER_PARAMS))
                self._funds = funds_from_screener(payload)
            except Exception as e:
                self._failed = f"{type(e).__name__}: {e}"
                raise
        return self._funds

    def composition(self, isin: str, symbol: str | None) -> EtfComposition | None:  # noqa: ARG002 - Port EtfSource
        """``None`` fuer einen Fonds eines anderen Anbieters; wirft bei Ausfall. iShares findet
        den Fonds ueber die ISIN, das Symbol braucht nur yfinance."""
        fund = self.funds().get(isin)
        if fund is None:
            return None
        payload = self._fetch(ISHARES_URL, {**ISHARES_PARAMS, "portfolioId": fund.portfolio_id})
        as_of, holdings = holdings_from_payload(payload)
        if not holdings:
            msg = f"iShares {isin}: keine Positionen"
            raise SourceError(msg)
        age = (self._today() - as_of).days
        if age > MAX_AGE_DAYS:
            msg = f"iShares {isin}: Positionen vom {as_of} ({age} Tage alt)"
            raise SourceError(msg)
        return composition_from_holdings(isin, SOURCE, as_of, fund.facts, holdings)
