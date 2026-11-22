"""Depotstand als Datei im eigenen Format (D3.5, DEP-05; docs/architecture/depot/depots.md).

Format wie die Report-CSV: ``;``, Dezimalkomma, UTF-8 mit BOM, Zeilenende LF. Spalten
``isin;menge;einstand;notiz;einheit``; ``einheit`` (``stueck``/``nennwert``) ist optional.

Lesen ist nachsichtig, aber nie still:
- UTF-8 mit oder ohne BOM, sonst Windows-1252 (so speichert Excel "CSV (Trennzeichen-getrennt)").
- Kopfzeile optional; mit Kopfzeile gilt die Reihenfolge ihrer Spalten.
- Zahlen mit Dezimalkomma, Tausenderpunkte erlaubt (``1.500,25``); ohne Komma ist der Punkt der
  Dezimalpunkt (``1.5``). ``1.234`` ohne Komma ist mehrdeutig und wird abgelehnt.
- Jede Zeile wird gelesen oder mit Grund abgelehnt ("nicht erkannt"). Was die ganze Datei
  unbrauchbar macht (zu gross, Zeichensatz, keine Position, mehr als ``MAX_LINES``
  Datenzeilen), ist ein ``FileError``. Die Grenze gilt fuer gelesene und abgelehnte Zeilen
  zusammen: Sonst ergaebe eine Datei mit 100 000 kaputten Zeilen einen Abgleich, der nicht
  mehr durch NATS passt (1 MB).

Schreiben: dasselbe Format; eine Notiz, die wie eine Formel beginnt (``=``, ``+``, ``-``, ``@``),
bekommt ein ``'`` davor (Tabellenprogramme fuehren sie sonst aus), das Lesen nimmt es wieder weg.
"""

from __future__ import annotations

import csv
import io
import re
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Literal

from va_contracts.portfolio import MAX_FILE_BYTES, MAX_LINES, MAX_TEXT
from va_contracts.securities import valid_isin

from .depots import DepotError, HoldingLine, same_position

if TYPE_CHECKING:
    from va_contracts.portfolio import DepotKind, HoldingUnit

# ``MAX_FILE_BYTES`` (640 KiB, im Contract): Base64 im JSON muss unter 1 MB bleiben, der Grenze
# von nginx (client_max_body_size) und NATS (max_payload). Reicht fuer 1000 lange Positionen.
__all__ = [
    "MAX_FILE_BYTES",
    "FileError",
    "FileLine",
    "ImportEntry",
    "ParsedFile",
    "RejectedRow",
    "compare",
    "parse_holdings",
    "write_holdings",
]
COLUMNS = ("isin", "menge", "einstand", "notiz", "einheit")
UNITS: dict[str, HoldingUnit] = {
    "stueck": "pieces",
    "stück": "pieces",
    "pieces": "pieces",
    "nennwert": "nominal",
    "nominal": "nominal",
}
UNIT_NAMES: dict[HoldingUnit, str] = {"pieces": "stueck", "nominal": "nennwert"}
FORMULA_START = ("=", "+", "-", "@", "\t", "\r")
MAX_DIGITS, MAX_PLACES = 20, 8  # wie ``Quantity`` und ``Amount`` im Contract

_PLAIN_COMMA = re.compile(r"^-?\d+,\d+$")
_GROUPED_COMMA = re.compile(r"^-?\d{1,3}(\.\d{3})+,\d+$")
_GROUPED_ONLY = re.compile(r"^-?\d{1,3}(\.\d{3})+$")
_PLAIN = re.compile(r"^-?\d+(\.\d+)?$")

ImportStatus = Literal["new", "changed", "unchanged", "removed"]


class FileError(DepotError):
    """Die Datei ist als Ganzes nicht lesbar (am Request/Reply ``invalid``)."""


class _RowError(ValueError):
    pass


