"""Fundamentale Anker je Titel (F3.1, ADR-0011, Punkt 6). Sie gehen nicht in den Composite ein.

- **Ertragskraftwert (EPV, Greenwald):** normalisierter NOPAT / Kapitalkosten r minus
  Nettoverschuldung, je Aktie und als Preis/EPV.
- **Implizites FCF-Wachstum (Reverse DCF):** das Wachstum, bei dem der heutige FCF ueber
  ``dcf_years`` Jahre und danach mit ``terminal_growth`` den Boersenwert ergibt.
- Beides auch bei r - 1 und r + 1 Prozentpunkt (``_r_low``, ``_r_high``).

Eingaben aus dem Snapshot: ``nopat_normalized`` (market-data), Nettoverschuldung =
``enterprise_value`` - ``market_cap``, FCF = ``market_cap`` / ``p_fcf``, ``shares_outstanding``.
Finanzwerte (Branche unter ``industry_prefixes``) bekommen keine Anker: Fuer sie gilt das
gerechtfertigte KBV im Abschnitt "Finanzwerte" (F2.4).
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd

from va_contracts.events.v1.ranking import ANCHOR_KEYS

from .scoring import industry_rule_applies

if TYPE_CHECKING:
    from .scoring import ScoringConfig

ANCHOR_COLUMNS: tuple[str, ...] = ANCHOR_KEYS

# Suchintervall des Reverse DCF und Sensitivitaet der Kapitalkosten
GROWTH_LOW = -0.20
GROWTH_HIGH = 0.40
SENSITIVITY = 0.01
_BISECTION_STEPS = 100
_TOLERANCE = 1e-9


def _number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except TypeError, ValueError:
        return None
    return number if math.isfinite(number) else None


def epv_equity(
    *, nopat: float | None, net_debt: float | None, cost_of_capital: float
) -> float | None:
    """Ertragskraftwert des Eigenkapitals: NOPAT / r minus Nettoverschuldung."""
    if nopat is None or net_debt is None or cost_of_capital <= 0:
        return None
    return nopat / cost_of_capital - net_debt


def _dcf_value(fcf: float, growth: float, r: float, terminal: float, years: int) -> float:
    factor = (1 + growth) / (1 + r)
    value = sum(fcf * factor**t for t in range(1, years + 1))
    last = fcf * (1 + growth) ** years
    return value + last * (1 + terminal) / (r - terminal) / (1 + r) ** years


def implied_fcf_growth(
    *,
    market_cap: float | None,
    fcf: float | None,
    cost_of_capital: float,
    terminal_growth: float,
    years: int,
) -> float | None:
    """Reverse DCF per Bisektion zwischen ``GROWTH_LOW`` und ``GROWTH_HIGH``.

    ``None`` ohne positiven FCF und Boersenwert, bei r <= g oder ohne Loesung im Intervall.
    """
    if market_cap is None or fcf is None or market_cap <= 0 or fcf <= 0:
        return None
    if cost_of_capital <= terminal_growth or years < 1:
        return None

    def gap(growth: float) -> float:
        return _dcf_value(fcf, growth, cost_of_capital, terminal_growth, years) - market_cap

    low, high = GROWTH_LOW, GROWTH_HIGH
    if gap(low) > 0 or gap(high) < 0:
        return None
    for _ in range(_BISECTION_STEPS):
        middle = (low + high) / 2
        if gap(middle) < 0:
            low = middle
        else:
            high = middle
        if high - low < _TOLERANCE:
            break
    return (low + high) / 2


def _column(frame: pd.DataFrame, name: str) -> pd.Series:
    if name in frame.columns:
        return frame[name]
    return pd.Series(np.nan, index=frame.index, dtype=float)


def _anchors_of(row: Mapping[Any, Any], cfg: ScoringConfig) -> dict[str, float | None]:
    empty: dict[str, float | None] = dict.fromkeys(ANCHOR_COLUMNS)
    if industry_rule_applies(row.get("industry"), tuple(cfg.industry_prefixes)):
        return empty
    market_cap = _number(row.get("market_cap"))
    enterprise_value = _number(row.get("enterprise_value"))
    net_debt = (
        None if market_cap is None or enterprise_value is None else enterprise_value - market_cap
    )
    p_fcf = _number(row.get("p_fcf"))
    fcf = None if market_cap is None or not p_fcf else market_cap / p_fcf
    nopat = _number(row.get("nopat_normalized"))
    shares = _number(row.get("shares_outstanding"))

    def epv_at(r: float) -> tuple[float | None, float | None]:
        epv = epv_equity(nopat=nopat, net_debt=net_debt, cost_of_capital=r)
        per_share = None if epv is None or not shares or shares <= 0 else epv / shares
        ratio = None if epv is None or epv <= 0 or market_cap is None else market_cap / epv
        return per_share, ratio

    def growth_at(r: float) -> float | None:
        return implied_fcf_growth(
            market_cap=market_cap,
            fcf=fcf,
            cost_of_capital=r,
            terminal_growth=cfg.terminal_growth,
            years=cfg.dcf_years,
        )

    r = cfg.cost_of_capital
    per_share, ratio = epv_at(r)
    return {
        "epv_per_share": per_share,
        "price_to_epv": ratio,
        "implied_fcf_growth": growth_at(r),
        "price_to_epv_r_low": epv_at(r - SENSITIVITY)[1],
        "price_to_epv_r_high": epv_at(r + SENSITIVITY)[1],
        "implied_fcf_growth_r_low": growth_at(r - SENSITIVITY),
        "implied_fcf_growth_r_high": growth_at(r + SENSITIVITY),
    }


def add_anchors(scored: pd.DataFrame, cfg: ScoringConfig) -> pd.DataFrame:
    """Die Ausgabe von ``score()`` plus die Anker als Spalten; sonst unveraendert."""
    out = scored.copy()
    inputs = pd.DataFrame(
        {
            name: _column(scored, name)
            for name in (
                "industry",
                "market_cap",
                "enterprise_value",
                "p_fcf",
                "nopat_normalized",
                "shares_outstanding",
            )
        }
    )
    rows = [_anchors_of(row, cfg) for row in inputs.to_dict("records")]
    anchors = pd.DataFrame(rows, index=scored.index, columns=list(ANCHOR_COLUMNS), dtype=float)
    for name in ANCHOR_COLUMNS:
        out[name] = anchors[name]
    return out
