"""Depotstand als Datei im eigenen Format (D3.5, DEP-05; docs/architecture/depot/depots.md).

``isin;menge;einstand;notiz`` (dazu optional ``einheit``), ``;``, Dezimalkomma, UTF-8 mit oder
ohne BOM (sonst Windows-1252, wie Excel speichert), Kopfzeile optional:
- Jede Zeile wird gelesen oder mit Grund abgelehnt ("nicht erkannt"), nie still uebergangen.
- Eine Zahl wie ``1.234`` ohne Komma ist mehrdeutig und wird abgelehnt.
- Der Abgleich nennt je ISIN neu, geaendert, gleich, entfaellt.
- Der Export liefert dasselbe Format; eine Notiz, die wie eine Formel beginnt, bekommt ``'``.
"""

from __future__ import annotations

import csv
import io
from decimal import Decimal

import pytest

from va_contracts.securities import valid_isin
from va_portfolio.domain.depots import HoldingLine
from va_portfolio.domain.holdings_file import (
    MAX_FILE_BYTES,
    FileError,
    compare,
    parse_holdings,
    write_holdings,
)

SAP = "DE0007164600"
APPLE = "US0378331005"
BUND = "DE0001102580"
BOM = "﻿"


def _parse(text: str, kind: str = "depot", encoding: str = "utf-8"):
    return parse_holdings(text.encode(encoding), kind)  # type: ignore[arg-type]


class TestReading:
    def test_with_header_bom_and_decimal_comma(self):
        parsed = _parse(f"{BOM}isin;menge;einstand;notiz\n{SAP};12,5;1.500,25;Kaufgrund\n")
        [line] = parsed.lines
        assert (line.isin, line.quantity, line.cost_basis_eur, line.note, line.unit) == (
            SAP,
            Decimal("12.5"),
            Decimal("1500.25"),
            "Kaufgrund",
            None,
        )
        assert parsed.rejected == ()

    def test_without_header_and_with_windows_line_ends(self):
        parsed = _parse(f"{SAP};10;;\r\n{APPLE};3\r\n")
        assert [(line.isin, line.quantity) for line in parsed.lines] == [
            (SAP, Decimal(10)),
            (APPLE, Decimal(3)),
        ]
        assert parsed.lines[1].cost_basis_eur is None

    def test_columns_by_header_in_any_order(self):
        parsed = _parse(f"menge;isin;einheit\n10000;{BUND};nennwert\n")
        [line] = parsed.lines
        assert (line.isin, line.quantity, line.unit) == (BUND, Decimal(10000), "nominal")

    def test_excel_saves_windows_1252(self):
        parsed = _parse(f"{SAP};1;;Ölwerte für später\n", encoding="cp1252")
        assert parsed.lines[0].note == "Ölwerte für später"

    def test_quoted_note_with_semicolon(self):
        parsed = _parse(f'{SAP};1;;"Kauf; Nachkauf"\n')
        assert parsed.lines[0].note == "Kauf; Nachkauf"

    def test_isin_in_lower_case_and_blank_lines(self):
        parsed = _parse(f"\n{SAP.lower()};1\n\n")
        assert [line.isin for line in parsed.lines] == [SAP]

    def test_a_point_only_as_decimal_point_without_comma(self):
        assert _parse(f"{SAP};1.5\n").lines[0].quantity == Decimal("1.5")

    def test_formula_guard_from_the_export_is_removed(self):
        assert _parse(f"{SAP};1;;'=Kaufgrund\n").lines[0].note == "=Kaufgrund"


