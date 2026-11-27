"""portfolio am Bus (D3.4): Kopien von Stammdaten und Kursen aus market-data.

- ``marketdata.securities.updated`` -> ``MarketStore.record_securities``
- ``marketdata.prices.completed`` -> ``MarketStore.record_prices`` (Kurse und Waehrungskurse)
- ``scoring.run.completed`` -> ``MarketStore.record_scores`` (D4.2): Ranking-Zeilen und
  Einordnungen (D4.1) mit ISIN; ohne ISIN kann portfolio sie keiner Position zuordnen

Wirft der Speicher, stellt der Bus erneut zu. Folge-Events gibt es nicht: Die Bewertung rechnet
portfolio bei jeder Anfrage aus den Kopien (``DepotService``).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from va_contracts.events.v1 import PRICES_COMPLETED, SCORING_RUN_COMPLETED, SECURITIES_UPDATED

from ..application.market import FxRate, SecurityCopy
from ..domain.valuation import Quote, Score, SecurityInfo, score_reason

if TYPE_CHECKING:
    from va_contracts import Envelope
    from va_contracts.events.v1 import (
        PlacementV1,
        PricesCompletedV1,
        RankingRowV1,
        ScoringRunCompletedV1,
        SecuritiesUpdatedV1,
    )
    from va_platform.bus import EventBus

    from ..application.market import MarketStore

CONSUMER = "portfolio"


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _decimal(value: float) -> Decimal:
    """Ein Kurs aus dem Event (JSON-Zahl) so, wie er dort steht."""
    return Decimal(str(value))


class SecuritiesUpdatedHandler:
    def __init__(
        self, bus: EventBus, store: MarketStore, *, clock: Callable[[], datetime] = _utcnow
    ) -> None:
        self._bus = bus
        self._store = store
        self._clock = clock

    def subscribe(self) -> None:
        self._bus.subscribe(SECURITIES_UPDATED, CONSUMER, self)

    def __call__(self, env: Envelope[SecuritiesUpdatedV1]) -> None:
        copies = [
            SecurityCopy(
                SecurityInfo(s.isin, s.name, s.asset_class, s.currency),
                s.model_dump(mode="json"),
            )
            for s in env.data.securities
        ]
        self._store.record_securities(copies, as_of=env.data.as_of, at=self._clock())


class PricesCompletedHandler:
    def __init__(
        self, bus: EventBus, store: MarketStore, *, clock: Callable[[], datetime] = _utcnow
    ) -> None:
        self._bus = bus
        self._store = store
        self._clock = clock

    def subscribe(self) -> None:
        self._bus.subscribe(PRICES_COMPLETED, CONSUMER, self)

    def __call__(self, env: Envelope[PricesCompletedV1]) -> None:
        quotes = [
            Quote(
                isin=c.isin,
                trade_date=c.trade_date,
                close=_decimal(c.close),
                currency=c.currency,
                percent_of_par=c.percent_of_par,
                source=c.source,
                symbol=c.symbol,
            )
            for c in env.data.closes
        ]
        rates = [FxRate(f.currency, f.trade_date, _decimal(f.rate_to_eur)) for f in env.data.fx]
        self._store.record_prices(quotes, rates, at=self._clock())


class ScoringRunCompletedHandler:
    """D4.2: Scores je ISIN aus dem Ranking und den Einordnungen eines Bewertungslaufs."""

    def __init__(
        self, bus: EventBus, store: MarketStore, *, clock: Callable[[], datetime] = _utcnow
    ) -> None:
        self._bus = bus
        self._store = store
        self._clock = clock

    def subscribe(self) -> None:
        self._bus.subscribe(SCORING_RUN_COMPLETED, CONSUMER, self)

    def __call__(self, env: Envelope[ScoringRunCompletedV1]) -> None:
        data = env.data
        scores = [
            _ranked(row, data.scoring_run_id, data.as_of) for row in data.ranking if row.isin
        ] + [_placed(p, data.scoring_run_id, data.as_of) for p in data.placements if p.isin]
        self._store.record_scores(scores, at=self._clock())


def _ranked(row: RankingRowV1, scoring_run_id: int, as_of: date) -> Score:
    """Ein Titel des Rankings: dieselben Werte wie dort, mit Rang."""
    return Score(
        isin=str(row.isin),
        scoring_run_id=scoring_run_id,
        as_of=as_of,
        symbol=row.fundamentals.symbol,
        reference="universe",
        rank=row.rank_overall,
        value_score=row.value_score,
        quality_score=row.quality_score,
        composite_score=row.composite_score,
        composite_percentile=row.composite_percentile,
        value_trap_flag=row.value_trap_flag,
        value_trap_reason=row.value_trap_reason,
        industry_rule=row.industry_rule,
        reason=score_reason(row.value_score, row.quality_score),
    )


def _placed(placement: PlacementV1, scoring_run_id: int, as_of: date) -> Score:
    """Eine eingeordnete Aktie (D4.1): unter dem Groessenfilter oder von ausserhalb."""
    return Score(
        isin=str(placement.isin),
        scoring_run_id=scoring_run_id,
        as_of=as_of,
        symbol=placement.symbol,
        reference="below_size_filter" if placement.below_size_filter else "outside",
        value_score=placement.value_score,
        quality_score=placement.quality_score,
        composite_score=placement.composite_score,
        composite_percentile=placement.composite_percentile,
        value_trap_flag=placement.value_trap_flag,
        value_trap_reason=placement.value_trap_reason,
        industry_rule=placement.industry_rule,
        reason=placement.reason,
    )


def wire(bus: EventBus, store: MarketStore) -> None:
    SecuritiesUpdatedHandler(bus, store).subscribe()
    PricesCompletedHandler(bus, store).subscribe()
    ScoringRunCompletedHandler(bus, store).subscribe()
