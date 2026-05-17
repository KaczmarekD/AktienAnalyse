"""DAX/MDAX Universum laden.

Primaerquelle: Wikipedia (Tabelle der Index-Konstituenten).
Fallback: CSV unter ``data/dax_mdax_fallback.csv`` - so kann das Universum
ohne Code-Aenderung aktualisiert werden.

yfinance-Ticker fuer deutsche Aktien: Boersenkuerzel + ``.DE`` (Xetra).
"""

from __future__ import annotations

import csv
import logging
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import requests
from tenacity import retry, stop_after_attempt, wait_exponential

log = logging.getLogger(__name__)

WIKI_DAX = "https://en.wikipedia.org/wiki/DAX"
WIKI_MDAX = "https://en.wikipedia.org/wiki/MDAX"

DEFAULT_FALLBACK_CSV = Path(__file__).resolve().parent.parent / "data" / "dax_mdax_fallback.csv"


@dataclass(frozen=True)
class Ticker:
    symbol: str
    name: str
    index: str  # "DAX" oder "MDAX"


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=2, max=20))
def _fetch_wiki_table(url: str) -> pd.DataFrame:
    headers = {"User-Agent": "value-analyzer/1.0 (educational)"}
    response = requests.get(url, headers=headers, timeout=20)
    response.raise_for_status()
    tables = pd.read_html(response.text)
    for tbl in tables:
        cols = {str(c).lower() for c in tbl.columns}
        if any(k in cols for k in ("ticker", "symbol")):
            return tbl
    msg = f"Keine Ticker-Tabelle auf {url} gefunden"
    raise ValueError(msg)


def _parse_wiki(df: pd.DataFrame, index_name: str) -> list[Ticker]:
    df = df.copy()
    df.columns = [str(c).lower() for c in df.columns]
    ticker_col = next((c for c in df.columns if c in ("ticker", "symbol")), None)
    name_col = next(
        (c for c in df.columns if c in ("company", "name", "constituent")),
        None,
    )
    if ticker_col is None:
        return []

    tickers: list[Ticker] = []
    for _, row in df.iterrows():
        raw = str(row[ticker_col]).strip()
        if not raw or raw.lower() == "nan":
            continue
        sym = raw if "." in raw else f"{raw}.DE"
        name = str(row[name_col]).strip() if name_col else sym
        tickers.append(Ticker(symbol=sym, name=name, index=index_name))
    return tickers


def load_fallback(csv_path: Path | None = None) -> list[Ticker]:
    """Liest die Fallback-Liste aus CSV (symbol,name,index)."""
    path = csv_path or DEFAULT_FALLBACK_CSV
    if not path.exists():
        log.error("Fallback-CSV nicht gefunden: %s", path)
        return []
    with path.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return [
            Ticker(
                symbol=row["symbol"].strip(), name=row["name"].strip(), index=row["index"].strip()
            )
            for row in reader
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


def load_universe(force_fallback: bool = False, fallback_csv: Path | None = None) -> list[Ticker]:
    """Vollstaendige Liste DAX + MDAX, dedupliziert."""
    if force_fallback:
        log.info("Force-Fallback aktiv - lese aus CSV")
        return _dedupe(load_fallback(fallback_csv))

    tickers: list[Ticker] = []
    try:
        dax_df = _fetch_wiki_table(WIKI_DAX)
        tickers.extend(_parse_wiki(dax_df, "DAX"))
        log.info("DAX von Wikipedia geladen: %d Werte", len(tickers))
    except Exception as e:
        log.warning("Wikipedia-Fetch DAX fehlgeschlagen (%s) - nutze Fallback komplett", e)
        return _dedupe(load_fallback(fallback_csv))

    try:
        mdax_df = _fetch_wiki_table(WIKI_MDAX)
        before = len(tickers)
        tickers.extend(_parse_wiki(mdax_df, "MDAX"))
        log.info("MDAX von Wikipedia geladen: %d Werte", len(tickers) - before)
    except Exception as e:
        log.warning("Wikipedia-Fetch MDAX fehlgeschlagen (%s) - ergaenze Fallback-MDAX", e)
        seen = {t.symbol for t in tickers}
        tickers.extend(
            t for t in load_fallback(fallback_csv) if t.index == "MDAX" and t.symbol not in seen
        )

    unique = _dedupe(tickers)
    log.info("Universum gesamt: %d eindeutige Ticker", len(unique))
    return unique