@dataclass(frozen=True)
class FileLine:
    """Eine gelesene Zeile; ``unit`` ``None``: nicht angegeben (der Anwendungsfall ergaenzt)."""

    line: int
    isin: str
    quantity: Decimal | None
    unit: HoldingUnit | None
    cost_basis_eur: Decimal | None
    note: str | None


@dataclass(frozen=True)
class RejectedRow:
    line: int  # Zeile in der Datei, ab 1
    reason: str


@dataclass(frozen=True)
class ParsedFile:
    lines: tuple[FileLine, ...]
    rejected: tuple[RejectedRow, ...]


@dataclass(frozen=True)
class ImportEntry:
    isin: str
    status: ImportStatus
    before: HoldingLine | None
    after: HoldingLine | None


def _text(content: bytes) -> str:
    if len(content) > MAX_FILE_BYTES:
        msg = f"Die Datei ist groesser als {MAX_FILE_BYTES // 1024} KiB"
        raise FileError(msg)
    try:
        return content.decode("utf-8-sig")
    except UnicodeDecodeError:
        pass
    try:
        return content.decode("cp1252")
    except UnicodeDecodeError:
        msg = "Der Zeichensatz der Datei ist nicht lesbar (UTF-8 oder Windows-1252)"
        raise FileError(msg) from None


def _number(raw: str, label: str) -> Decimal | None:
    text = raw.strip().replace(" ", "").replace("\u00a0", "")
    if not text:
        return None
    if _PLAIN_COMMA.match(text) or _GROUPED_COMMA.match(text):
        text = text.replace(".", "").replace(",", ".")
    elif _GROUPED_ONLY.match(text):
        msg = (
            f"{label} {raw.strip()!r} ist mehrdeutig: Dezimalkomma verwenden (etwa 1234 oder 1,234)"
        )
        raise _RowError(msg)
    elif not _PLAIN.match(text):
        msg = f"{label} {raw.strip()!r} ist keine Zahl"
        raise _RowError(msg)
    try:
        value = Decimal(text)
    except InvalidOperation:  # pragma: no cover - die Muster lassen nur Zahlen durch
        msg = f"{label} {raw.strip()!r} ist keine Zahl"
        raise _RowError(msg) from None
    exponent = value.as_tuple().exponent
    assert isinstance(exponent, int)
    if -exponent > MAX_PLACES:
        msg = f"{label}: hoechstens {MAX_PLACES} Nachkommastellen"
        raise _RowError(msg)
    if len(value.as_tuple().digits) > MAX_DIGITS:
        msg = f"{label} ist zu gross"
        raise _RowError(msg)
    return value


def _note(raw: str) -> str | None:
    note = raw.strip()
    if note.startswith("'") and note[1:2] and note[1] in FORMULA_START:
        note = note[1:]
    if len(note) > MAX_TEXT:
        msg = f"Die Notiz hat hoechstens {MAX_TEXT} Zeichen"
        raise _RowError(msg)
    return note or None


def _columns(row: list[str]) -> list[str] | None:
    """Die Spalten aus einer Kopfzeile; ``None``, wenn die Zeile keine ist."""
    names = [cell.strip().lower() for cell in row]
    unknown = [name for name in names if name and name not in COLUMNS]
    if names and names[0] == "isin" and unknown:
        msg = f"Unbekannte Spalte {', '.join(unknown)} (erlaubt: {';'.join(COLUMNS)})"
        raise FileError(msg)
    if not any(names) or unknown:
        return None
    if "isin" not in names:
        msg = "Die Kopfzeile braucht die Spalte isin"
        raise FileError(msg)
    return names


