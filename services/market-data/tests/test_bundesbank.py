"""Kurse der Bundeswertpapiere aus der Bundesbank (D2.5, WP-06, WP-08).

Die Seite „Kurse und Renditen“ verlinkt je Monat eine XLSX mit einem Blatt je Handelstag. Die
Fixture bildet die echte Datei vom 20.11.2026 nach (Titel, Kopfzeile mit Zeilenumbruechen,
Zahlen als Zahlen, Faelligkeit als Datum, Fussnoten am Ende). Die Abrufe selbst laufen nicht in den
Tests.
"""

from __future__ import annotations

import io
from datetime import date, datetime

import openpyxl
import pytest

from va_market_data.adapters.bundesbank import (
    BUNDESBANK_PAGE,
    BundesbankPrices,
    month_links,
    quotes_from_workbook,
)
from va_market_data.domain.universe import SourceError

HEADER = [
    "ISIN",
    "Kupon",
    "Bezeichnung\n1)",
    "Fälligkeit",
    "Rest-\nlaufzeit\nJ/M",
    "Emissions-\nvolumen\n(Mrd. EUR)",
    "Kurs 2)",
    "Rendite\nin %",
    "Kurs plus\nStückzinsen",
]
BOBL = "DE0001141851"
DBR = "DE0001102416"
ILB = "DE0001030583"  # inflationsindexiert


def _rows(day: str, bobl: float, dbr: float) -> list[list[object]]:
    title: list[object] = [f"Kurse/Renditen börsennotierter Bundeswertpapiere vom {day}"]
    note: list[object] = ["2) Bundesbank-Referenzpreis an der Frankfurter Wertpapierbörse"]
    return [
        title + [None] * 8,
        list(HEADER),
        [DBR, 0.25, "DBR 0.25 02/15/27", datetime(2027, 2, 15), "0/2", 30.5, dbr, 2.73, 99.64],
        [BOBL, 0, "OBL 0 04/16/27 185", datetime(2027, 4, 16), "0/4", 22, bobl, 2.76, bobl],
        [ILB, 0.1, "DBRI 0.1 04/15/33", datetime(2033, 4, 15), "6/4", 18, 95.2, 0.9, 121.3],
        ["1) Kurzbezeichnung", None, None, None, None, None, None, None, None],
        note + [None] * 8,
    ]


def _workbook(sheets: dict[str, list[list[object]]]) -> bytes:
    book = openpyxl.Workbook()
    for sheet in list(book.worksheets):  # das leere Standardblatt
        book.remove(sheet)
    for name, rows in sheets.items():
        sheet = book.create_sheet(name)
        for row in rows:
            sheet.append(row)
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


NOVEMBER = _workbook(
    {
        "19.11.2026": _rows("19.11.2026", 98.93, 99.44),
        "20.11.2026": _rows("20.11.2026", 98.94, 99.445),
    }
)
OCTOBER = _workbook({"30.10.2026": _rows("30.10.2026", 98.7, 99.3)})

PAGE = """
<ul>
<li><a href="/resource/blob/972722/ef0b4f60508293f7aca70fa2216b1b45/472B63F073F071307366337C94F8C870/2026-11-excel-data.xlsx" title="Kurse November">November 2026</a></li>
<li><a href="/resource/blob/972700/414785491dbb07dc7d400364de768448/472B63F073F071307366337C94F8C870/2026-10-excel-data.xlsx">Oktober 2026</a></li>
<li><a href="/de/service/bundeswertpapiere">Bundeswertpapiere</a></li>
</ul>
"""


class TestLinks:
    def test_the_monthly_files_newest_first(self):
        links = month_links(PAGE)
        assert [(y, m) for y, m, _ in links] == [(2026, 11), (2026, 10)]
        assert links[0][2] == (
            "https://www.bundesbank.de/resource/blob/972722/ef0b4f60508293f7aca70fa2216b1b45/"
            "472B63F073F071307366337C94F8C870/2026-11-excel-data.xlsx"
        )

    def test_a_page_without_files_is_an_error_of_the_source(self):
        with pytest.raises(SourceError):
            month_links("<html><body>Wartungsarbeiten</body></html>")


