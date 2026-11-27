"""Lebenszyklus der Hinweise (D5.2, HIN-03, ANA-10).

- Ein neuer Depotstand bekommt gleich seine Analyse mit Hinweisen (``analysis_run``) und das
  Event ``portfolio.analysis.completed`` mit Zahlen, ohne ISINs.
- Neue Kurse, Scores oder Stammdaten rechnen alle aktiven Depots neu; ein Lauf nur, wenn sich
  etwas geaendert hat.
- Status gegen den vorherigen Lauf: neu, besteht, erledigt.
- ``depots.hints`` liefert den juengsten Lauf mit den Texten des Katalogs; ohne Lauf wird einer
  gerechnet, ein fremdes Depot ist ``not_found``.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from va_contracts import new_envelope
from va_contracts.events.v1 import (
    ANALYSIS_COMPLETED,
    PRICES_COMPLETED,
    DailyCloseV1,
    PricesCompletedV1,
)
from va_contracts.rpc.v1 import DEPOTS_HINTS, DepotHintsReplyV1, DepotRefRequestV1
from va_platform.bus import InProcessBus
from va_portfolio.adapters.memory import MemoryDepotStore, MemoryMarketStore
from va_portfolio.application.depots import DepotService
from va_portfolio.application.market import SecurityCopy
from va_portfolio.domain.depots import CashLine, HoldingLine
from va_portfolio.domain.valuation import Quote, Score, SecurityInfo
from va_portfolio.entrypoints import handlers as market_handlers
from va_portfolio.entrypoints.rpc import handlers

ANNA, BEN = 1, 2
SAP = "DE0007164600"
FRIDAY = date(2026, 11, 27)
T0 = datetime(2026, 11, 27, 20, tzinfo=UTC)


def _setup():
    market = MemoryMarketStore()
    sap = SecurityInfo(SAP, "SAP SE", "equity", "EUR")
    market.record_securities([SecurityCopy(sap, {"isin": SAP})], as_of=FRIDAY, at=T0)
    market.record_prices([Quote(SAP, FRIDAY, Decimal(100), "EUR")], [], at=T0)
    store = MemoryDepotStore()
    service = DepotService(store, market=market, clock=lambda: T0)
    bus = InProcessBus(max_deliver=1)
    market_handlers.wire(bus, market, after=service.refresh_all)
    return bus, market, store, service


def _depot(service: DepotService, quantity: int = 30, cash: int = 7000) -> int:
    depot = service.create(ANNA, "depot", "DKB", None).depot
    service.save(
        ANNA, depot.id, 0, [HoldingLine(SAP, Decimal(quantity))], [CashLine(Decimal(cash))]
    )
    return depot.id


def _analysis_events(store: MemoryDepotStore):
    return [e for e in store.events if e.type == ANALYSIS_COMPLETED.type]


def _price(bus: InProcessBus, close: float) -> None:
    bus.publish(
        new_envelope(
            PRICES_COMPLETED,
            PricesCompletedV1(
                price_run_id=2,
                trade_date=FRIDAY,
                closes=[
                    DailyCloseV1(
                        isin=SAP,
                        symbol="SAP.DE",
                        trade_date=FRIDAY,
                        close=close,
                        currency="EUR",
                        source="yahoo",
                    )
                ],
                fx=[],
            ),
            source="va/market-data",
        )
    )


class TestRuns:
    def test_a_new_holding_gets_its_hints_at_once(self):
        _, _, store, service = _setup()
        depot_id = _depot(service)  # SAP 3000 von 10 000: 30 %, Kasse 70 %
        run = store.latest_run(depot_id)
        assert run is not None
        keys = {t.hint.key for t in run.hints}
        assert f"HIN-K01:{SAP}" in keys  # ueber 20 %: kritisch
        assert "HIN-A02:depot" in keys
        assert {t.status for t in run.hints} == {"new"}
        [event] = _analysis_events(store)
        assert (event.data.depot_id, event.data.owner_user_id, event.data.analysis_run_id) == (
            depot_id,
            ANNA,
            run.id,
        )
        assert event.data.critical == 1
        assert event.data.new == len(run.hints)

    def test_nothing_changed_no_new_run(self):
        _, _, store, service = _setup()
        _depot(service)
        assert service.refresh_all("prices") == 0
        assert len(store.runs) == 1

    def test_a_new_price_recomputes_with_status(self):
        bus, _, store, service = _setup()
        depot_id = _depot(service)
        _price(bus, 20.0)  # SAP 600 von 7600: unter 10 %
        run = store.latest_run(depot_id)
        assert run is not None
        assert len(store.runs) == 2
        statuses = {t.hint.key: t.status for t in run.hints}
        assert statuses[f"HIN-K01:{SAP}"] == "resolved"
        assert statuses["HIN-A02:depot"] == "existing"
        assert len(_analysis_events(store)) == 2

    def test_the_drop_against_the_previous_scoring_run(self):
        _, market, store, service = _setup()
        before = Score(SAP, 7, FRIDAY, "SAP.DE", "universe", composite_percentile=0.8)
        now = Score(SAP, 8, FRIDAY, "SAP.DE", "universe", composite_percentile=0.5)
        market.record_scores([before], at=T0)
        market.record_scores([now], at=T0)
        depot_id = _depot(service)
        run = store.latest_run(depot_id)
        assert run is not None
        [q03] = [t.hint for t in run.hints if t.hint.rule == "HIN-Q03"]
        assert q03.measured == 0.3

    def test_without_market_data_no_run(self):
        store = MemoryDepotStore()
        service = DepotService(store, clock=lambda: T0)
        depot_id = _depot(service)
        assert store.latest_run(depot_id) is None
        assert service.hints(ANNA, depot_id) is None


class TestOverRpc:
    def _ask(self, service: DepotService, user_id: int, depot_id: int) -> DepotHintsReplyV1:
        request = DepotRefRequestV1(user_id=user_id, depot_id=depot_id)
        reply = handlers(service)[DEPOTS_HINTS](request)
        assert isinstance(reply, DepotHintsReplyV1)
        return reply

    def test_the_hints_with_the_catalog_texts(self):
        _, _, _, service = _setup()
        depot_id = _depot(service)
        reply = self._ask(service, ANNA, depot_id)
        assert reply.hints is not None
        k01 = next(h for h in reply.hints.hints if h.rule == "HIN-K01")
        assert (k01.severity, k01.status, k01.title) == ("critical", "new", "Großer Einzeltitel")
        assert k01.approach.endswith(".")
        assert reply.hints.version == 1

    def test_without_run_one_is_computed(self):
        _, _, store, service = _setup()
        depot = service.create(ANNA, "watchlist", "Ideen", None).depot
        reply = self._ask(service, ANNA, depot.id)
        assert reply.hints is not None
        assert reply.hints.analysis_run_id is not None
        assert len(store.runs) == 1

    def test_a_foreign_depot_is_not_found(self):
        _, _, _, service = _setup()
        depot_id = _depot(service)
        reply = self._ask(service, BEN, depot_id)
        assert reply.error is not None
        assert reply.error.code == "not_found"
