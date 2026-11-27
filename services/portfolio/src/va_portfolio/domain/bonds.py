"""Anleihen rechnen (D4.3, ANA-07; docs/architecture/depot/analyse.md, Abschnitt Anleihen).

Reine Rechnung je 100 Nennwert, Stichtag ist das Kursdatum (ohne Valuta-Verschiebung):

- **Kupontermine** rueckwaerts ab der Faelligkeit in Abstaenden von ``12 / frequency`` Monaten,
  immer am Tag der Faelligkeit, in kurzen Monaten am letzten (keine Monatsende-Regel). Eine
  unregelmaessige erste Periode kennen die Stammdaten nicht; gerechnet wird mit regelmaessigen.
- **Stueckzinsen** nach der Zinsmethode: ``ACT/ACT ICMA`` (Tage seit dem letzten Kupon durch
  Tage der Periode, wie bei Bundesanleihen) oder ``30E/360``. Ein Kupon am Stichtag gehoert dem
  Verkaeufer: Stueckzinsen 0, der naechste Kupon ist der folgende.
- **Rendite bis Faelligkeit** nach ICMA: Dirty-Preis = Summe der Zahlungen, abgezinst mit
  ``(1 + y / f) ** (v + k)``, ``v`` = Anteil der laufenden Periode bis zum naechsten Kupon.
  Geloest mit Bisektion zwischen -50 % und 100 %, ohne neue Abhaengigkeit.
- **Duration** aus denselben Zahlungen: Macaulay in Jahren, modifiziert ``/ (1 + y / f)``.
- **Sonderformen** ohne Rendite: variabel verzinst, Wandelanleihe, ewig, ohne Kupon in den
  Stammdaten. Erkannt an ``floating`` und am CFI-Code (ISO 10962: 2. Zeichen ``C`` Wandelanleihe,
  3. ``V`` variabel, 5. ``P``/``Q``/``R`` ohne Faelligkeit). Inflationsindexierte erkennt FIRDS
  nicht; sie rechnen wie feste Anleihen auf den Nominalkurs.

ESMA FIRDS liefert weder Kupontermine noch Zinsmethode. Ohne Angabe gilt, was fuer
Bundesanleihen stimmt: jaehrlich, ACT/ACT ICMA, Kupon am Jahrestag der Faelligkeit.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import date
from typing import Literal

DayCount = Literal["ACT/ACT ICMA", "30E/360"]
# Warum es keine Rendite gibt: Sonderform, faellig, oder der Kurs liegt ausserhalb der
# Grenzen der Bisektion (``out_of_range``, meist ein Datenfehler)
SpecialForm = Literal["floating", "convertible", "perpetual", "no_terms", "matured", "out_of_range"]

# Grenzen der Bisektion (Rendite pro Jahr) und ihre Genauigkeit
YIELD_LOW = -0.5
YIELD_HIGH = 1.0
YIELD_TOLERANCE = 1e-12
MAX_STEPS = 200
REDEMPTION = 100.0
DAYS_PER_YEAR = 365.25  # nur fuer die Restlaufzeit in Jahren


@dataclass(frozen=True)
class BondTerms:
    """Ausstattung einer Anleihe; ``coupon`` in Prozent pro Jahr, ``None`` heisst unbekannt."""

    coupon: float | None
    maturity: date | None
    frequency: int = 1  # Kupons pro Jahr
    day_count: DayCount = "ACT/ACT ICMA"
    floating: bool = False


@dataclass(frozen=True)
class BondFigures:
    """Kennzahlen je 100 Nennwert. Ohne Rendite nennt ``special`` den Grund."""

    on: date
    clean_price: float
    accrued: float | None = None
    dirty_price: float | None = None
    ytm: float | None = None  # pro Jahr, 0.026 = 2,6 %
    macaulay_duration: float | None = None  # Jahre
    modified_duration: float | None = None
    next_coupon: date | None = None
    coupon_dates: list[date] = field(default_factory=list)
    years_to_maturity: float | None = None
    special: SpecialForm | None = None


def special_form(terms: BondTerms, cfi: str | None = None) -> SpecialForm | None:
    """Sonderform aus den Stammdaten, ``None`` bei einer festverzinslichen Anleihe."""
    code = (cfi or "").upper()
    if len(code) == 6 and code[0] == "D" and code[1] == "C":
        return "convertible"
    if terms.floating or (len(code) == 6 and code[0] == "D" and code[2] == "V"):
        return "floating"
    if terms.maturity is None or (len(code) == 6 and code[0] == "D" and code[4] in "PQR"):
        return "perpetual"
    if terms.coupon is None:
        return "no_terms"
    return None


def _shift(maturity: date, months: int) -> date:
    """``months`` Monate vor der Faelligkeit, am Tag der Faelligkeit oder am Monatsletzten."""
    index = maturity.year * 12 + maturity.month - 1 - months
    year, month = divmod(index, 12)
    month += 1
    day = min(maturity.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _step(terms: BondTerms) -> int:
    if terms.frequency not in (1, 2, 4, 12):
        msg = f"Kupons pro Jahr: 1, 2, 4 oder 12, nicht {terms.frequency}"
        raise ValueError(msg)
    return 12 // terms.frequency


def _period(terms: BondTerms, on: date) -> tuple[date, date]:
    """Letzter Kupontermin bis einschliesslich ``on`` und der naechste danach."""
    assert terms.maturity is not None
    step = _step(terms)
    n = 0
    while _shift(terms.maturity, (n + 1) * step) > on:
        n += 1
    previous = _shift(terms.maturity, (n + 1) * step)
    following = _shift(terms.maturity, n * step)
    return previous, following


def coupon_dates(terms: BondTerms, *, after: date) -> list[date]:
    """Kupontermine nach ``after`` bis zur Faelligkeit, aufsteigend."""
    if terms.maturity is None or terms.maturity <= after:
        return []
    step = _step(terms)
    dates: list[date] = []
    n = 0
    while (when := _shift(terms.maturity, n * step)) > after:
        dates.append(when)
        n += 1
    return sorted(dates)


def _days_30e(start: date, end: date) -> int:
    return (
        360 * (end.year - start.year)
        + 30 * (end.month - start.month)
        + min(end.day, 30)
        - min(start.day, 30)
    )


def _fraction(terms: BondTerms, start: date, end: date, previous: date, following: date) -> float:
    """Anteil der Periode ``previous`` bis ``following``, der zwischen ``start`` und ``end`` liegt."""
    if terms.day_count == "30E/360":
        return _days_30e(start, end) / (360 / terms.frequency)
    return (end - start).days / (following - previous).days


def accrued_interest(terms: BondTerms, on: date) -> float:
    """Stueckzinsen je 100 Nennwert am Stichtag; 0 an einem Kupontermin."""
    if terms.coupon is None or terms.maturity is None or on >= terms.maturity:
        return 0.0
    previous, following = _period(terms, on)
    return terms.coupon / terms.frequency * _fraction(terms, previous, on, previous, following)


def _cash_flows(terms: BondTerms, on: date) -> tuple[float, list[float]]:
    """``v`` (Anteil bis zum naechsten Kupon) und die Zahlungen ab dem naechsten Kupon."""
    assert terms.coupon is not None
    assert terms.maturity is not None
    previous, following = _period(terms, on)
    v = _fraction(terms, on, following, previous, following)
    dates = coupon_dates(terms, after=on)
    flows = [terms.coupon / terms.frequency] * len(dates)
    flows[-1] += REDEMPTION
    return v, flows


def _present_value(rate: float, v: float, flows: list[float], frequency: int) -> float:
    base = 1 + rate / frequency
    return sum(flow / base ** (v + k) for k, flow in enumerate(flows))


def _solve(dirty: float, v: float, flows: list[float], frequency: int) -> float | None:
    """Rendite per Bisektion; der Barwert faellt mit der Rendite. ``None`` ausserhalb der Grenzen."""
    low, high = YIELD_LOW, YIELD_HIGH
    if not (
        _present_value(low, v, flows, frequency)
        >= dirty
        >= _present_value(high, v, flows, frequency)
    ):
        return None
    for _ in range(MAX_STEPS):
        middle = (low + high) / 2
        if _present_value(middle, v, flows, frequency) > dirty:
            low = middle
        else:
            high = middle
        if high - low < YIELD_TOLERANCE:
            break
    return (low + high) / 2


def bond_figures(
    terms: BondTerms, *, clean_price: float, on: date, cfi: str | None = None
) -> BondFigures:
    """Rendite, Duration, Stueckzinsen und Kupontermine zum Kurs ``clean_price`` (in Prozent)."""
    special = special_form(terms, cfi)
    if special is not None:
        return BondFigures(on=on, clean_price=clean_price, special=special)
    assert terms.maturity is not None
    if on >= terms.maturity:
        return BondFigures(on=on, clean_price=clean_price, special="matured")
    accrued = accrued_interest(terms, on)
    dirty = clean_price + accrued
    v, flows = _cash_flows(terms, on)
    dates = coupon_dates(terms, after=on)
    common = {
        "on": on,
        "clean_price": clean_price,
        "accrued": accrued,
        "dirty_price": dirty,
        "next_coupon": dates[0],
        "coupon_dates": dates,
        "years_to_maturity": (terms.maturity - on).days / DAYS_PER_YEAR,
    }
    ytm = _solve(dirty, v, flows, terms.frequency)
    if ytm is None:
        return BondFigures(**common, special="out_of_range")  # type: ignore[arg-type]
    base = 1 + ytm / terms.frequency
    values = [flow / base ** (v + k) for k, flow in enumerate(flows)]
    macaulay = sum((v + k) / terms.frequency * pv for k, pv in enumerate(values)) / sum(values)
    return BondFigures(
        **common,  # type: ignore[arg-type]
        ytm=ytm,
        macaulay_duration=macaulay,
        modified_duration=macaulay / base,
    )