class TestRejected:
    @pytest.mark.parametrize(
        ("row", "reason"),
        [
            ("DE0007164601;1", "ISIN"),  # Pruefziffer
            ("SAP;1", "ISIN"),
            (f"{SAP};10.000", "mehrdeutig"),
            (f"{SAP};zehn", "Zahl"),
            (f"{SAP};0", "groesser als 0"),
            (f"{SAP};", "Menge"),
            (f"{SAP};1;-5", "negativ"),
            (f"{SAP};1;;;tonnen", "Einheit"),
            (f"{SAP};1,123456789", "Nachkommastellen"),
            (f"{SAP};1;;{'x' * 501}", "Notiz"),
        ],
    )
    def test_each_row_with_a_reason(self, row, reason):
        parsed = _parse(f"{APPLE};1\n{row}\n")
        assert [line.isin for line in parsed.lines] == [APPLE]
        [rejected] = parsed.rejected
        assert rejected.line == 2
        assert reason in rejected.reason

    def test_duplicate_isin_names_the_first_row(self):
        parsed = _parse(f"{SAP};1\n{APPLE};2\n{SAP};3\n")
        [rejected] = parsed.rejected
        assert (rejected.line, "Zeile 1" in rejected.reason) == (3, True)

    def test_watchlist_without_quantities(self):
        parsed = _parse(f"{SAP}\n{APPLE};3\n", kind="watchlist")
        assert [line.isin for line in parsed.lines] == [SAP]
        assert "Beobachtungsliste" in parsed.rejected[0].reason

    def test_too_large(self):
        with pytest.raises(FileError, match="KiB"):
            parse_holdings(b"x" * (MAX_FILE_BYTES + 1), "depot")

    def test_unreadable_characters(self):
        with pytest.raises(FileError, match="Zeichensatz"):
            parse_holdings(b"\x81\x8d\x8f\x90\x9d;1\n", "depot")  # in Windows-1252 nicht belegt

    def test_empty(self):
        with pytest.raises(FileError, match="keine Position"):
            _parse("isin;menge;einstand;notiz\n")

    def test_header_with_an_unknown_column(self):
        with pytest.raises(FileError, match="kurs"):
            _parse(f"isin;menge;kurs\n{SAP};1;231,5\n")

    def test_header_without_isin(self):
        with pytest.raises(FileError, match="isin"):
            _parse("menge;notiz\n1;x\n")

    def test_too_many_lines(self):
        isins = [_isin(n) for n in range(1001)]
        with pytest.raises(FileError, match="1000"):
            _parse("".join(f"{isin};1\n" for isin in isins))

    def test_exactly_1000_lines(self):
        assert len(_parse("".join(f"{_isin(n)};1\n" for n in range(1000))).lines) == 1000

    def test_rejected_rows_count_too(self):
        # sonst passte der Abgleich einer kaputten Datei nicht durch NATS
        with pytest.raises(FileError, match="1000"):
            _parse("kaputt;1\n" * 1001)


def _isin(n: int) -> str:
    body = f"DE000{n:06d}"
    return next(body + d for d in "0123456789" if valid_isin(body + d))


class TestCompare:
    def test_new_changed_unchanged_removed(self):
        current = [
            HoldingLine(SAP, Decimal(10)),
            HoldingLine(APPLE, Decimal(3)),
            HoldingLine(BUND, Decimal(5000), "nominal"),
        ]
        new = [
            HoldingLine(SAP, Decimal("10.000")),  # gleich
            HoldingLine(APPLE, Decimal(4)),
            HoldingLine("IE00B4L5Y983", Decimal(7)),
        ]
        entries = compare(current, new)
        assert [(e.isin, e.status) for e in entries] == [
            (SAP, "unchanged"),
            (APPLE, "changed"),
            ("IE00B4L5Y983", "new"),
            (BUND, "removed"),
        ]
        assert entries[1].before == current[1]
        assert entries[3].after is None


class TestWriting:
    def test_same_format_back(self):
        lines = [
            HoldingLine(
                SAP, Decimal("12.50000000"), cost_basis_eur=Decimal("1500.25"), note="Kauf"
            ),
            HoldingLine(BUND, Decimal("10000"), "nominal"),
        ]
        content = write_holdings(lines)
        assert content.startswith(BOM.encode("utf-8"))
        text = content.decode("utf-8-sig")
        assert text.splitlines() == [
            "isin;menge;einstand;notiz;einheit",
            f"{SAP};12,5;1500,25;Kauf;stueck",
            f"{BUND};10000;;;nennwert",
        ]
        assert "\r" not in text

    def test_round_trip(self):
        lines = [
            HoldingLine(SAP, Decimal("0.123"), cost_basis_eur=Decimal(2000), note='a;b "c"'),
            HoldingLine(BUND, Decimal("1E+4"), "nominal"),
        ]
        parsed = parse_holdings(write_holdings(lines), "depot")
        assert [(p.isin, p.quantity, p.unit, p.cost_basis_eur, p.note) for p in parsed.lines] == [
            (SAP, Decimal("0.123"), "pieces", Decimal(2000), 'a;b "c"'),
            (BUND, Decimal(10000), "nominal", None, None),
        ]

    @pytest.mark.parametrize("note", ['=HYPERLINK("x")', "+1", "-1", "@SUM(A1)"])
    def test_a_note_never_becomes_a_formula(self, note):
        content = write_holdings([HoldingLine(SAP, Decimal(1), note=note)])
        [_, row] = list(csv.reader(io.StringIO(content.decode("utf-8-sig")), delimiter=";"))
        assert row[3] == f"'{note}"
        assert parse_holdings(content, "depot").lines[0].note == note

    def test_watchlist_without_quantities(self):
        text = write_holdings([HoldingLine(SAP, None)]).decode("utf-8-sig")
        assert text.splitlines()[1] == f"{SAP};;;;stueck"
