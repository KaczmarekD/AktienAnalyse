"""Tests fuer die Umwandlung in DB-taugliche Werte."""

from __future__ import annotations

import math
from datetime import date

import numpy as np
import pandas as pd

from src.db.serialization import json_safe, to_python

NUL = chr(0)


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
