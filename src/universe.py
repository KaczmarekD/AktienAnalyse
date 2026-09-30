"""DAX/MDAX Universum laden.

Quellen-Kette (erste gueltige gewinnt):

1. iShares-Holdings der physisch replizierenden ETFs EXS1 (DAX) und EXS3
   (MDAX) - liefert Emittententicker + ISIN, ``ticker + ".DE"`` ist das
   Yahoo-Symbol.
2. Deka-ETF-XLSX, Blatt "Indexzusammensetzung" - nur ISIN; Symbol ueber die
   Fallback-CSV, unbekannte ISINs (Neuaufnahmen) ueber OpenFIGI (Xetra).
3. Fallback-CSV ``data/dax_mdax_fallback.csv`` - immer verfuegbar.

Jede Live-Quelle wird hart validiert (JSON/XLSX lesbar, exakte Anzahl pro
Index, Stichtag nicht zu alt). Die iShares-URLs sind undokumentiert und
brachen im September 2026 schon einmal still weg (HTML mit HTTP 200).

Weicht die Live-Quelle von der CSV ab, meldet ``Universe.added/removed``
das - der Report zeigt dann einen Hinweis, die CSV zu pflegen. Die CSV wird
bewusst nicht automatisch ueberschrieben.

Rechtliches: Keine Quelle erlaubt automatisierten Abruf ausdruecklich;
iShares/Deka sperren die Pfade nicht per robots.txt. Privat, 1x pro Woche.
Hintergrund: docs/research/dax-mdax-datenquellen/bericht.md
"""

from __future__ import annotations

import csv
import io
import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import requests
from tenacity import retry, stop_after_attempt, wait_exponential

log = logging.getLogger(__name__)

# --- Quellen (bei Umbenennung durch den Anbieter nur hier anpassen) ---------
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

DEKA_URL = "https://www.deka-etf.de/etfs/Deka-{index}-UCITS-ETF/composition_download"
DEKA_SHEET = "Indexzusammensetzung"

OPENFIGI_URL = "https://api.openfigi.com/v3/mapping"
OPENFIGI_EXCHANGE = "GY"  # Xetra
OPENFIGI_BATCH = 10  # Limit ohne API-Key

YAHOO_SUFFIX = ".DE"
USER_AGENT = "value-analyzer/1.0 (private, weekly)"

FALLBACK_SOURCE = "Fallback-CSV"

DEFAULT_FALLBACK_CSV = Path(__file__).resolve().parent.parent / "data" / "dax_mdax_fallback.csv"


class SourceError(Exception):
    """Eine Live-Quelle ist nicht erreichbar oder liefert ungueltige Daten."""


@dataclass(frozen=True)
class Ticker:
    symbol: str
    name: str
    index: str  # "DAX" oder "MDAX"
    isin: str | None = None


@dataclass
class UniverseConfig:
    expected_counts: dict[str, int] = field(default_factory=lambda: {"DAX": 40, "MDAX": 50})
    max_age_days: int = 10
    timeout: float = 30.0


@dataclass
class Universe:
    tickers: list[Ticker]
    source: str  # "iShares" | "Deka" | FALLBACK_SOURCE
    as_of: date | None = None
    added: list[Ticker] = field(default_factory=list)  # in Quelle, nicht in CSV
    removed: list[Ticker] = field(default_factory=list)  # in CSV, nicht in Quelle


# ---------------------------------------------------------------------------
# Netz
# ---------------------------------------------------------------------------


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=2, max=20))
def _http_get(url: str, params: dict[str, str] | None = None, timeout: float = 30.0) -> Any:
    response = requests.get(url, params=params, headers={"User-Agent": USER_AGENT}, timeout=timeout)
    response.raise_for_status()
    return response


def _fetch_ishares_json(index: str, timeout: float) -> dict[str, Any]:
    params = {**ISHARES_PARAMS, "portfolioId": ISHARES_PORTFOLIO_IDS[index]}
    response = _http_get(ISHARES_URL, params=params, timeout=timeout)
    try:
        return response.json()
    except ValueError as e:
        msg = f"iShares {index}: kein JSON ({e})"
        raise SourceError(msg) from e


