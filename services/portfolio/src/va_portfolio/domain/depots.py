"""Depots und Depotstaende (D3.1, docs/architecture/depot/depots.md), rein.

- Ein Depotstand ist vollstaendig und unveraenderlich (ADR-0013). Jede Speicherung ergibt die
  naechste Version, aber nur auf die neueste als Basis (DEP-03, sonst ``VersionConflict``).
- Mengen und Betraege sind ``Decimal``, nie ``float``.
- Beobachtungsliste (DEP-09): Wertpapiere ohne Menge, ohne Einstand, ohne Kasse.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal
from typing import get_args

from va_contracts.portfolio import (
    MAX_LINES,
    MAX_NAME,
    MAX_TEXT,
    DepotKind,
    DepotState,
    HoldingUnit,
    SnapshotSource,
)
from va_contracts.securities import valid_isin

UNITS: tuple[str, ...] = get_args(HoldingUnit)
CASH_CURRENCIES = ("EUR",)

__all__ = [
    "CashLine",
    "Depot",
    "DepotError",
    "Diff",
    "HoldingLine",
    "Snapshot",
    "VersionConflict",
    "check_holdings",
    "check_name",
    "diff",
    "next_version",
    "same_position",
]


class DepotError(ValueError):
    """Eine Eingabe passt nicht (Fehler ``invalid`` am Request/Reply)."""


class VersionConflict(Exception):
    """Die Basisversion ist nicht mehr die neueste; ``newest`` nennt sie."""

    def __init__(self, newest: int) -> None:
        super().__init__(f"Der Depotstand ist inzwischen bei Version {newest}")
        self.newest = newest


@dataclass(frozen=True)
class Depot:
    id: int
    owner_user_id: int
    kind: DepotKind
    name: str
    description: str | None
    status: DepotState
    created_at: datetime


@dataclass(frozen=True)
class HoldingLine:
    isin: str
    quantity: Decimal | None  # Stueck oder Nennwert; in der Beobachtungsliste leer
    unit: HoldingUnit = "pieces"
    cost_basis_eur: Decimal | None = None  # Einstandswert der ganzen Position
    note: str | None = None


@dataclass(frozen=True)
class CashLine:
    amount: Decimal
    currency: str = "EUR"


@dataclass(frozen=True)
class Snapshot:
    """Ein Depotstand; Version 0 ist der leere Stand vor der ersten Speicherung."""

    depot_id: int
    version: int
    source: SnapshotSource | None = None
    created_at: datetime | None = None
    created_by: int | None = None
    lines: tuple[HoldingLine, ...] = ()
    cash: tuple[CashLine, ...] = ()
    source_ref: str | None = None  # D3.5: SHA-256 der Datei bei Herkunft ``import``


@dataclass(frozen=True)
class Diff:
    added: int
    changed: int
    removed: int


def _text(value: str | None, label: str, limit: int) -> str | None:
    if value is None:
        return None
    text = value.strip()
    if len(text) > limit:
        msg = f"{label} hat hoechstens {limit} Zeichen"
        raise DepotError(msg)
    return text or None


def check_name(name: str, description: str | None) -> tuple[str, str | None]:
    """Name (1 bis 100 Zeichen) und Beschreibung, ohne Leerraum am Rand."""
    clean = _text(name, "Der Name", MAX_NAME)
    if not clean:
        msg = "Der Name fehlt"
        raise DepotError(msg)
    return clean, _text(description, "Die Beschreibung", MAX_TEXT)


def _finite(value: Decimal | None) -> bool:
    return value is None or value.is_finite()


def _check_line(kind: DepotKind, line: HoldingLine) -> HoldingLine:
    isin = line.isin.strip().upper()
    if not valid_isin(isin):
        msg = f"Keine gueltige ISIN: {line.isin!r}"
        raise DepotError(msg)
    if line.unit not in UNITS:
        msg = f"{isin}: unbekannte Einheit {line.unit!r}"
        raise DepotError(msg)
    if not (_finite(line.quantity) and _finite(line.cost_basis_eur)):
        msg = f"{isin}: Menge und Einstand muessen Zahlen sein"
        raise DepotError(msg)
    if kind == "watchlist":
        if line.quantity is not None or line.cost_basis_eur is not None:
            msg = f"{isin}: Eine Beobachtungsliste hat keine Mengen und keinen Einstand"
            raise DepotError(msg)
    elif line.quantity is None or line.quantity <= 0:
        msg = f"{isin}: Die Menge muss groesser als 0 sein"
        raise DepotError(msg)
    if line.cost_basis_eur is not None and line.cost_basis_eur < 0:
        msg = f"{isin}: Der Einstand darf nicht negativ sein"
        raise DepotError(msg)
    return replace(line, isin=isin, note=_text(line.note, f"{isin}: Die Notiz", MAX_TEXT))


def check_holdings(
    kind: DepotKind, lines: Iterable[HoldingLine], cash: Iterable[CashLine]
) -> tuple[tuple[HoldingLine, ...], tuple[CashLine, ...]]:
    """Positionen und Kasse eines neuen Depotstands, geprueft und bereinigt."""
    raw = list(lines)
    if len(raw) > MAX_LINES:
        msg = f"Hoechstens {MAX_LINES} Positionen je Depot"
        raise DepotError(msg)
    checked = tuple(_check_line(kind, line) for line in raw)
    seen: set[str] = set()
    for line in checked:
        if line.isin in seen:
            msg = f"{line.isin} steht doppelt im Depot"
            raise DepotError(msg)
        seen.add(line.isin)
    cash_lines = tuple(cash)
    if kind == "watchlist" and cash_lines:
        msg = "Eine Beobachtungsliste hat keine Kasse"
        raise DepotError(msg)
    if len(cash_lines) > 1 or any(c.currency not in CASH_CURRENCIES for c in cash_lines):
        msg = "Kasse: hoechstens eine Zeile, in EUR"
        raise DepotError(msg)
    if any(not c.amount.is_finite() for c in cash_lines):
        msg = "Kasse: der Betrag muss eine Zahl sein"
        raise DepotError(msg)
    return checked, cash_lines


def next_version(*, newest: int, base: int) -> int:
    """Die Version des neuen Depotstands; wirft ``VersionConflict`` auf eine alte Basis."""
    if base != newest:
        raise VersionConflict(newest)
    return newest + 1


def same_position(a: HoldingLine, b: HoldingLine) -> bool:
    """Gleich bis auf die ISIN; ``Decimal`` vergleicht 10 und 10.000 als gleich."""
    return (a.quantity, a.unit, a.cost_basis_eur, a.note) == (
        b.quantity,
        b.unit,
        b.cost_basis_eur,
        b.note,
    )


def diff(previous: Sequence[HoldingLine], current: Sequence[HoldingLine]) -> Diff:
    """Unterschied nach ISIN; ``Decimal`` vergleicht 10 und 10.000 als gleich."""
    before = {line.isin: line for line in previous}
    after = {line.isin: line for line in current}
    added = len(after.keys() - before.keys())
    removed = len(before.keys() - after.keys())
    changed = sum(
        1 for isin in after.keys() & before.keys() if not same_position(before[isin], after[isin])
    )
    return Diff(added, changed, removed)
