"""Kopien der Marktdaten in portfolio (D3.4, ADR-0013; docs/architecture/depot/depots.md).

portfolio liest keine Tabellen von market-data. Es haelt eigene Kopien aus den Events:

- ``marketdata.securities.updated`` -> ``security_view`` (Stammdaten, das ganze ``SecurityV1``
  fuer die Analyse in D5), gueltig ist je ISIN der juengste Stand (``as_of``).
- ``marketdata.prices.completed`` -> ``price_view`` und ``fx_view``, gueltig ist je ISIN bzw.
  Waehrung der juengste Handelstag.
- ``scoring.run.completed`` -> ``score_view`` (D4.2): die Ranking-Zeilen und Einordnungen mit
  ISIN, gueltig ist je ISIN der juengste Bewertungslauf (``scoring_run_id``).

Alles nur angefuegt. Ein Event kommt einmal (Inbox des ``ReliableBus``); kommt es nach einem
Absturz doch zweimal, stehen dieselben Zeilen doppelt da, gelesen wird ohnehin das Juengste.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from collections.abc import Collection, Sequence
    from datetime import date, datetime
    from decimal import Decimal

    from ..domain.valuation import Market, Quote, Score, SecurityInfo


@dataclass(frozen=True)
class SecurityCopy:
    info: SecurityInfo
    payload: dict[str, Any]  # ``SecurityV1`` als JSON


@dataclass(frozen=True)
class FxRate:
    currency: str
    trade_date: date
    rate_to_eur: Decimal  # 1 Einheit der Waehrung in EUR


class MarketReader(Protocol):
    def market(self, isins: Collection[str]) -> Market:
        """Je ISIN die juengsten Stammdaten und Kurse, dazu der juengste Kurs jeder Waehrung."""
        ...

    def previous_scores(self, isins: Collection[str]) -> dict[str, Score]:
        """D5.2: je ISIN die Scores des vorherigen Bewertungslaufs, der sie kannte (HIN-Q03)."""
        ...

    def universe(self, scoring_run_id: int) -> list[Score]:
        """D5.5: die Titel des Rankings eines Bewertungslaufs (``reference = universe``)."""
        ...

    def security_payloads(self, isins: Collection[str]) -> dict[str, dict[str, Any]]:
        """D4.4: je ISIN das juengste ganze ``SecurityV1`` (ETF- und Anleihedaten) als JSON."""
        ...


class MarketStore(MarketReader, Protocol):
    def record_securities(
        self, copies: Sequence[SecurityCopy], *, as_of: date, at: datetime
    ) -> None: ...

    def record_prices(
        self, quotes: Sequence[Quote], rates: Sequence[FxRate], *, at: datetime
    ) -> None: ...

    def record_scores(self, scores: Sequence[Score], *, at: datetime) -> None:
        """D4.2: die Scores eines Bewertungslaufs, je ISIN eine Zeile."""
        ...