def _fetch_deka_xlsx(index: str, timeout: float) -> bytes:
    return _http_get(DEKA_URL.format(index=index), timeout=timeout).content


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=2, max=20))
def _openfigi_post(jobs: list[dict[str, str]], timeout: float = 30.0) -> Any:
    response = requests.post(OPENFIGI_URL, json=jobs, timeout=timeout)
    response.raise_for_status()
    return response.json()


# ---------------------------------------------------------------------------
# Parser + Validierung (rein, ohne Netz)
# ---------------------------------------------------------------------------


def _check_count(count: int, index: str, source: str, cfg: UniverseConfig) -> None:
    expected = cfg.expected_counts[index]
    if count != expected:
        msg = f"{source} {index}: {count} statt {expected} Aktien"
        raise SourceError(msg)


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
    _check_count(len(tickers), index, "iShares", cfg)
    return tickers, as_of


def _clean_name(value: Any) -> str:
    """Leere Excel-Zellen kommen als NaN (float) - nie als 'nan' durchreichen."""
    return value.strip() if isinstance(value, str) else ""


def parse_deka(content: bytes, index: str, cfg: UniverseConfig) -> list[tuple[str, str]]:
    """Deka-XLSX -> [(Name, ISIN)] aus dem Blatt der Indexzusammensetzung."""
    try:
        df = pd.read_excel(io.BytesIO(content), sheet_name=DEKA_SHEET, dtype=str)
        rows = [
            (_clean_name(name) or isin.strip(), isin.strip())
            for name, isin in zip(df["Holding Name"], df["ISIN"], strict=True)
            if isinstance(isin, str) and isin.strip()
        ]
    except Exception as e:
        msg = f"Deka {index}: {DEKA_SHEET} nicht lesbar ({e!r})"
        raise SourceError(msg) from e
    _check_count(len(rows), index, "Deka", cfg)
    return rows


def resolve_isins_openfigi(isins: Iterable[str], timeout: float = 30.0) -> dict[str, str]:
    """ISIN -> Yahoo-Symbol ueber das Xetra-Listing. Fehler ergeben Luecken, keine Exception."""
    isins = list(isins)
    result: dict[str, str] = {}
    for start in range(0, len(isins), OPENFIGI_BATCH):
        batch = isins[start : start + OPENFIGI_BATCH]
        jobs = [{"idType": "ID_ISIN", "idValue": i, "exchCode": OPENFIGI_EXCHANGE} for i in batch]
        try:
            answers = _openfigi_post(jobs, timeout)
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


def _map_isins(
    rows: list[tuple[str, str]],
    index: str,
    known: dict[str, Ticker],
    resolver: Callable[[list[str]], dict[str, str]],
) -> list[Ticker]:
    """ISINs zuerst ueber die CSV, Rest ueber ``resolver``. Luecken -> SourceError."""
    unknown = [isin for _, isin in rows if isin not in known]
    resolved = resolver(unknown) if unknown else {}
    missing = [isin for isin in unknown if isin not in resolved]
    if missing:
        msg = f"Deka {index}: kein Ticker fuer {', '.join(missing)}"
        raise SourceError(msg)

    tickers: list[Ticker] = []
    for name, isin in rows:
        if isin in known:
            k = known[isin]
            tickers.append(Ticker(k.symbol, k.name, index, isin))
        else:
            tickers.append(Ticker(resolved[isin], name, index, isin))
    return tickers


# ---------------------------------------------------------------------------
# Quellen
# ---------------------------------------------------------------------------


def _from_ishares(
    fallback: list[Ticker], cfg: UniverseConfig, today: date
) -> tuple[list[Ticker], date]:
    known_names = {t.isin: t.name for t in fallback if t.isin}
    tickers: list[Ticker] = []
    as_of_dates: list[date] = []
    for index in cfg.expected_counts:
        index_tickers, as_of = parse_ishares(
            _fetch_ishares_json(index, cfg.timeout), index, known_names, cfg, today
        )
        tickers.extend(index_tickers)
        as_of_dates.append(as_of)
    return tickers, min(as_of_dates)


