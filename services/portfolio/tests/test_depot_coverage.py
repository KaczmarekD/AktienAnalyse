"""Die Abdeckung aus den Depots (D3.3, WP-09, WP-13; docs/architecture/depot/wertpapiere.md).

portfolio meldet market-data die Menge aller ISINs in den neuesten Depotstaenden aktiver Depots
und Beobachtungslisten, aller Nutzer zusammen (``portfolio.coverage.changed``):
- nach jeder Aenderung, die die Menge aendert (Speichern, Archivieren, Wiederherstellen),
- nicht, wenn sie gleich bleibt (andere Menge, Notiz, Umbenennen),
- beim Start und taeglich immer (``announce_coverage``): falls ein Event verloren ging oder
  market-data eine ISIN nicht aufloesen konnte.
Ohne Nutzer, Depots oder Mengen.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from va_contracts.events.v1 import COVERAGE_CHANGED
from va_portfolio.adapters.memory import MemoryDepotStore
from va_portfolio.application.depots import DepotService
from va_portfolio.domain.depots import HoldingLine
from va_portfolio.entrypoints.service import _keep_flushing

ANNA, BEN = 1, 2
SAP = "DE0007164600"
APPLE = "US0378331005"
WORLD = "IE00B4L5Y983"


@pytest.fixture
def store() -> MemoryDepotStore:
    return MemoryDepotStore()


@pytest.fixture
def service(store) -> DepotService:
    return DepotService(store)


def _coverage(store: MemoryDepotStore) -> list[list[str]]:
    return [e.data.isins for e in store.events if e.type == COVERAGE_CHANGED.type]


def _line(isin: str, quantity: str | None = "1", **kwargs) -> HoldingLine:
    return HoldingLine(isin, Decimal(quantity) if quantity else None, **kwargs)


def test_a_new_isin_changes_the_coverage(service, store):
    depot = service.create(ANNA, "depot", "DKB", None).depot
    assert _coverage(store) == []  # ein leeres Depot aendert nichts
    service.save(ANNA, depot.id, 0, [_line(SAP)], [])
    service.save(ANNA, depot.id, 1, [_line(SAP), _line(APPLE)], [])
    assert _coverage(store) == [[SAP], sorted({SAP, APPLE})]


def test_the_same_set_sends_nothing(service, store):
    depot = service.create(ANNA, "depot", "DKB", None).depot
    service.save(ANNA, depot.id, 0, [_line(SAP, "1")], [])
    service.save(ANNA, depot.id, 1, [_line(SAP, "5", note="mehr")], [])
    service.update(ANNA, depot.id, "Rente", None)
    assert _coverage(store) == [[SAP]]


def test_all_users_and_watchlists_together(service, store):
    annas = service.create(ANNA, "depot", "DKB", None).depot
    bens = service.create(BEN, "watchlist", "Ideen", None).depot
    service.save(ANNA, annas.id, 0, [_line(SAP)], [])
    service.save(BEN, bens.id, 0, [_line(WORLD, None), _line(SAP, None)], [])
    assert _coverage(store) == [[SAP], sorted({SAP, WORLD})]  # sortiert, je ISIN einmal


def test_archiving_removes_and_restoring_returns(service, store):
    depot = service.create(ANNA, "depot", "DKB", None).depot
    service.save(ANNA, depot.id, 0, [_line(APPLE)], [])
    service.archive(ANNA, depot.id)
    service.restore(ANNA, depot.id)
    assert _coverage(store) == [[APPLE], [], [APPLE]]


def test_an_isin_in_two_depots_stays(service, store):
    first = service.create(ANNA, "depot", "DKB", None).depot
    second = service.create(BEN, "depot", "Comdirect", None).depot
    service.save(ANNA, first.id, 0, [_line(SAP)], [])
    service.save(BEN, second.id, 0, [_line(SAP)], [])
    service.save(ANNA, first.id, 1, [], [])
    assert _coverage(store) == [[SAP]]  # Ben haelt SAP weiter


def test_only_the_newest_snapshot_counts(service, store):
    depot = service.create(ANNA, "depot", "DKB", None).depot
    service.save(ANNA, depot.id, 0, [_line(SAP)], [])
    service.save(ANNA, depot.id, 1, [_line(APPLE)], [])
    assert _coverage(store) == [[SAP], [APPLE]]


def test_at_start_the_whole_set_once(service, store):
    depot = service.create(ANNA, "depot", "DKB", None).depot
    service.save(ANNA, depot.id, 0, [_line(SAP)], [])
    service.announce_coverage()
    assert _coverage(store) == [[SAP], [SAP]]


def test_the_event_names_no_user_and_no_quantity(service, store):
    depot = service.create(ANNA, "depot", "DKB", None).depot
    service.save(ANNA, depot.id, 0, [_line(SAP, "12.5")], [])
    [event] = [e for e in store.events if e.type == COVERAGE_CHANGED.type]
    payload = event.data.model_dump_json()
    assert "12.5" not in payload
    assert set(event.data.model_dump()) == {"isins"}


def test_a_failed_change_is_not_lost_but_the_next_announcement_has_it(service, store):
    depot = service.create(ANNA, "depot", "DKB", None).depot
    store.add_coverage = _broken  # type: ignore[method-assign]
    service.save(ANNA, depot.id, 0, [_line(SAP)], [])  # die Aenderung selbst gilt
    assert service.holdings(ANNA, depot.id).version == 1
    del store.add_coverage
    service.announce_coverage()
    assert _coverage(store) == [[SAP]]


def _broken(*args, **kwargs) -> bool:
    msg = "Outbox weg"
    raise RuntimeError(msg)


def test_the_service_announces_once_a_day():
    calls: list[str] = []
    ticks = iter([0.0, 10.0, 86_400.0, 86_401.0, 90_000.0])
    rounds = iter([False, False, False, True])

    def flush() -> int:
        calls.append("flush")
        return 0

    _keep_flushing(
        flush,
        0.0,
        lambda: next(rounds),
        announce=lambda: calls.append("announce"),
        announce_every=86_400.0,
        timer=lambda: next(ticks),
    )
    assert calls == ["flush", "announce", "flush", "flush"]


def test_a_failed_announcement_keeps_the_cycle():
    calls: list[str] = []
    ticks = iter([0.0, 100.0, 100.0, 200.0, 200.0])
    rounds = iter([False, False, True])

    def announce() -> None:
        calls.append("announce")
        raise RuntimeError("NATS weg")

    _keep_flushing(
        lambda: calls.append("flush") or 0,
        0.0,
        lambda: next(rounds),
        announce=announce,
        announce_every=50.0,
        timer=lambda: next(ticks),
    )
    assert calls == ["announce", "flush", "announce", "flush"]
