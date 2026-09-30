"""Umwandlung von pandas/numpy-Werten in Datenbank-taugliche Python-Werte."""

from __future__ import annotations

import math
from datetime import date, datetime
from typing import Any

import numpy as np
import pandas as pd

_NUL = chr(0)  # PostgreSQL lehnt NUL-Zeichen in TEXT/JSONB ab


def to_python(value: Any) -> Any:
    """Skalar fuer eine DB-Spalte: NaN/NaT/pd.NA -> None, numpy -> Python."""
    if value is None or value is pd.NaT or value is pd.NA:
        return None
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, pd.Timestamp):
        return value.to_pydatetime()
    if isinstance(value, str) and _NUL in value:
        return value.replace(_NUL, "")
    return value


def json_safe(obj: Any) -> Any:
    """Rekursiv JSONB-tauglich machen. NaN/Inf sind kein gueltiges JSON -> null."""
    if isinstance(obj, dict):
        return {to_python(str(k)): json_safe(v) for k, v in obj.items()}
    if isinstance(obj, list | tuple | set):
        return [json_safe(v) for v in obj]
    obj = to_python(obj)
    if obj is None or isinstance(obj, bool | int | float | str):
        return obj
    if isinstance(obj, datetime | date):
        return obj.isoformat()
    return str(obj)
