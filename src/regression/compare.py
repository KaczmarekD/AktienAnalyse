"""Vergleich eines nachgespielten Bewertungslaufs mit dem gespeicherten.

Reine Funktionen ohne Datenbank. Gleitkommazahlen gelten bis auf die letzten Stellen als
gleich (wie beim Golden-Master), "leer" und NaN ebenfalls.
"""

from __future__ import annotations

import io
import math
from collections.abc import Hashable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import pandas as pd

from va_platform.serialization import to_python

REL_TOL = 1e-9
ABS_TOL = 1e-12

SCORE_FIELDS = (
    "passed_filter",
    "value_score",
    "quality_score",
    "composite_score",
    "value_trap_flag",
    "rank_overall",
)
FACTOR_FIELDS = ("raw_value", "percentile_rank")

PRESENT = "vorhanden"
ABSENT = "fehlt"


@dataclass(frozen=True)
class Difference:
    """Ein abweichender Wert: ``area`` scores/factors/csv, ``field`` die Spalte."""

    area: str
    symbol: str
    field: str
    expected: Any
    actual: Any

    def __str__(self) -> str:
        where = f"{self.symbol} " if self.symbol else ""
        return f"{where}{self.field}: {show(self.expected)} -> {show(self.actual)}"


def show(value: Any) -> str:
    if value is None:
        return "leer"
    if isinstance(value, float):
        return f"{value:.10g}"
    return str(value)


def same(expected: Any, actual: Any) -> bool:
    a, b = to_python(expected), to_python(actual)
    if a is None or b is None:
        return a is None and b is None
    if isinstance(a, int | float) and isinstance(b, int | float):
        return math.isclose(float(a), float(b), rel_tol=REL_TOL, abs_tol=ABS_TOL)
    return a == b


def compare_scores(expected: pd.DataFrame, actual: pd.DataFrame) -> list[Difference]:
    """Scores, Flag und Rang je Titel; die Reihenfolge der Zeilen zaehlt nicht."""
    return _compare_rows("scores", _rows(expected, ("symbol",)), _rows(actual, ("symbol",)))


def compare_factor_scores(expected: pd.DataFrame, actual: pd.DataFrame) -> list[Difference]:
    """Rohwert und Perzentilrang je Titel und Faktor."""
    key = ("symbol", "factor_key")
    return _compare_rows("factors", _rows(expected, key), _rows(actual, key))


def compare_csv(expected: bytes, actual: bytes) -> list[Difference]:
    """CSV des Reports Zeile fuer Zeile: Die Reihenfolge ist das Ranking und zaehlt."""
    old, new = _read_csv(expected), _read_csv(actual)
    if list(old.columns) != list(new.columns):
        return [Difference("csv", "", "spalten", ", ".join(old.columns), ", ".join(new.columns))]
    found: list[Difference] = []
    for i in range(max(len(old), len(new))):
        if i >= len(new):
            found.append(Difference("csv", _label(old, i), "zeile", PRESENT, ABSENT))
            continue
        if i >= len(old):
            found.append(Difference("csv", _label(new, i), "zeile", ABSENT, PRESENT))
            continue
        for column in old.columns:
            before, after = str(old.at[i, column]), str(new.at[i, column])
            if not _same_cell(before, after):
                found.append(Difference("csv", _label(old, i), str(column), before, after))
    return found


def _rows(
    frame: pd.DataFrame, key: Sequence[str]
) -> dict[tuple[Hashable, ...], Mapping[Hashable, Any]]:
    return {tuple(row[k] for k in key): row for row in frame.to_dict("records")}


def _compare_rows(
    area: str,
    expected: Mapping[tuple[Hashable, ...], Mapping[Hashable, Any]],
    actual: Mapping[tuple[Hashable, ...], Mapping[Hashable, Any]],
) -> list[Difference]:
    fields = SCORE_FIELDS if area == "scores" else FACTOR_FIELDS
    found: list[Difference] = []
    for key in sorted(expected.keys() | actual.keys(), key=lambda k: tuple(map(str, k))):
        symbol = str(key[0])
        label = "titel" if len(key) == 1 else str(key[1])
        if key not in actual:
            found.append(Difference(area, symbol, label, PRESENT, ABSENT))
            continue
        if key not in expected:
            found.append(Difference(area, symbol, label, ABSENT, PRESENT))
            continue
        for field in fields:
            before, after = expected[key].get(field), actual[key].get(field)
            if not same(before, after):
                name = field if len(key) == 1 else f"{key[1]}.{field}"
                found.append(Difference(area, symbol, name, to_python(before), to_python(after)))
    return found


def _read_csv(data: bytes) -> pd.DataFrame:
    # Alles als Text: Zahlen vergleicht _same_cell mit Toleranz, der Rest muss gleich sein
    return pd.read_csv(
        io.BytesIO(data), sep=";", encoding="utf-8-sig", dtype=str, keep_default_na=False
    )


def _label(frame: pd.DataFrame, i: int) -> str:
    return str(frame.at[i, "symbol"]) if "symbol" in frame.columns else f"Zeile {i + 1}"


def _same_cell(before: str, after: str) -> bool:
    if before == after:
        return True
    try:
        a, b = float(before.replace(",", ".")), float(after.replace(",", "."))
    except ValueError:
        return False
    return math.isclose(a, b, rel_tol=REL_TOL, abs_tol=ABS_TOL)
