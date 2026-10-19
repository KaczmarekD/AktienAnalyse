"""Zeitreihen je Titel (ADR-0010): Historie der Aktienanzahl (F1.3).

Nur Parser und der gespeicherte Stand je Titel. Gespeichert wird im Repository,
ausgewertet wird (noch) nichts - Ranking, Mail und CSV bleiben unveraendert.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .db.serialization import period_end

if TYPE_CHECKING:
    from datetime import date

    import pandas as pd


@dataclass(frozen=True)
class HistoryState:
    """Bis wann die Historie eines Titels gespeichert ist - bestimmt, ab wann nachgeladen wird.

    ``None``: noch nichts gespeichert, der Abruf holt die ganze Historie.
    """

    last_share_date: date | None = None


def daily_share_counts(series: pd.Series | None) -> dict[date, int]:
    """Antwort von ``get_shares_full`` -> ein Wert je Tag.

    - Mehrere Werte an einem Tag: Es gilt der letzte in der Reihenfolge von yfinance
      (zeitlich sortiert). Yahoo liefert manche Tage doppelt, teils mit zwei Werten.
    - Der Tag ist der Kalendertag in der Zeitzone der Boerse, wie yfinance ihn liefert,
      nicht nach UTC umgerechnet (dieselbe Datumsregel wie fuer Abschluesse).
    - Fehlende, unendliche und nicht positive Werte zaehlen nicht.
    """
    counts: dict[date, int] = {}
    if series is None:
        return counts
    for stamp, value in series.items():
        day = period_end(stamp)
        try:
            shares = float(value)
        except TypeError, ValueError:
            continue
        if day is None or not math.isfinite(shares) or shares <= 0:
            continue
        counts[day] = round(shares)
    return counts
