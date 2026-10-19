"""Die Periodenregel: Welches Spaltenlabel eines Abschlusses ist ein Periodenende?

Die eine Regel fuer Kennzahlen (Abruf) und Speicherung (``statement_value``), auch fuer
die Tage von Aktienanzahl und Kursen (vorher ``src.db.serialization``).
"""

from __future__ import annotations

from datetime import date
from typing import Any

import numpy as np
import pandas as pd


def period_end(label: Any) -> date | None:
    """Spaltenlabel eines Abschlusses (bei yfinance das Periodenende) -> ``date``.

    None, wenn das Label kein Datum ist: None/NaN/NaT, Text ohne Datum oder eine Zahl -
    pandas liest Zahlen als Nanosekunden seit 1970, ein RangeIndex waere sonst 1970-01-01.
    """
    if isinstance(label, int | float | np.number):
        return None
    try:
        ts = pd.Timestamp(label)
    except TypeError, ValueError:
        return None
    # None und "NaT" werfen nicht, sondern ergeben NaT
    return None if pd.isna(ts) else ts.date()
