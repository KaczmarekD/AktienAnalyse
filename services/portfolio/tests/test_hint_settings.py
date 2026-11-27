"""Schwellen, Zielallokation und Kenntnisnahme (D5.3, HIN-04, HIN-05, DEP-10, HIN-A01).

- Schwellen und Zielallokation je Depot, versioniert: Speichern auf eine alte Version ist ein
  Konflikt mit der neuesten, ein archiviertes Depot ist schreibgeschützt.
- Nach dem Speichern rechnet das Depot neu; neue Schwellen ändern die Hinweise, eine
  Zielallokation bringt HIN-A01.
- Zur Kenntnis genommen bleibt ein Hinweis, bis er schwerer wird oder sich sein Messwert um die
  Spanne der Regel verschlechtert.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from va_contracts.portfolio import HintParamsV1, TargetAllocationV1
from va_contracts.rpc.v1 import (
    DEPOTS_SETTINGS,
    HINT_ACK,
    HINT_PARAMS_SAVE,
    DepotHintsReplyV1,
    DepotRefRequestV1,
    DepotSettingsReplyV1,
    HintAckRequestV1,
    HintParamsSaveRequestV1,
)
from va_portfolio.adapters.memory import MemoryDepotStore, MemoryMarketStore
from va_portfolio.application.depots import ArchivedDepot, DepotService
from va_portfolio.application.market import SecurityCopy
from va_portfolio.domain.depots import CashLine, HoldingLine, VersionConflict
from va_portfolio.domain.valuation import Quote, SecurityInfo
from va_portfolio.entrypoints.rpc import handlers

ANNA, BEN = 1, 2
SAP = "DE0007164600"
FRIDAY = date(2026, 11, 27)
T0 = datetime(2026, 11, 27, 20, tzinfo=UTC)
K01 = f"HIN-K01:{SAP}"


def _setup(price: int = 100):
    market = MemoryMarketStore()
    sap = SecurityInfo(SAP, "SAP SE", "equity", "EUR")
    market.record_securities([SecurityCopy(sap, {"isin": SAP})], as_of=FRIDAY, at=T0)
    market.record_prices([Quote(SAP, FRIDAY, Decimal(price), "EUR")], [], at=T0)
    store = MemoryDepotStore()
    service = DepotService(store, market=market, clock=lambda: T0)
    depot = service.create(ANNA, "depot", "DKB", None).depot
    # SAP 15 x 100 = 1500 von 10 000: 15 %, Warnung
    service.save(ANNA, depot.id, 0, [HoldingLine(SAP, Decimal(15))], [CashLine(Decimal(8500))])
    return market, store, service, depot.id


def _keys(store: MemoryDepotStore, depot_id: int) -> dict[str, str]:
    run = store.latest_run(depot_id)
    assert run is not None
    return {t.hint.key: t.status for t in run.hints}


class TestSettings:
    def test_standard_without_stored_settings(self):
        _, _, service, depot_id = _setup()
        settings = service.settings(ANNA, depot_id)
        assert (settings.hint_params_version, settings.target_version) == (0, 0)
        assert dict(settings.target) == {}

    def test_new_thresholds_change_the_hints(self):
        _, store, service, depot_id = _setup()
        assert K01 in _keys(store, depot_id)
        params = HintParamsV1(k01_warning=0.2, k01_critical=0.3)
        settings = service.save_hint_params(ANNA, depot_id, 0, params)
        assert settings.hint_params_version == 1
        assert _keys(store, depot_id)[K01] == "resolved"

    def test_a_stale_version_is_a_conflict(self):
        _, _, service, depot_id = _setup()
        service.save_hint_params(ANNA, depot_id, 0, HintParamsV1())
        with pytest.raises(VersionConflict) as conflict:
            service.save_hint_params(ANNA, depot_id, 0, HintParamsV1())
        assert conflict.value.newest == 1

    def test_an_archived_depot_is_read_only(self):
        _, _, service, depot_id = _setup()
        service.archive(ANNA, depot_id)
        with pytest.raises(ArchivedDepot):
            service.save_target(ANNA, depot_id, 0, TargetAllocationV1())

    def test_a_target_brings_a01(self):
        _, store, service, depot_id = _setup()
        target = TargetAllocationV1(shares={"equity": 0.6, "cash": 0.4})
        service.save_target(ANNA, depot_id, 0, target)
        keys = _keys(store, depot_id)
        assert keys["HIN-A01:equity"] == "new"  # 15 % statt 60 %
        assert keys["HIN-A01:cash"] == "new"  # 85 % statt 40 %


class TestAcknowledged:
    def test_acknowledged_until_worse(self):
        market, store, service, depot_id = _setup()
        service.acknowledge(ANNA, depot_id, K01)
        run = store.latest_run(depot_id)
        assert run is not None
        assert K01 in service.acknowledged(depot_id, run)
        # SAP steigt auf 200: 3000 von 11 500 = 26 %, kritisch
        market.record_prices([Quote(SAP, FRIDAY, Decimal(200), "EUR")], [], at=T0)
        service.refresh_all("prices")
        run = store.latest_run(depot_id)
        assert run is not None
        assert K01 not in service.acknowledged(depot_id, run)

    def test_a_hint_that_returns_after_resolving_is_visible_again(self):
        _, store, service, depot_id = _setup()
        service.acknowledge(ANNA, depot_id, K01)
        # SAP auf 5 Stueck: 5 % - erledigt; dann wieder 15 Stueck: neu
        cash = [CashLine(Decimal(8500))]
        service.save(ANNA, depot_id, 1, [HoldingLine(SAP, Decimal(5))], cash)
        assert _keys(store, depot_id)[K01] == "resolved"
        service.save(ANNA, depot_id, 2, [HoldingLine(SAP, Decimal(15))], cash)
        run = store.latest_run(depot_id)
        assert run is not None
        assert _keys(store, depot_id)[K01] == "new"
        assert K01 not in service.acknowledged(depot_id, run)

    def test_the_export_holds_settings_and_acks(self):
        _, _, service, depot_id = _setup()
        service.save_hint_params(ANNA, depot_id, 0, HintParamsV1(a02_cash=0.5))
        service.save_target(ANNA, depot_id, 0, TargetAllocationV1(shares={"equity": 1.0}))
        service.acknowledge(ANNA, depot_id, K01)
        [(_, _, history)] = service.export(ANNA)
        assert [(v.version, v.values["a02_cash"]) for v in history.hint_params] == [(1, 0.5)]
        assert [dict(v.values) for v in history.targets] == [{"equity": 1.0}]
        assert [a.key for a in history.acks] == [K01]

    def test_not_in_an_archived_depot(self):
        _, _, service, depot_id = _setup()
        service.archive(ANNA, depot_id)
        with pytest.raises(ArchivedDepot):
            service.acknowledge(ANNA, depot_id, K01)

    def test_an_unknown_hint_is_not_found(self):
        _, _, service, depot_id = _setup()
        from va_portfolio.application.depots import DepotNotFound

        with pytest.raises(DepotNotFound):
            service.acknowledge(ANNA, depot_id, "HIN-K01:DE0000000000")


class TestOverRpc:
    def test_settings_and_conflict(self):
        _, _, service, depot_id = _setup()
        rpc = handlers(service)
        reply = rpc[DEPOTS_SETTINGS](DepotRefRequestV1(user_id=ANNA, depot_id=depot_id))
        assert isinstance(reply, DepotSettingsReplyV1)
        assert reply.settings is not None
        assert reply.settings.hint_params == HintParamsV1()
        request = HintParamsSaveRequestV1(
            user_id=ANNA, depot_id=depot_id, base_version=0, params=HintParamsV1(a02_cash=0.5)
        )
        saved = rpc[HINT_PARAMS_SAVE](request)
        assert isinstance(saved, DepotSettingsReplyV1)
        assert saved.settings is not None
        assert (saved.settings.hint_params_version, saved.settings.hint_params.a02_cash) == (1, 0.5)
        stale = rpc[HINT_PARAMS_SAVE](request)
        assert stale.error is not None
        assert (stale.error.code, stale.error.newest) == ("conflict", 1)

    def test_acknowledge_marks_the_hint(self):
        _, _, service, depot_id = _setup()
        reply = handlers(service)[HINT_ACK](
            HintAckRequestV1(user_id=ANNA, depot_id=depot_id, key=K01)
        )
        assert isinstance(reply, DepotHintsReplyV1)
        assert reply.hints is not None
        [k01] = [h for h in reply.hints.hints if h.key == K01]
        assert k01.acknowledged is True

    def test_a_foreign_depot_is_not_found(self):
        _, _, service, depot_id = _setup()
        reply = handlers(service)[DEPOTS_SETTINGS](
            DepotRefRequestV1(user_id=BEN, depot_id=depot_id)
        )
        assert reply.error is not None
        assert reply.error.code == "not_found"
