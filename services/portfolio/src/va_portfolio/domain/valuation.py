"""Bewertung eines Depots (D3.4, DEP-07, DEP-13, WP-11; docs/architecture/depot/depots.md).

Reine Rechnung aus dem Depotstand und den Kopien der Marktdaten (``Market``):

- Wert einer Position = Menge x letzter Schlusskurs x Waehrungskurs (1 Einheit in EUR). Anleihen
  stehen mit dem Nennwert im Depot und haben einen Kurs in Prozent vom Nennwert: Nennwert x Kurs /
  100. Passt der Kurs nicht zur Einheit (Prozentkurs je Stueck), gibt es keinen Wert.
- Fehlt der Kurs, der Waehrungskurs oder passt die Einheit nicht, fehlt der Wert sichtbar mit
  Grund (``missing``), nie als 0. Das Depot zaehlt solche Positionen (``unvalued``).
- Ohne Stammdaten ist eine Position "wird geprueft" (``pending``, WP-13); ein Kurs zaehlt trotzdem.
- Einstand und Differenz nur, wo der Einstand erfasst ist; die Summe der Differenzen nur ueber
  Positionen mit Einstand und Wert (DEP-13, nur Anzeige).
- Werte in EUR auf Cent gerundet (kaufmaennisch); Kurse und Waehrungskurse unveraendert.
- Eine Beobachtungsliste hat keine Mengen, also keinen Wert, nur die Kurse.
- Seit D4.2 traegt jede Position die Scores ihrer ISIN aus dem juengsten Bewertungslauf, der sie
  kennt (``Score``), auch in einer Beobachtungsliste; ohne fehlen sie.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from va_contracts.portfolio import DepotKind

    from .depots import CashLine, HoldingLine

EUR = "EUR"
CENT = Decimal("0.01")
HUNDRED = Decimal(100)

Missing = Literal["price", "fx", "unit"]


@dataclass(frozen=True)
class SecurityInfo:
    """Stammdaten eines Wertpapiers, soweit die Bewertung sie braucht (Kopie aus market-data)."""

    isin: str
    name: str
    asset_class: str
    currency: str | None = None


@dataclass(frozen=True)
class Quote:
    """Letzter Schlusskurs in Hauptwaehrung; bei Anleihen in Prozent vom Nennwert."""

    isin: str
    trade_date: date
    close: Decimal
    currency: str
    percent_of_par: bool = False
    source: str | None = None  # yahoo, bundesbank
    symbol: str | None = None


@dataclass(frozen=True)
class Score:
    """Scores einer Aktie aus einem Bewertungslauf (D4.2, Kopie aus ``scoring.run.completed``).

    ``reference``: ``universe`` (Titel des Rankings, mit ``rank``), ``below_size_filter`` oder
    ``outside`` (eingeordnet, D4.1). ``as_of``: Stand des Abrufs des Bewertungslaufs.
    """

    isin: str
    scoring_run_id: int
    as_of: date
    symbol: str
    reference: str
    rank: int | None = None
    value_score: float | None = None
    quality_score: float | None = None
    composite_score: float | None = None
    composite_percentile: float | None = None
    value_trap_flag: bool = False
    value_trap_reason: str | None = None
    industry_rule: bool = False
    reason: str | None = None


def score_reason(value: float | None, quality: float | None) -> str | None:
    """Warum es keinen Composite gibt (wie ``PlacementV1.reason``); mit beiden ``None``."""
    if value is None and quality is None:
        return "no_data"
    if value is None:
        return "no_value"
    if quality is None:
        return "no_quality"
    return None


@dataclass(frozen=True)
class Market:
    """Die Kopien der Marktdaten fuer eine Bewertung, je ISIN bzw. Waehrung das Juengste."""

    securities: Mapping[str, SecurityInfo]
    quotes: Mapping[str, Quote]
    fx: Mapping[str, Decimal]  # Waehrung -> 1 Einheit in EUR; EUR ist immer 1
    # D4.2: je ISIN die Scores aus dem juengsten Bewertungslauf, der sie kennt
    scores: Mapping[str, Score] = field(default_factory=dict)


@dataclass(frozen=True)
class PositionValue:
    line: HoldingLine
    security: SecurityInfo | None
    quote: Quote | None
    fx_rate: Decimal | None
    value_eur: Decimal | None
    missing: Missing | None  # nur bei einer Menge ohne Wert
    score: Score | None = None  # D4.2

    @property
    def pending(self) -> bool:
        """ "Wird geprueft": market-data hat noch keine Stammdaten geliefert."""
        return self.security is None

    @property
    def difference_eur(self) -> Decimal | None:
        cost = self.line.cost_basis_eur
        if cost is None or self.value_eur is None:
            return None
        return (self.value_eur - cost).quantize(CENT, ROUND_HALF_UP)


@dataclass(frozen=True)
class DepotValue:
    kind: DepotKind
    positions: tuple[PositionValue, ...]
    cash_eur: Decimal

    @property
    def positions_eur(self) -> Decimal | None:
        """Summe der bewerteten Positionen; ``None`` bei einer Beobachtungsliste."""
        if self.kind == "watchlist":
            return None
        return sum((p.value_eur for p in self.positions if p.value_eur is not None), Decimal(0))

    @property
    def value_eur(self) -> Decimal | None:
        positions = self.positions_eur
        return None if positions is None else (positions + self.cash_eur).quantize(CENT)

    @property
    def unvalued(self) -> int:
        return sum(p.missing is not None for p in self.positions)

    @property
    def complete(self) -> bool:
        return self.unvalued == 0

    @property
    def pending(self) -> int:
        return sum(p.pending for p in self.positions)

    @property
    def cost_basis_eur(self) -> Decimal | None:
        known = [p.line.cost_basis_eur for p in self.positions if p.line.cost_basis_eur is not None]
        return sum(known, Decimal(0)).quantize(CENT) if known else None

    @property
    def difference_eur(self) -> Decimal | None:
        known = [d for p in self.positions if (d := p.difference_eur) is not None]
        return sum(known, Decimal(0)).quantize(CENT) if known else None

    @property
    def price_date(self) -> date | None:
        """Der aelteste Kurs der bewerteten Positionen: so alt ist der Wert hoechstens."""
        dates = [p.quote.trade_date for p in self.positions if p.value_eur is not None and p.quote]
        return min(dates) if dates else None


def _fx(currency: str, fx: Mapping[str, Decimal]) -> Decimal | None:
    return Decimal(1) if currency == EUR else fx.get(currency)


def value_position(line: HoldingLine, market: Market) -> PositionValue:
    security = market.securities.get(line.isin)
    quote = market.quotes.get(line.isin)
    fx_rate = _fx(quote.currency, market.fx) if quote is not None else None

    score = market.scores.get(line.isin)

    def result(value: Decimal | None, missing: Missing | None) -> PositionValue:
        return PositionValue(line, security, quote, fx_rate, value, missing, score)

    if line.quantity is None:  # Beobachtungsliste
        return result(None, None)
    if quote is None:
        return result(None, "price")
    if quote.percent_of_par != (line.unit == "nominal"):
        return result(None, "unit")
    if fx_rate is None:
        return result(None, "fx")
    price = quote.close / HUNDRED if quote.percent_of_par else quote.close
    return result((line.quantity * price * fx_rate).quantize(CENT, ROUND_HALF_UP), None)


def value_depot(
    kind: DepotKind, lines: Sequence[HoldingLine], cash: Sequence[CashLine], market: Market
) -> DepotValue:
    """Kasse vorerst nur in EUR (``CashLineV1``)."""
    cash_eur = sum((c.amount for c in cash), Decimal(0)).quantize(CENT, ROUND_HALF_UP)
    return DepotValue(kind, tuple(value_position(line, market) for line in lines), cash_eur)