def _line(number: int, cells: dict[str, str], kind: DepotKind) -> FileLine:
    isin = cells.get("isin", "").strip().upper()
    if not valid_isin(isin):
        msg = f"Keine gueltige ISIN: {cells.get('isin', '').strip()!r}"
        raise _RowError(msg)
    quantity = _number(cells.get("menge", ""), "Menge")
    cost = _number(cells.get("einstand", ""), "Einstand")
    unit_name = cells.get("einheit", "").strip().lower()
    if unit_name and unit_name not in UNITS:
        msg = f"Unbekannte Einheit {unit_name!r} (stueck oder nennwert)"
        raise _RowError(msg)
    if kind == "watchlist":
        if quantity is not None or cost is not None:
            msg = "Eine Beobachtungsliste hat keine Mengen und keinen Einstand"
            raise _RowError(msg)
    elif quantity is None:
        msg = "Die Menge fehlt"
        raise _RowError(msg)
    elif quantity <= 0:
        msg = "Die Menge muss groesser als 0 sein"
        raise _RowError(msg)
    if cost is not None and cost < 0:
        msg = "Der Einstand darf nicht negativ sein"
        raise _RowError(msg)
    note = _note(cells.get("notiz", ""))
    return FileLine(number, isin, quantity, UNITS.get(unit_name), cost, note)


def parse_holdings(content: bytes, kind: DepotKind) -> ParsedFile:
    """Liest eine Datei; wirft ``FileError``, wenn sie als Ganzes nicht lesbar ist."""
    text = _text(content)
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=";")
    columns: list[str] | None = None
    seen_header = False
    lines: list[FileLine] = []
    rejected: list[RejectedRow] = []
    first_row: dict[str, int] = {}
    try:
        for row in reader:
            if not any(cell.strip() for cell in row):
                continue
            number = reader.line_num
            if len(lines) + len(rejected) >= MAX_LINES:
                msg = f"Hoechstens {MAX_LINES} Zeilen je Datei"
                raise FileError(msg)
            if not seen_header:
                seen_header = True
                columns = _columns(row)
                if columns is not None:
                    continue
            names = columns or list(COLUMNS)
            extra = [cell for cell in row[len(names) :] if cell.strip()]
            try:
                if extra:
                    msg = f"Zu viele Spalten (erwartet: {';'.join(names)})"
                    raise _RowError(msg)
                line = _line(number, dict(zip(names, row, strict=False)), kind)
                if line.isin in first_row:
                    msg = f"{line.isin} steht schon in Zeile {first_row[line.isin]}"
                    raise _RowError(msg)
            except _RowError as e:
                rejected.append(RejectedRow(number, str(e)))
                continue
            first_row[line.isin] = number
            lines.append(line)
    except csv.Error as e:
        msg = f"Die Datei ist kein lesbares CSV: {e}"
        raise FileError(msg) from None
    if not lines and not rejected:
        msg = "Die Datei enthaelt keine Position"
        raise FileError(msg)
    return ParsedFile(tuple(lines), tuple(rejected))


def compare(current: Sequence[HoldingLine], new: Sequence[HoldingLine]) -> list[ImportEntry]:
    """Abgleich nach ISIN: zuerst die Zeilen der Datei, dann was entfaellt."""
    before = {line.isin: line for line in current}
    after = {line.isin for line in new}
    entries = [
        ImportEntry(
            line.isin,
            "new"
            if line.isin not in before
            else ("unchanged" if same_position(before[line.isin], line) else "changed"),
            before.get(line.isin),
            line,
        )
        for line in new
    ]
    entries += [
        ImportEntry(line.isin, "removed", line, None) for line in current if line.isin not in after
    ]
    return entries


def _decimal(value: Decimal | None) -> str:
    return "" if value is None else format(value.normalize(), "f").replace(".", ",")


def _guarded(note: str | None) -> str:
    if not note:
        return ""
    return f"'{note}" if note.startswith(FORMULA_START) else note


def write_holdings(lines: Sequence[HoldingLine]) -> bytes:
    """Die Positionen im eigenen Format (UTF-8 mit BOM, LF)."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";", lineterminator="\n")
    writer.writerow(COLUMNS)
    for line in lines:
        writer.writerow(
            [
                line.isin,
                _decimal(line.quantity),
                _decimal(line.cost_basis_eur),
                _guarded(line.note),
                UNIT_NAMES[line.unit],
            ]
        )
    return ("﻿" + buffer.getvalue()).encode("utf-8")
