"""Tageskurse (D2.3, WP-06, WP-11): Schlusskurse und Waehrungskurse, rein.

- Gespeichert und gemeldet wird in Hauptwaehrung: London notiert in Pence (``GBp``/``GBX``),
  Johannesburg in Cent (``ZAc``), Tel Aviv in Agorot (``ILA``) - jeweils durch 100.
- Ein Kurs gilt fuer seinen Handelstag. Ein Feiertag bringt keinen neuen Tag; der letzte bleibt.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

EUR = "EUR"
# Untereinheit -> (Hauptwaehrung, Teiler)
MINOR_UNITS: dict[str, tuple[str, float]] = {
    "GBp": ("GBP", 100.0),
    "GBX": ("GBP", 100.0),
    "ZAc": ("ZAR", 100.0),
    "ILA": ("ILS", 100.0),
}


@dataclass(frozen=True)
class Quote:
    """Letzter Schlusskurs eines Symbols aus dem Sammelabruf, in der Notierung der Boerse."""

    symbol: str
    trade_date: date
    close: float


@dataclass(frozen=True)
class DailyClose:
    isin: str
    symbol: str | None
    trade_date: date
    close: float
    currency: str  # Hauptwaehrung
    # Notierung an der Boerse (z. B. GBp), fuer den naechsten Tag; nicht Teil des Events
    quote_currency: str | None = None


@dataclass(frozen=True)
class FxDaily:
    currency: str
    trade_date: date
    rate_to_eur: float


def to_major_unit(close: float, currency: str) -> tuple[float, str]:
    major = MINOR_UNITS.get(currency)
    if major is None:
        return close, currency
    unit, divisor = major
    return close / divisor, unit
