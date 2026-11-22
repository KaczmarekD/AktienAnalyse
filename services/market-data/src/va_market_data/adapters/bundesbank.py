"""Quelle Bundesbank: Kurse der boersennotierten Bundeswertpapiere (D2.5, WP-06, WP-08).

Die Seite „Kurse und Renditen“ verlinkt je Monat eine XLSX (``…/JJJJ-MM-excel-data.xlsx``, der
Pfad enthaelt eine wechselnde Blob-ID). Darin ein Blatt je Handelstag (``TT.MM.JJJJ``): Titel,
Kopfzeile, je Anleihe eine Zeile mit ISIN und „Kurs“ (Bundesbank-Referenzpreis in Prozent vom
Nennwert, ohne Stueckzinsen; bei inflationsindexierten ohne Inflationsanpassung), Fussnoten am
Ende. Baut die Bundesbank um, nur die Konstanten am Kopf anpassen.

Rechtliches: oeffentliche Veroeffentlichung, kein Schluessel; robots.txt sperrt den Pfad nicht.
Ein Abruf je Handelstag.
"""

from __future__ import annotations

import io
import logging
import math
import re
from collections.abc import Callable
from datetime import date, datetime
from typing import Any
from urllib.parse import urljoin

import openpyxl

from va_contracts.securities import valid_isin

from ..application.prices import BondQuotes
from ..domain.universe import SourceError
from .http import http_get

log = logging.getLogger(__name__)

BUNDESBANK_PAGE = "https://www.bundesbank.de/de/service/bundeswertpapiere/kurse-und-renditen"
# Link einer Monatsdatei; Gruppen: Pfad, Jahr, Monat
LINK_PATTERN = re.compile(r'href="([^"]*?/(\d{4})-(\d{2})-excel-data\.xlsx)"')
SHEET_DATE = "%d.%m.%Y"  # Name eines Blatts = Handelstag
ISIN_HEADER = "ISIN"  # erste Spalte der Kopfzeile
# Spalte des Kurses: „Kurs 2)“ (Fussnote), nicht „Kurs plus Stueckzinsen“
CLOSE_HEADER = re.compile(r"^Kurs(?: \d+\))?$")
HEADER_ROWS = 10  # so weit oben steht die Kopfzeile
MAX_FILES = 2  # Datei des Monats und die des Vormonats (am Monatsersten)


def month_links(html: str) -> list[tuple[int, int, str]]:
    """(Jahr, Monat, URL) der Monatsdateien, die juengste zuerst; ohne Link ein Fehler."""
    links = {
        (int(year), int(month)): urljoin(BUNDESBANK_PAGE, path)
        for path, year, month in LINK_PATTERN.findall(html)
    }
    if not links:
        msg = "Bundesbank: keine Monatsdatei auf der Seite der Kurse"
        raise SourceError(msg)
    return [(year, month, url) for (year, month), url in sorted(links.items(), reverse=True)]


def _header(value: Any) -> str:
    return " ".join(str(value).split()) if value is not None else ""


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    number = float(value)
    return number if math.isfinite(number) and number > 0 else None


def _sheet_dates(names: list[str]) -> dict[date, str]:
    dates: dict[date, str] = {}
    for name in names:
        try:
            dates[datetime.strptime(name.strip(), SHEET_DATE).date()] = name
        except ValueError:
            continue
    return dates


def _closes(rows: list[tuple[Any, ...]], sheet: str) -> dict[str, float]:
    header_at = next(
        (i for i, row in enumerate(rows[:HEADER_ROWS]) if row and _header(row[0]) == ISIN_HEADER),
        None,
    )
    if header_at is None:
        msg = f"Bundesbank {sheet}: keine Kopfzeile mit {ISIN_HEADER}"
        raise SourceError(msg)
    header = [_header(cell) for cell in rows[header_at]]
    column = next((i for i, name in enumerate(header) if CLOSE_HEADER.match(name)), None)
    if column is None:
        msg = f"Bundesbank {sheet}: keine Spalte Kurs in {header}"
        raise SourceError(msg)
    closes: dict[str, float] = {}
    for row in rows[header_at + 1 :]:
        isin = str(row[0]).strip() if row and row[0] is not None else ""
        close = _number(row[column]) if len(row) > column else None
        if valid_isin(isin) and close is not None:
            closes[isin] = close
    if not closes:
        msg = f"Bundesbank {sheet}: keine Kurse"
        raise SourceError(msg)
    return closes


def quotes_from_workbook(content: bytes, trade_date: date) -> BondQuotes | None:
    """Das Blatt von ``trade_date``, sonst das juengste davor; ``None`` ohne ein solches."""
    try:
        book = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except Exception as e:  # kaputte oder keine XLSX (HTML-Fehlerseite)
        msg = f"Bundesbank: keine lesbare XLSX ({type(e).__name__})"
        raise SourceError(msg) from e
    try:
        dates = _sheet_dates(book.sheetnames)
        candidates = [day for day in dates if day <= trade_date]
        if not candidates:
            return None
        day = max(candidates)
        rows = list(book[dates[day]].iter_rows(values_only=True))
        return BondQuotes(day, _closes(rows, dates[day]))
    finally:
        book.close()


class BundesbankPrices:
    """Kurse der Bundeswertpapiere bis zu einem Handelstag: die Datei des Monats, am Monatsersten
    die des Vormonats. Wirft bei Ausfall; ``None``, wenn keine Datei ein passendes Blatt hat."""

    def __init__(
        self,
        *,
        text: Callable[[str], str] | None = None,
        content: Callable[[str], bytes] | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._text = text or (lambda url: http_get(url, timeout=timeout).text)
        self._content = content or (lambda url: http_get(url, timeout=timeout).content)

    def closes(self, trade_date: date) -> BondQuotes | None:
        month = (trade_date.year, trade_date.month)
        files = [
            url for year, m, url in month_links(self._text(BUNDESBANK_PAGE)) if (year, m) <= month
        ]
        for url in files[:MAX_FILES]:
            quotes = quotes_from_workbook(self._content(url), trade_date)
            if quotes is not None:
                return quotes
        return None