def _from_deka(fallback: list[Ticker], cfg: UniverseConfig) -> list[Ticker]:
    known = {t.isin: t for t in fallback if t.isin}
    tickers: list[Ticker] = []
    for index in cfg.expected_counts:
        rows = parse_deka(_fetch_deka_xlsx(index, cfg.timeout), index, cfg)
        tickers.extend(
            _map_isins(rows, index, known, lambda isins: resolve_isins_openfigi(isins, cfg.timeout))
        )
    return tickers


def load_fallback(csv_path: Path | None = None) -> list[Ticker]:
    """Liest die Fallback-Liste aus CSV (symbol,name,index[,isin])."""
    path = csv_path or DEFAULT_FALLBACK_CSV
    if not path.exists():
        log.error("Fallback-CSV nicht gefunden: %s", path)
        return []
    with path.open(encoding="utf-8") as f:
        return [
            Ticker(
                symbol=row["symbol"].strip(),
                name=row["name"].strip(),
                index=row["index"].strip(),
                isin=(row.get("isin") or "").strip() or None,
            )
            for row in csv.DictReader(f)
            if row.get("symbol")
        ]


def _dedupe(tickers: list[Ticker]) -> list[Ticker]:
    seen: set[str] = set()
    result: list[Ticker] = []
    for t in tickers:
        if t.symbol in seen:
            continue
        seen.add(t.symbol)
        result.append(t)
    return result


def _diff_key(t: Ticker) -> tuple[str, str, str | None]:
    # Symbol + Index + ISIN: erkennt auch Auf-/Abstiege und ISIN-Wechsel
    return (t.symbol, t.index, t.isin)


def _diff(live: list[Ticker], fallback: list[Ticker]) -> tuple[list[Ticker], list[Ticker]]:
    live_keys = {_diff_key(t) for t in live}
    fallback_keys = {_diff_key(t) for t in fallback}
    added = [t for t in live if _diff_key(t) not in fallback_keys]
    removed = [t for t in fallback if _diff_key(t) not in live_keys]
    return added, removed


def load_universe(
    cfg: UniverseConfig | None = None,
    fallback_csv: Path | None = None,
    force_fallback: bool = False,
    today: date | None = None,
) -> Universe:
    """DAX + MDAX aus der ersten gueltigen Quelle, dedupliziert."""
    cfg = cfg or UniverseConfig()
    today = today or date.today()
    fallback = _dedupe(load_fallback(fallback_csv))

    if not force_fallback:
        try:
            tickers, as_of = _from_ishares(fallback, cfg, today)
            return _live_universe(tickers, "iShares", as_of, fallback)
        except Exception as e:
            log.warning("iShares-Quelle ungueltig (%s) - versuche Deka", e)
        try:
            return _live_universe(_from_deka(fallback, cfg), "Deka", None, fallback)
        except Exception as e:
            log.warning("Deka-Quelle ungueltig (%s) - nutze Fallback-CSV", e)
    else:
        log.info("Force-Fallback aktiv - lese aus CSV")

    log.info("Universum aus Fallback-CSV: %d Ticker", len(fallback))
    return Universe(tickers=fallback, source=FALLBACK_SOURCE)


def _live_universe(
    tickers: list[Ticker], source: str, as_of: date | None, fallback: list[Ticker]
) -> Universe:
    unique = _dedupe(tickers)
    added, removed = _diff(unique, fallback)
    log.info("Universum aus %s: %d Ticker (Stand %s)", source, len(unique), as_of or "-")
    if added or removed:
        log.warning(
            "Fallback-CSV veraltet: +%s / -%s",
            [t.symbol for t in added],
            [t.symbol for t in removed],
        )
    return Universe(tickers=unique, source=source, as_of=as_of, added=added, removed=removed)
