"""Zeitreihen je Titel (ADR-0010): Aktienanzahl (F1.3) und Kurshistorie (F1.4).

Parser, der gespeicherte Stand je Titel und das 12-1-Momentum (F2.3, ADR-0011). Gespeichert
wird im Repository.
Die Parser kennen keine yfinance-Namen: Der Abruf benennt die Spalten vorher um
(``va_market_data.adapters.yahoo.PRICE_FIELDS``).
"""

from __future__ import annotations

import math
from bisect import bisect_right
from dataclasses import dataclass, field
from datetime import timedelta
from itertools import pairwise
from typing import TYPE_CHECKING, Any

import pandas as pd

from .periods import period_end

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import date, datetime

# Groesste Zahl in einer BIGINT-Spalte; darueber scheiterte das Speichern des Titels
MAX_BIGINT = 2**63 - 1

# Spalten der Kurshistorie nach dem Abruf
PRICE_COLUMNS = ("close", "adj_close", "dividend", "split")

# So weit zurueck liest der Abruf die gespeicherte Aktienanzahl und die Kurse: ein Jahr fuer
# Netto-Emission (F2.2) und Momentum (F2.3), ihre Fenster und das Alter des Stichtags, mit Reserve
RECENT_HISTORY_DAYS = 550

# 12-1-Momentum (F2.3): Rendite von 365 bis 30 Tage vor dem juengsten Handelstag. Ein Zieltag
# gilt mit dem Handelstag davor, hoechstens so viele Tage frueher; die Kurse duerfen beim Abruf
# hoechstens so alt sein.
MOMENTUM_LOOKBACK_DAYS = 365
MOMENTUM_SKIP_DAYS = 30
MOMENTUM_MAX_GAP_DAYS = 7
MOMENTUM_MAX_AGE_DAYS = 14

# Yahoo rechnet Adj Close bei jedem Abruf minimal anders (gemessen: bis 6e-7 relativ).
# Korrekturen, Splits und Dividendenanpassungen liegen um Groessenordnungen darueber.
PRICE_REL_TOL = 1e-5


@dataclass(frozen=True)
class HistoryState:
    """Bis wann die Historie eines Titels gespeichert ist - bestimmt, ab wann nachgeladen wird.

    ``None``: noch nichts gespeichert, der Abruf holt die ganze Historie.
    """

    last_share_date: date | None = None
    last_price_date: date | None = None
    # Tage mit gespeichertem Split: Ein neuer Split im Abruffenster laedt alle Kurse neu
    price_split_days: frozenset[date] = frozenset()
    # Gespeicherte Aktienanzahl und Kurse (juengste Version je Tag) der letzten
    # ``RECENT_HISTORY_DAYS``: Der Abruf holt nur die neuen Tage, Netto-Emission (F2.2) und
    # Momentum (F2.3) brauchen das Jahr davor
    stored_shares: Mapping[date, int] = field(default_factory=dict)
    stored_prices: Mapping[date, PriceBar] = field(default_factory=dict)


@dataclass(frozen=True)
class PriceBar:
    """Ein Handelstag im Stand des Abrufs.

    ``close`` ist wie bei Yahoo split-, aber nicht dividendenbereinigt, ``adj_close``
    zusaetzlich dividendenbereinigt. ``adj_close`` aendert sich also mit jeder
    Dividende fuer alle frueheren Tage; eine durchgehende Reihe ergibt sich aus
    ``close``, ``dividend`` und ``split``.
    """

    close: float
    adj_close: float | None
    dividend: float
    split: float

    def same_as(self, other: PriceBar) -> bool:
        """Gleich bis auf das Float-Rauschen von Yahoo (``PRICE_REL_TOL``)."""
        if (self.adj_close is None) != (other.adj_close is None):
            return False
        pairs = [
            (self.close, other.close),
            (self.dividend, other.dividend),
            (self.split, other.split),
        ]
        if self.adj_close is not None and other.adj_close is not None:
            pairs.append((self.adj_close, other.adj_close))
        return all(math.isclose(a, b, rel_tol=PRICE_REL_TOL) for a, b in pairs)