class TestWorkbook:
    def test_the_sheet_of_the_day(self):
        quotes = quotes_from_workbook(NOVEMBER, date(2026, 11, 20))
        assert quotes is not None
        assert quotes.trade_date == date(2026, 11, 20)
        assert quotes.closes == {DBR: 99.445, BOBL: 98.94, ILB: 95.2}

    def test_before_publication_the_day_before(self):
        """Am Abend kann das Blatt des Tages noch fehlen; ein Feiertag hat keins."""
        quotes = quotes_from_workbook(NOVEMBER, date(2026, 11, 23))
        assert quotes is not None
        assert quotes.trade_date == date(2026, 11, 20)

    def test_no_sheet_until_the_day(self):
        assert quotes_from_workbook(NOVEMBER, date(2026, 11, 18)) is None

    def test_footnotes_and_odd_sheets_are_skipped(self):
        book = _workbook({"Hinweise": [["Text"]], "20.11.2026": _rows("20.11.2026", 98.94, 99.4)})
        quotes = quotes_from_workbook(book, date(2026, 11, 20))
        assert quotes is not None
        assert set(quotes.closes) == {DBR, BOBL, ILB}

    def test_a_row_without_price_is_left_out(self):
        rows = _rows("20.11.2026", 98.94, 99.445)
        rows[3][6] = "-"
        quotes = quotes_from_workbook(_workbook({"20.11.2026": rows}), date(2026, 11, 20))
        assert quotes is not None
        assert BOBL not in quotes.closes

    def test_without_the_price_column_an_error_of_the_source(self):
        rows = _rows("20.11.2026", 98.94, 99.445)
        rows[1] = [h.replace("Kurs 2)", "Preis") for h in HEADER]
        with pytest.raises(SourceError, match="Kurs"):
            quotes_from_workbook(_workbook({"20.11.2026": rows}), date(2026, 11, 20))

    def test_not_a_workbook_is_an_error_of_the_source(self):
        with pytest.raises(SourceError):
            quotes_from_workbook(b"<html>", date(2026, 11, 20))


class FakeFetch:
    def __init__(self, files: dict[str, bytes], page: str = PAGE) -> None:
        self.files = files
        self.page = page
        self.calls: list[str] = []

    def text(self, url: str) -> str:
        self.calls.append(url)
        assert url == BUNDESBANK_PAGE
        return self.page

    def content(self, url: str) -> bytes:
        self.calls.append(url)
        return next(body for name, body in self.files.items() if url.endswith(name))


class TestBundesbankPrices:
    def test_the_file_of_the_month(self):
        fetch = FakeFetch({"2026-11-excel-data.xlsx": NOVEMBER})
        quotes = BundesbankPrices(text=fetch.text, content=fetch.content).closes(date(2026, 11, 20))
        assert quotes is not None
        assert quotes.closes[BOBL] == 98.94
        assert len(fetch.calls) == 2  # Seite und eine Datei

    def test_on_the_first_of_a_month_the_previous_file(self):
        """Am 02.11. hat die Datei des Monats noch kein Blatt bis zu diesem Tag."""
        early = _workbook({"03.11.2026": _rows("03.11.2026", 98.8, 99.3)})
        fetch = FakeFetch({"2026-11-excel-data.xlsx": early, "2026-10-excel-data.xlsx": OCTOBER})
        quotes = BundesbankPrices(text=fetch.text, content=fetch.content).closes(date(2026, 11, 2))
        assert quotes is not None
        assert quotes.trade_date == date(2026, 10, 30)

    def test_a_later_month_file_is_not_used(self):
        """Ein Nachholtag im Oktober nimmt nicht die Datei des Novembers."""
        fetch = FakeFetch({"2026-11-excel-data.xlsx": NOVEMBER, "2026-10-excel-data.xlsx": OCTOBER})
        quotes = BundesbankPrices(text=fetch.text, content=fetch.content).closes(date(2026, 10, 30))
        assert quotes is not None
        assert quotes.trade_date == date(2026, 10, 30)
        assert not any(url.endswith("2026-11-excel-data.xlsx") for url in fetch.calls)

    def test_nothing_found_is_none(self):
        fetch = FakeFetch({"2026-11-excel-data.xlsx": NOVEMBER, "2026-10-excel-data.xlsx": OCTOBER})
        assert (
            BundesbankPrices(text=fetch.text, content=fetch.content).closes(date(2026, 9, 1))
            is None
        )
