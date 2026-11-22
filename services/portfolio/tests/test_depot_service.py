"""Anwendungsfall Depots (D3.1, DEP-01, 03, 06; docs/architecture/depot/depots.md).

- Jede Anfrage nennt den Nutzer; ein Depot eines anderen ist wie ein unbekanntes (``not_found``).
- Ein neues Depot hat den leeren Stand Version 0; jede Speicherung die naechste Version, nur auf
  die neueste als Basis (sonst Konflikt mit der neuesten).
- Archivierte Depots sind schreibgeschuetzt, bis sie wiederhergestellt sind.
- Jede Aenderung schickt ``portfolio.depot.changed`` (nur IDs, Art und Version) ueber die Outbox,
  in derselben Transaktion wie die Daten; danach wird die Outbox geleert.

Der Speicher ist ``MemoryDepotStore`` (verhaelt sich wie der in Postgres).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from va_contracts.events.v1 import DEPOT_CHANGED
from va_portfolio.adapters.memory import MemoryDepotStore
from va_portfolio.application.depots import (
    ArchivedDepot,
    DepotNotFound,
    DepotService,
)
from va_portfolio.domain.depots import (
    CashLine,
    DepotError,
    HoldingLine,
    VersionConflict,
)

ANNA, BEN = 1, 2
SAP = "DE0007164600"
APPLE = "US0378331005"
T0 = datetime(2026, 11, 22, 10, 0, tzinfo=UTC)


class Clock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> datetime:
        self.now += timedelta(minutes=1)
        return self.now


@dataclass
class World:
    store: MemoryDepotStore = field(default_factory=MemoryDepotStore)
    flushed: int = 0

    def service(self) -> DepotService:
        def flush() -> None:
            self.flushed += 1

        return DepotService(self.store, clock=Clock(), flush=flush)


@pytest.fixture
def world() -> World:
    return World()


def _lines(*pairs: tuple[str, str]) -> list[HoldingLine]:
    return [HoldingLine(isin, Decimal(q)) for isin, q in pairs]


class TestDepots:
    def test_create_and_list_own_depots(self, world):
        service = world.service()
        created = service.create(ANNA, "depot", "  DKB  ", None)
        service.create(BEN, "depot", "Bens Depot", None)
        assert (created.depot.name, created.version, created.positions) == ("DKB", 0, 0)
        assert [s.depot.name for s in service.list(ANNA)] == ["DKB"]
        [event] = world.store.events[:1]
        assert event.type == DEPOT_CHANGED.type
        assert (event.data.depot_id, event.data.owner_user_id, event.data.change) == (
            created.depot.id,
            ANNA,
            "created",
        )
        assert world.flushed == 2

    def test_a_foreign_depot_is_not_found(self, world):
        service = world.service()
        bens = service.create(BEN, "depot", "Bens Depot", None).depot.id
        for call in (
            lambda: service.get(ANNA, bens),
            lambda: service.update(ANNA, bens, "Meins", None),
            lambda: service.archive(ANNA, bens),
            lambda: service.holdings(ANNA, bens),
            lambda: service.save(ANNA, bens, 0, _lines((SAP, "1")), []),
            lambda: service.history(ANNA, bens),
        ):
            with pytest.raises(DepotNotFound):
                call()
        with pytest.raises(DepotNotFound):
            service.get(ANNA, 999)

    def test_rename(self, world):
        service = world.service()
        depot = service.create(ANNA, "depot", "DKB", None).depot
        renamed = service.update(ANNA, depot.id, "Altersvorsorge", "  Sparplan ")
        assert (renamed.depot.name, renamed.depot.description) == ("Altersvorsorge", "Sparplan")
        assert world.store.events[-1].data.change == "renamed"

    def test_an_invalid_name(self, world):
        with pytest.raises(DepotError):
            world.service().create(ANNA, "depot", "   ", None)
        assert world.store.events == []

    def test_archive_and_restore(self, world):
        service = world.service()
        depot = service.create(ANNA, "depot", "Alt", None).depot
        assert service.archive(ANNA, depot.id).depot.status == "archived"
        assert service.list(ANNA) == []
        assert [s.depot.id for s in service.list(ANNA, include_archived=True)] == [depot.id]
        with pytest.raises(ArchivedDepot):
            service.save(ANNA, depot.id, 0, _lines((SAP, "1")), [])
        with pytest.raises(ArchivedDepot):
            service.update(ANNA, depot.id, "Neu", None)
        assert service.restore(ANNA, depot.id).depot.status == "active"
        assert [e.data.change for e in world.store.events] == ["created", "archived", "restored"]

    def test_archiving_twice_changes_nothing(self, world):
        service = world.service()
        depot = service.create(ANNA, "depot", "Alt", None).depot
        service.archive(ANNA, depot.id)
        service.archive(ANNA, depot.id)
        assert [e.data.change for e in world.store.events] == ["created", "archived"]


class TestHoldings:
    def test_a_new_depot_has_the_empty_version_0(self, world):
        service = world.service()
        depot = service.create(ANNA, "depot", "DKB", None).depot
        holdings = service.holdings(ANNA, depot.id)
        assert (holdings.version, holdings.lines, holdings.cash) == (0, (), ())

    def test_each_save_is_the_next_version(self, world):
        service = world.service()
        depot = service.create(ANNA, "depot", "DKB", None).depot
        first = service.save(ANNA, depot.id, 0, _lines((SAP, "10")), [CashLine(Decimal("100"))])
        second = service.save(ANNA, depot.id, 1, _lines((SAP, "12"), (APPLE, "3")), [])
        assert (first.version, second.version) == (1, 2)
        assert (second.source, second.created_by) == ("manual", ANNA)
        assert service.holdings(ANNA, depot.id).version == 2
        assert service.holdings(ANNA, depot.id, version=1).lines == first.lines
        summary = service.get(ANNA, depot.id)
        assert (summary.version, summary.positions) == (2, 2)
        holdings_events = [e.data for e in world.store.events if e.data.change == "holdings"]
        assert [e.version for e in holdings_events] == [1, 2]

    def test_an_unknown_version_is_not_found(self, world):
        service = world.service()
        depot = service.create(ANNA, "depot", "DKB", None).depot
        with pytest.raises(DepotNotFound):
            service.holdings(ANNA, depot.id, version=5)

    def test_an_old_base_is_a_conflict(self, world):
        service = world.service()
        depot = service.create(ANNA, "depot", "DKB", None).depot
        service.save(ANNA, depot.id, 0, _lines((SAP, "10")), [])
        with pytest.raises(VersionConflict) as caught:
            service.save(ANNA, depot.id, 0, _lines((SAP, "11")), [])
        assert caught.value.newest == 1

    def test_a_simultaneous_save_is_a_conflict(self, world):
        """Zwei Speicherungen auf dieselbe Basis: Die Datenbank laesst nur eine zu."""
        service = world.service()
        depot = service.create(ANNA, "depot", "DKB", None).depot
        world.store.race = True
        with pytest.raises(VersionConflict) as caught:
            service.save(ANNA, depot.id, 0, _lines((SAP, "10")), [])
        assert caught.value.newest == 1

    def test_invalid_lines_save_nothing(self, world):
        service = world.service()
        depot = service.create(ANNA, "depot", "DKB", None).depot
        with pytest.raises(DepotError):
            service.save(ANNA, depot.id, 0, _lines((SAP, "1"), (SAP, "2")), [])
        assert service.holdings(ANNA, depot.id).version == 0

    def test_an_import_is_marked(self, world):
        service = world.service()
        depot = service.create(ANNA, "depot", "DKB", None).depot
        saved = service.save(ANNA, depot.id, 0, _lines((SAP, "1")), [], source="import")
        assert saved.source == "import"

    def test_a_watchlist(self, world):
        service = world.service()
        depot = service.create(ANNA, "watchlist", "Ideen", None).depot
        saved = service.save(ANNA, depot.id, 0, [HoldingLine(SAP, None)], [])
        assert saved.lines[0].quantity is None

    def test_a_failing_flush_does_not_fail_the_change(self, world):
        def broken() -> None:
            raise ConnectionError("NATS weg")

        service = DepotService(world.store, clock=Clock(), flush=broken)
        depot = service.create(ANNA, "depot", "DKB", None).depot
        assert service.save(ANNA, depot.id, 0, _lines((SAP, "1")), []).version == 1


class TestHistory:
    def test_newest_first_with_changes(self, world):
        service = world.service()
        depot = service.create(ANNA, "depot", "DKB", None).depot
        service.save(ANNA, depot.id, 0, _lines((SAP, "10")), [])
        service.save(ANNA, depot.id, 1, _lines((SAP, "12"), (APPLE, "3")), [])
        service.save(ANNA, depot.id, 2, _lines((APPLE, "3")), [])
        history = service.history(ANNA, depot.id)
        assert [entry.version for entry in history] == [3, 2, 1]
        assert [(e.diff.added, e.diff.changed, e.diff.removed) for e in history] == [
            (0, 0, 1),
            (1, 1, 0),
            (1, 0, 0),
        ]
        assert [e.positions for e in history] == [1, 2, 1]

    def test_without_saves_empty(self, world):
        service = world.service()
        depot = service.create(ANNA, "depot", "DKB", None).depot
        assert service.history(ANNA, depot.id) == []
