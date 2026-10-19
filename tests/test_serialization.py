"""Tests fuer die Umwandlung in DB-taugliche Werte."""

from __future__ import annotations

import math
from datetime import date

import numpy as np
import pandas as pd
import pytest

from src.db.serialization import json_safe, period_end, to_python

NUL = chr(0)


class TestPeriodEnd:
    @pytest.mark.parametrize(
        ("label", "expected"),
        [
            (pd.Timestamp("2025-12-31"), date(2025, 12, 31)),
            ("2025-12-31", date(2025, 12, 31)),
            (date(2025, 12, 31), date(2025, 12, 31)),
            (np.datetime64("2025-12-31"), date(2025, 12, 31)),
            # pd.Timestamp wirft hier nicht, sondern liefert NaT - das ist keine Periode
            (None, None),
            (float("nan"), None),
            ("NaT", None),
            (pd.NaT, None),
            ("keine Periode", None),
            # Zahlen liest pandas als Nanosekunden seit 1970 - kein Periodenende
            (0, None),
            (2023, None),
            (np.int64(1), None),
            (2023.0, None),
        ],
    )
    def test_cases(self, label, expected):
        assert period_end(label) == expected


class TestToPython:
    def test_missing_values_become_none(self):
        assert to_python(float("nan")) is None
        assert to_python(np.float64("inf")) is None
        assert to_python(pd.NaT) is None
        assert to_python(pd.NA) is None

    def test_numpy_scalars_become_python(self):
        assert type(to_python(np.int64(3))) is int
        assert to_python(np.bool_(True)) is True

    def test_nul_characters_are_removed(self):
        # PostgreSQL lehnt NUL in TEXT/JSONB ab - ein kaputter Yahoo-String
        # darf den Lauf nicht kippen
        assert to_python(f"Foo{NUL}Bar") == "FooBar"


class TestJsonSafe:
    def test_nested_structures(self):
        payload = {"a": [1.0, math.nan, {"b": np.float32(2.5)}], 3: date(2026, 9, 29)}
        assert json_safe(payload) == {"a": [1.0, None, {"b": 2.5}], "3": "2026-09-29"}

    def test_nul_in_keys_and_values_is_removed(self):
        assert json_safe({f"na{NUL}me": f"wert{NUL}"}) == {"name": "wert"}
