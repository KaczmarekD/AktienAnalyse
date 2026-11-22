"""Depots im Speicher (Port ``DepotStore``), fuer Tests und den Betrieb ohne Datenbank.

Verhaelt sich wie ``PostgresDepotStore``: Daten und Event einer Aenderung gemeinsam, eine
vergebene Version ergibt ``VersionConflict``. Die Events sammelt ``events`` (statt der Outbox).
"""

from __future__ import annotations

import threading
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from ..domain.depots import Depot, Snapshot, VersionConflict

if TYPE_CHECKING:
    from datetime import datetime

    from va_contracts import Envelope
    from va_contracts.portfolio import DepotKind, DepotState

    from ..application.depots import CoverageFactory, EventFactory


class MemoryDepotStore:
    def __init__(self) -> None:
        self.depots_by_id: dict[int, Depot] = {}
        self.snaps: dict[int, list[Snapshot]] = {}
        self.events: list[Envelope[Any]] = []
        # Simuliert eine gleichzeitige Speicherung: Die Version ist schon vergeben
        self.race = False
        self._lock = threading.Lock()

    def create_depot(
        self,
        *,
        owner_user_id: int,
        kind: DepotKind,
        name: str,
        description: str | None,
        at: datetime,
        changed: EventFactory,
    ) -> Depot:
        with self._lock:
            depot = Depot(
                len(self.depots_by_id) + 1, owner_user_id, kind, name, description, "active", at
            )
            self.depots_by_id[depot.id] = depot
            self.events.append(changed(depot.id))
            return depot

    def depots(self, owner_user_id: int, *, include_archived: bool) -> list[Depot]:
        return [
            d
            for d in self.depots_by_id.values()
            if d.owner_user_id == owner_user_id and (include_archived or d.status == "active")
        ]

    def depot(self, depot_id: int) -> Depot | None:
        return self.depots_by_id.get(depot_id)

    def rename(
        self,
        depot_id: int,
        *,
        name: str,
        description: str | None,
        at: datetime,
        event: Envelope[Any],
    ) -> None:
        del at  # der Speicher fuehrt keinen Verlauf der Namen
        with self._lock:
            self.depots_by_id[depot_id] = replace(
                self.depots_by_id[depot_id], name=name, description=description
            )
            self.events.append(event)

    def set_status(
        self, depot_id: int, status: DepotState, *, at: datetime, event: Envelope[Any]
    ) -> None:
        del at
        with self._lock:
            self.depots_by_id[depot_id] = replace(self.depots_by_id[depot_id], status=status)
            self.events.append(event)

    def newest_version(self, depot_id: int) -> int:
        snaps = self.snaps.get(depot_id, [])
        return snaps[-1].version if snaps else 0

    def held_isins(self) -> list[str]:
        isins = {
            line.isin
            for depot_id, snaps in self.snaps.items()
            if snaps and self.depots_by_id[depot_id].status == "active"
            for line in snaps[-1].lines
        }
        return sorted(isins)

    def add_coverage(self, make: CoverageFactory, *, unless: list[str] | None = None) -> bool:
        with self._lock:
            isins = self.held_isins()
            if unless is not None and isins == unless:
                return False
            self.events.append(make(isins))
            return True

    def summary(self, depot_id: int) -> tuple[int, int]:
        snaps = self.snaps.get(depot_id, [])
        return (snaps[-1].version, len(snaps[-1].lines)) if snaps else (0, 0)

    def snapshot(self, depot_id: int, version: int | None = None) -> Snapshot | None:
        snaps = self.snaps.get(depot_id, [])
        if version is None:
            return snaps[-1] if snaps else None
        return next((s for s in snaps if s.version == version), None)

    def snapshots(self, depot_id: int) -> list[Snapshot]:
        return list(self.snaps.get(depot_id, []))

    def save_snapshot(self, snapshot: Snapshot, *, event: Envelope[Any]) -> None:
        with self._lock:
            snaps = self.snaps.setdefault(snapshot.depot_id, [])
            if self.race:  # jemand anderes war schneller
                snaps.append(replace(snapshot, created_by=None))
            if any(s.version == snapshot.version for s in snaps):
                raise VersionConflict(snaps[-1].version)
            snaps.append(snapshot)
            self.events.append(event)
