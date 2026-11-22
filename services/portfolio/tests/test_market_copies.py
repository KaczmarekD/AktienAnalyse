"""Kopien der Marktdaten und Bewertung ueber Request/Reply (D3.4, DEP-07, DEP-13).

- ``securities.updated`` und ``prices.completed`` landen in den Kopien; je ISIN gilt das Juengste.
- ``depots.list`` traegt den Wert jedes Depots, ``depots.get`` dazu jede Position mit Kurs, Datum
  und Quelle. Der Export bleibt ohne Bewertung.
- Sind die Kopien nicht lesbar, kommen die Depots ohne Bewertung.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import pytest

from va_contracts import new_envelope
from va_contracts.events.v1 import (
    PRICES_COMPLETED,
    SECURITIES_UPDATED,
    DailyCloseV1,
    FxDailyV1,
    PricesCompletedV1,
    SecuritiesUpdatedV1,
)
from va_contracts.rpc.v1 import (
    DEPOTS_EXPORT,
    DEPOTS_GET,
    DEPOTS_LIST,
    DepotExportRequestV1,
    DepotListRequestV1,
    DepotRefRequestV1,
)
from va_contracts.securities import SecurityV1
from va_platform.bus import InProcessBus
from va_portfolio.adapters.memory import MemoryDepotStore, MemoryMarketStore
from va_portfolio.application.depots import DepotService
from va_portfolio.domain.depots import CashLine, HoldingLine
from va_portfolio.entrypoints import handlers as market_handlers
from va_portfolio.entrypoints.rpc import handlers

ANNA = 1
SAP = "DE0007164600"
APPLE = "US0378331005"
FRIDAY = date(2026, 11, 20)
THURSDAY = date(2026, 11, 19)


def _securities(as_of: date, *securities: SecurityV1):
    return new_envelope(
        SECURITIES_UPDATED,
        SecuritiesUpdatedV1(as_of=as_of, securities=list(securities)),
        source="va/market-data",
    )


def _prices(trade_date: date, *closes: DailyCloseV1, fx: list[FxDailyV1] | None = None):
    return new_envelope(
        PRICES_COMPLETED,
        PricesCompletedV1(price_run_id=1, trade_date=trade_date, closes=list(closes), fx=fx or []),
        source="va/market-data",
    )


def _close(isin: str, close: float, currency: str = "EUR", day: date = FRIDAY) -> DailyCloseV1:
    return DailyCloseV1(
        isin=isin, symbol="X", trade_date=day, close=close, currency=currency, source="yahoo"
    )


@pytest.fixture
def market() -> MemoryMarketStore:
    return MemoryMarketStore()


@pytest.fixture
def bus(market) -> InProcessBus:
    bus = InProcessBus(max_deliver=1)
    market_handlers.wire(bus, market)
    return bus


@pytest.fixture
def service(market) -> DepotService:
    return DepotService(MemoryDepotStore(), market=market)


@pytest.fixture
def rpc(service) -> dict[Any, Any]:
    return handlers(service)


def _depot_with(service: DepotService, *lines: HoldingLine, cash: str | None = None) -> int:
    depot = service.create(ANNA, "depot", "DKB", None).depot
    service.save(ANNA, depot.id, 0, list(lines), [CashLine(Decimal(cash))] if cash else [])
    return depot.id


class TestCopies:
    def test_newest_security_and_price_count(self, bus, market):
        bus.publish(_securities(FRIDAY, SecurityV1(isin=SAP, name="SAP SE", asset_class="equity")))
        bus.publish(
            _securities(THURSDAY, SecurityV1(isin=SAP, name="SAP alt", asset_class="equity"))
        )
        bus.publish(_prices(FRIDAY, _close(SAP, 231.5)))
        bus.publish(_prices(THURSDAY, _close(SAP, 220.0, day=THURSDAY)))  # spaet zugestellt
        copy = market.market([SAP])
        assert copy.securities[SAP].name == "SAP SE"
        assert copy.quotes[SAP].close == Decimal("231.5")  # Decimal wie im Event, ohne Float-Rest
        assert copy.quotes[SAP].source == "yahoo"

    def test_rates_to_euro(self, bus, market):
        fx = [FxDailyV1(currency="USD", trade_date=FRIDAY, rate_to_eur=0.92)]
        bus.publish(_prices(FRIDAY, _close(APPLE, 190.0, "USD"), fx=fx))
        assert market.market([APPLE]).fx == {"USD": Decimal("0.92")}

    def test_the_whole_security_is_kept_for_the_analysis(self, bus, market):
        bus.publish(_securities(FRIDAY, SecurityV1(isin=SAP, name="SAP SE", asset_class="equity")))
        assert market.payloads[SAP]["name"] == "SAP SE"


class TestValuationOverRpc:
    def test_list_carries_the_value_without_positions(self, bus, service, rpc):
        bus.publish(_prices(FRIDAY, _close(SAP, 231.5)))
        _depot_with(service, HoldingLine(SAP, Decimal(10)), cash="100")
        [depot] = rpc[DEPOTS_LIST](DepotListRequestV1(user_id=ANNA)).depots
        assert depot.valuation is not None
        assert depot.valuation.value_eur == Decimal("2415.00")
        assert depot.valuation.positions == []
        assert depot.valuation.pending == 1  # noch keine Stammdaten

    def test_get_carries_each_position(self, bus, service, rpc):
        bus.publish(_securities(FRIDAY, SecurityV1(isin=SAP, name="SAP SE", asset_class="equity")))
        bus.publish(_prices(FRIDAY, _close(SAP, 231.5)))
        depot_id = _depot_with(
            service,
            HoldingLine(SAP, Decimal(10), cost_basis_eur=Decimal(2000)),
            HoldingLine(APPLE, Decimal(3)),
        )
        reply = rpc[DEPOTS_GET](DepotRefRequestV1(user_id=ANNA, depot_id=depot_id))
        valuation = reply.depot.valuation
        assert (valuation.complete, valuation.unvalued) == (False, 1)
        sap, apple = valuation.positions
        assert (sap.name, sap.price, sap.price_date, sap.price_source) == (
            "SAP SE",
            Decimal("231.5"),
            FRIDAY,
            "yahoo",
        )
        assert (sap.value_eur, sap.difference_eur) == (Decimal("2315.00"), Decimal("315.00"))
        assert (apple.value_eur, apple.missing, apple.pending) == (None, "price", True)
        # Im JSON Zahlen im String, nie float
        assert reply.model_dump(mode="json")["depot"]["valuation"]["value_eur"] == "2315.00"

    def test_export_without_valuation(self, service, rpc):
        _depot_with(service, HoldingLine(SAP, Decimal(10)))
        [exported] = rpc[DEPOTS_EXPORT](DepotExportRequestV1(user_id=ANNA)).depots
        assert exported.depot.valuation is None

    def test_unreadable_copies_cost_only_the_valuation(self, service, market, rpc):
        _depot_with(service, HoldingLine(SAP, Decimal(10)))

        def broken(isins):
            msg = "Datenbank weg"
            raise RuntimeError(msg)

        market.market = broken  # type: ignore[method-assign]
        [depot] = rpc[DEPOTS_LIST](DepotListRequestV1(user_id=ANNA)).depots
        assert (depot.positions, depot.valuation) == (1, None)

    def test_without_market_data_no_valuation(self):
        service = DepotService(MemoryDepotStore())
        _depot_with(service, HoldingLine(SAP, Decimal(10)))
        rpc: dict[Any, Any] = handlers(service)
        [depot] = rpc[DEPOTS_LIST](DepotListRequestV1(user_id=ANNA)).depots
        assert depot.valuation is None


def test_handlers_stamp_the_receipt():
    seen: list[datetime] = []

    class Store(MemoryMarketStore):
        def record_prices(self, quotes, rates, *, at):
            seen.append(at)

    bus = InProcessBus(max_deliver=1)
    at = datetime(2026, 11, 20, 22, 45, tzinfo=UTC)
    market_handlers.PricesCompletedHandler(bus, Store(), clock=lambda: at).subscribe()
    bus.publish(_prices(FRIDAY, _close(SAP, 1.0)))
    assert seen == [at]