def daily_share_counts(series: pd.Series | None) -> dict[date, int]:
    """Antwort von ``get_shares_full`` -> ein Wert je Tag.

    - Mehrere Werte an einem Tag: Es gilt der letzte in der Reihenfolge von yfinance
      (zeitlich sortiert). Yahoo liefert manche Tage doppelt, teils mit zwei Werten.
    - Der Tag ist der Kalendertag in der Zeitzone der Boerse, wie yfinance ihn liefert,
      nicht nach UTC umgerechnet (dieselbe Datumsregel wie fuer Abschluesse).
    - Fehlende und unendliche Werte zaehlen nicht, ebenso Werte, die gerundet nicht
      in ``share_count.shares`` passen (0 oder groesser als BIGINT).
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
        if day is None or not math.isfinite(shares):
            continue
        count = round(shares)
        if 0 < count <= MAX_BIGINT:
            counts[day] = count
    return counts


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except TypeError, ValueError:
        return None
    return number if math.isfinite(number) else None


def _exchange_day(moment: datetime, index: pd.Index) -> date:
    """Kalendertag von ``moment`` in der Zeitzone der Kurse."""
    stamp = pd.Timestamp(moment)
    tz = getattr(index, "tz", None)
    if tz is not None and stamp.tzinfo is not None:
        stamp = stamp.tz_convert(tz)
    return stamp.date()


def daily_price_bars(frame: pd.DataFrame | None, *, fetched_at: datetime) -> dict[date, PriceBar]:
    """Kurshistorie (Spalten ``PRICE_COLUMNS``) -> ein ``PriceBar`` je abgeschlossenem Handelstag.

    - Der Tag des Abrufs (in der Zeitzone der Boerse) laeuft noch und zaehlt nicht,
      sonst landete bei einem Lauf unter der Woche ein Intraday-Stand als Schlusskurs.
    - Ohne gueltigen Schlusskurs (> 0) zaehlt der Tag nicht, ebenso bei negativer
      Dividende oder negativem Split. Ein fehlendes ``adj_close`` bleibt leer.
    """
    bars: dict[date, PriceBar] = {}
    if frame is None or frame.empty:
        return bars
    open_day = _exchange_day(fetched_at, frame.index)
    columns = frame.reindex(columns=list(PRICE_COLUMNS))
    for stamp, close, adj_close, dividend, split in zip(
        frame.index, *(columns[c] for c in PRICE_COLUMNS), strict=True
    ):
        day = period_end(stamp)
        bar = PriceBar(
            close=_finite(close) or 0.0,
            adj_close=_finite(adj_close),
            dividend=_finite(dividend) or 0.0,
            split=_finite(split) or 0.0,
        )
        if day is None or day >= open_day or bar.close <= 0 or bar.dividend < 0 or bar.split < 0:
            continue
        bars[day] = bar
    return bars


def split_ratios(frame: pd.DataFrame | None) -> dict[date, float]:
    """Splits einer Kurshistorie (Spalten ``PRICE_COLUMNS``) je Tag: 2.0 = 2:1, 0.1 = 1:10."""
    if frame is None or frame.empty or "split" not in frame.columns:
        return {}
    return {
        day: ratio
        for stamp, split in frame["split"].items()
        if (day := period_end(stamp)) is not None and (ratio := _finite(split) or 0.0) > 0
    }


def split_days(frame: pd.DataFrame | None) -> set[date]:
    """Tage mit Split in einer Kurshistorie (Spalten ``PRICE_COLUMNS``)."""
    return set(split_ratios(frame))


def total_return(bars: Mapping[date, PriceBar], start: date, end: date) -> float | None:
    """Gesamtrendite mit Dividenden vom Schlusskurs an ``start`` bis zu dem an ``end``.

    Aus ``close`` und ``dividend``: Yahoo bereinigt ``close`` schon um Splits, ein neuer Split
    laedt die ganze Kurshistorie neu (``price_frames``). ``split`` noch einmal anzuwenden,
    zaehlte ihn doppelt. ``adj_close`` bleibt aussen vor: Gespeichert mischt es ueber Monate
    die Bereinigungsstaende verschiedener Abrufe.
    """
    if start not in bars or end not in bars or start >= end:
        return None
    days = sorted(day for day in bars if start <= day <= end)
    growth = 1.0
    for before, day in pairwise(days):
        if bars[before].close <= 0:
            return None
        growth *= (bars[day].close + bars[day].dividend) / bars[before].close
    return growth - 1


def _trading_day(days: list[date], target: date) -> date | None:
    """Der letzte Handelstag bis ``target``, hoechstens ``MOMENTUM_MAX_GAP_DAYS`` davor."""
    index = bisect_right(days, target) - 1
    if index < 0 or (target - days[index]).days > MOMENTUM_MAX_GAP_DAYS:
        return None
    return days[index]


def momentum_12_1(bars: Mapping[date, PriceBar], *, as_of: date) -> float | None:
    """12-1-Momentum: Gesamtrendite ueber zwoelf Monate ohne den letzten (JKP ``ret_12_1``,
    Jegadeesh und Titman 1993).

    Stichtag ist der juengste Handelstag, hoechstens ``MOMENTUM_MAX_AGE_DAYS`` vor ``as_of``.
    ``None`` ohne genug Historie.
    """
    if not bars:
        return None
    days = sorted(bars)
    latest = days[-1]
    if (as_of - latest).days > MOMENTUM_MAX_AGE_DAYS:
        return None
    start = _trading_day(days, latest - timedelta(days=MOMENTUM_LOOKBACK_DAYS))
    end = _trading_day(days, latest - timedelta(days=MOMENTUM_SKIP_DAYS))
    if start is None or end is None:
        return None
    return total_return(bars, start, end)
