"""Quelle Deka: ETF-XLSX, Blatt "Indexzusammensetzung" - nur ISIN und Name.

Das Symbol kommt ueber die Fallback-CSV, unbekannte ISINs (Neuaufnahmen) ueber einen
Resolver (OpenFIGI). Die Datei enthaelt keinen Stichtag.
"""

from __future__ import annotations

import io
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

import pandas as pd

from ..application.ports import LiveUniverse
from ..domain.universe import SourceError, Ticker, UniverseConfig, check_count
from .http import http_get

if TYPE_CHECKING:
    from datetime import date

DEKA_URL = "https://www.deka-etf.de/etfs/Deka-{index}-UCITS-ETF/composition_download"
DEKA_SHEET = "Indexzusammensetzung"

# ISINs -> {ISIN: Yahoo-Symbol}; Luecken erlaubt
IsinResolver = Callable[[list[str]], dict[str, str]]


def fetch_deka_xlsx(index: str, timeout: float) -> bytes:
    return http_get(DEKA_URL.format(index=index), timeout=timeout).content


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
    check_count(len(rows), index, "Deka", cfg)
    return rows


def map_isins(
    rows: list[tuple[str, str]],
    index: str,
    known: dict[str, Ticker],
    resolver: IsinResolver,
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


class DekaSource:
    """``UniverseSource``: alle Indizes aus den Deka-XLSX, ohne Stichtag."""

    name = "Deka"

    def __init__(self, resolver: Callable[[list[str], float], dict[str, str]]) -> None:
        self._resolver = resolver

    def load(self, fallback: list[Ticker], cfg: UniverseConfig, today: date) -> LiveUniverse:
        del today  # die Deka-Datei hat keinen Stichtag, den man pruefen koennte
        known = {t.isin: t for t in fallback if t.isin}
        tickers: list[Ticker] = []
        for index in cfg.expected_counts:
            rows = parse_deka(fetch_deka_xlsx(index, cfg.timeout), index, cfg)
            tickers.extend(
                map_isins(rows, index, known, lambda isins: self._resolver(isins, cfg.timeout))
            )
        return LiveUniverse(tickers=tickers, as_of=None)
