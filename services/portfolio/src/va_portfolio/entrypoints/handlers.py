"""portfolio am Bus (D3.4): Kopien von Stammdaten und Kursen aus market-data.

- ``marketdata.securities.updated`` -> ``MarketStore.record_securities``
- ``marketdata.prices.completed`` -> ``MarketStore.record_prices`` (Kurse und Waehrungskurse)

Wirft der Speicher, stellt der Bus erneut zu. Folge-Events gibt es nicht: Die Bewertung rechnet
portfolio bei jeder Anfrage aus den Kopien (``DepotService``).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from va_contracts.events.v1 import PRICES_COMPLETED, SECURITIES_UPDATED

from ..application.market import FxRate, SecurityCopy
from ..domain.valuation import Quote, SecurityInfo

if TYPE_CHECKING:
    from va_contracts import Envelope
    from va_contracts.events.v1 import PricesCompletedV1, SecuritiesUpdatedV1
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


def wire(bus: EventBus, store: MarketStore) -> None:
    SecuritiesUpdatedHandler(bus, store).subscribe()
    PricesCompletedHandler(bus, store).subscribe()
