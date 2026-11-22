"""Anwendungsfall Depots (D3.1, DEP-01, 03, 06, 09; docs/architecture/depot/depots.md).

- Jede Anfrage nennt den Nutzer. Ein Depot eines anderen ist wie ein unbekanntes
  (``DepotNotFound``): Das web-api prueft den Besitz, portfolio prueft ihn noch einmal.
- Jede Aenderung schreibt Daten und ``portfolio.depot.changed`` in einer Transaktion (Outbox,
  im Speicher); danach leert ``flush`` die Outbox. Scheitert das, bleibt das Event liegen und geht
  mit der naechsten Aenderung oder dem Takt des Dienstes raus.
- Archivierte Depots sind schreibgeschuetzt, bis sie wiederhergestellt sind (DEP-06).
- Abdeckung (D3.3, WP-09): Aendert eine Speicherung, Archivierung oder Wiederherstellung die
  Menge der gehaltenen ISINs (aller Nutzer), geht ``portfolio.coverage.changed`` mit der ganzen
  Menge raus, ohne Nutzer und Mengen; dazu beim Start und taeglich (``announce_coverage``).
  Das Event entsteht in einer eigenen Transaktion nach der Aenderung. Geht es dazwischen
  verloren, holt es die naechste Meldung nach.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Protocol

from va_contracts import new_envelope
from va_contracts.events.v1 import (
    COVERAGE_CHANGED,
    DEPOT_CHANGED,
    CoverageChangedV1,
    DepotChange,
    DepotChangedV1,
)

from ..domain.depots import (
    CashLine,
    Depot,
    Diff,
    HoldingLine,
    Snapshot,
    check_holdings,
    check_name,
    diff,
    next_version,
)

if TYPE_CHECKING:
    from va_contracts import Envelope
    from va_contracts.portfolio import DepotKind, DepotState, SnapshotSource

log = logging.getLogger(__name__)

SOURCE = "va/portfolio"

EventFactory = Callable[[int], "Envelope[Any]"]  # Depot-ID -> Event
CoverageFactory = Callable[[list[str]], "Envelope[Any]"]  # ISINs -> Event


class DepotNotFound(LookupError):
    """Kein Depot dieses Nutzers (oder keine solche Version)."""


class ArchivedDepot(Exception):
    """Ein archiviertes Depot aendert sich erst nach dem Wiederherstellen."""


class DepotStore(Protocol):
    """Depots im Schema ``portfolio``; jedes Schreiben mit seinem Event in einer Transaktion."""

    def create_depot(
        self,
        *,
        owner_user_id: int,
        kind: DepotKind,
        name: str,
        description: str | None,
        at: datetime,
        changed: EventFactory,
    ) -> Depot: ...

    def depots(self, owner_user_id: int, *, include_archived: bool) -> list[Depot]: ...

    def depot(self, depot_id: int) -> Depot | None: ...

    def rename(
        self,
        depot_id: int,
        *,
        name: str,
        description: str | None,
        at: datetime,
        event: Envelope[Any],
    ) -> None: ...

    def set_status(
        self, depot_id: int, status: DepotState, *, at: datetime, event: Envelope[Any]
    ) -> None: ...

    def newest_version(self, depot_id: int) -> int:
        """0 ohne gespeicherten Depotstand."""
        ...

    def summary(self, depot_id: int) -> tuple[int, int]:
        """(neueste Version, Zahl ihrer Positionen), ohne die Positionen zu laden; (0, 0) leer."""
        ...

    def held_isins(self) -> list[str]:
        """D3.3: die ISINs der neuesten Depotstaende aktiver Depots, aller Nutzer, sortiert."""
        ...

    def add_coverage(self, make: CoverageFactory, *, unless: list[str] | None = None) -> bool:
        """D3.3: liest ``held_isins`` und legt ``make(isins)`` in die Outbox, ausser die Menge ist
        gleich ``unless``. Nacheinander (eine Sperre), damit das juengste Event die juengste Menge
        nennt; ``False``, wenn nichts in die Outbox kam."""
        ...

    def snapshot(self, depot_id: int, version: int | None = None) -> Snapshot | None:
        """Der Depotstand ``version``, ohne Angabe der neueste; ``None``, wenn es ihn nicht gibt."""
        ...

    def snapshots(self, depot_id: int) -> list[Snapshot]:
        """Alle Depotstaende, aelteste zuerst."""
        ...

    def save_snapshot(self, snapshot: Snapshot, *, event: Envelope[Any]) -> None:
        """Wirft ``VersionConflict``, wenn die Version schon vergeben ist (gleichzeitig gespeichert)."""
        ...


@dataclass(frozen=True)
class DepotSummary:
    depot: Depot
    version: int  # 0: noch kein Depotstand
    positions: int


@dataclass(frozen=True)
class HistoryEntry:
    version: int
    source: SnapshotSource
    created_at: datetime
    created_by: int | None
    positions: int
    diff: Diff


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _coverage(isins: list[str]) -> Envelope[Any]:
    return new_envelope(COVERAGE_CHANGED, CoverageChangedV1(isins=isins), source=SOURCE)


def _changed(depot_id: int, owner: int, change: DepotChange, version: int) -> Envelope[Any]:
    data = DepotChangedV1(depot_id=depot_id, owner_user_id=owner, change=change, version=version)
    return new_envelope(DEPOT_CHANGED, data, source=SOURCE)


class DepotService:
    def __init__(
        self,
        store: DepotStore,
        *,
        clock: Callable[[], datetime] = _utcnow,
        flush: Callable[[], object] | None = None,
    ) -> None:
        self._store = store
        self._clock = clock
        self._flush = flush

    # --- Depots -----------------------------------------------------------------------

    def list(self, user_id: int, *, include_archived: bool = False) -> list[DepotSummary]:
        return [
            self._summary(depot)
            for depot in self._store.depots(user_id, include_archived=include_archived)
        ]

    def create(
        self, user_id: int, kind: DepotKind, name: str, description: str | None
    ) -> DepotSummary:
        clean, text = check_name(name, description)
        depot = self._store.create_depot(
            owner_user_id=user_id,
            kind=kind,
            name=clean,
            description=text,
            at=self._clock(),
            changed=lambda depot_id: _changed(depot_id, user_id, "created", 0),
        )
        self._after_write()
        return DepotSummary(depot, 0, 0)

    def get(self, user_id: int, depot_id: int) -> DepotSummary:
        return self._summary(self._owned(user_id, depot_id))

    def update(
        self, user_id: int, depot_id: int, name: str, description: str | None
    ) -> DepotSummary:
        depot = self._writable(user_id, depot_id)
        clean, text = check_name(name, description)
        version = self._store.newest_version(depot.id)
        self._store.rename(
            depot.id,
            name=clean,
            description=text,
            at=self._clock(),
            event=_changed(depot.id, user_id, "renamed", version),
        )
        self._after_write()
        return self.get(user_id, depot_id)

    def archive(self, user_id: int, depot_id: int) -> DepotSummary:
        return self._set_status(user_id, depot_id, "archived")

    def restore(self, user_id: int, depot_id: int) -> DepotSummary:
        return self._set_status(user_id, depot_id, "active")

    def _set_status(self, user_id: int, depot_id: int, status: DepotState) -> DepotSummary:
        depot = self._owned(user_id, depot_id)
        if depot.status != status:
            change: DepotChange = "archived" if status == "archived" else "restored"
            before = self._held()
            self._store.set_status(
                depot.id,
                status,
                at=self._clock(),
                event=_changed(depot.id, user_id, change, self._store.newest_version(depot.id)),
            )
            self._coverage_since(before)
            self._after_write()
        return self.get(user_id, depot_id)

    # --- Depotstaende -------------------------------------------------------------------

    def holdings(self, user_id: int, depot_id: int, version: int | None = None) -> Snapshot:
        """Der Depotstand ``version`` (ohne Angabe der neueste); Version 0 ist leer."""
        depot = self._owned(user_id, depot_id)
        if version == 0:
            return Snapshot(depot.id, 0)
        found = self._store.snapshot(depot.id, version)
        if found is not None:
            return found
        if version is None:
            return Snapshot(depot.id, 0)
        msg = f"Depot {depot_id} hat keine Version {version}"
        raise DepotNotFound(msg)

    def save(
        self,
        user_id: int,
        depot_id: int,
        base_version: int,
        lines: Sequence[HoldingLine],
        cash: Sequence[CashLine],
        *,
        source: SnapshotSource = "manual",
    ) -> Snapshot:
        """Ein neuer Depotstand; wirft ``VersionConflict`` auf eine veraltete Basis."""
        depot = self._writable(user_id, depot_id)
        checked, cash_lines = check_holdings(depot.kind, lines, cash)
        version = next_version(newest=self._store.newest_version(depot.id), base=base_version)
        snapshot = Snapshot(
            depot_id=depot.id,
            version=version,
            source=source,
            created_at=self._clock(),
            created_by=user_id,
            lines=checked,
            cash=cash_lines,
        )
        before = self._held()
        self._store.save_snapshot(snapshot, event=_changed(depot.id, user_id, "holdings", version))
        self._coverage_since(before)
        self._after_write()
        return snapshot

    def history(self, user_id: int, depot_id: int) -> list[HistoryEntry]:
        """Alle Depotstaende, neueste zuerst, mit dem Unterschied zum vorherigen."""
        depot = self._owned(user_id, depot_id)
        entries: list[HistoryEntry] = []
        previous: tuple[HoldingLine, ...] = ()
        for snap in self._store.snapshots(depot.id):
            # Gespeicherte Staende haben immer Herkunft und Zeitpunkt (nur Version 0 nicht)
            assert snap.source is not None
            assert snap.created_at is not None
            entries.append(
                HistoryEntry(
                    version=snap.version,
                    source=snap.source,
                    created_at=snap.created_at,
                    created_by=snap.created_by,
                    positions=len(snap.lines),
                    diff=diff(previous, snap.lines),
                )
            )
            previous = snap.lines
        return entries[::-1]

    def export(self, user_id: int) -> list[tuple[DepotSummary, list[Snapshot]]]:
        """D3.2 (NUT-12): alle Depots des Nutzers, auch archivierte, mit allen Depotstaenden."""
        return [
            (self._summary(depot), self._store.snapshots(depot.id))
            for depot in self._store.depots(user_id, include_archived=True)
        ]

    # --- Abdeckung (D3.3) ---------------------------------------------------------------

    def announce_coverage(self) -> None:
        """Die ganze Abdeckung melden, auch unveraendert (Start und taeglich): So kommt eine
        verlorene Meldung an, und market-data loest eine ISIN, die einmal scheiterte, neu auf."""
        self._store.add_coverage(_coverage)
        self._after_write()

    def _held(self) -> list[str] | None:
        try:
            return self._store.held_isins()
        except Exception:
            log.warning("Abdeckung nicht lesbar - sie geht nach der Aenderung raus", exc_info=True)
            return None

    def _coverage_since(self, before: list[str] | None) -> None:
        """Meldet die Abdeckung, wenn sie sich seit ``before`` geaendert hat (``None``: immer).
        Ein Fehler hier kostet nicht die Aenderung selbst; die naechste Meldung holt ihn nach."""
        try:
            self._store.add_coverage(_coverage, unless=before)
        except Exception:
            log.warning(
                "Abdeckung nicht gemeldet - die naechste Meldung holt es nach", exc_info=True
            )

    # --- intern -----------------------------------------------------------------------

    def _owned(self, user_id: int, depot_id: int) -> Depot:
        depot = self._store.depot(depot_id)
        if depot is None or depot.owner_user_id != user_id:
            msg = f"Kein Depot {depot_id}"
            raise DepotNotFound(msg)
        return depot

    def _writable(self, user_id: int, depot_id: int) -> Depot:
        depot = self._owned(user_id, depot_id)
        if depot.status == "archived":
            msg = f"Depot {depot_id} ist archiviert"
            raise ArchivedDepot(msg)
        return depot

    def _summary(self, depot: Depot) -> DepotSummary:
        version, positions = self._store.summary(depot.id)
        return DepotSummary(depot, version, positions)

    def _after_write(self) -> None:
        if self._flush is None:
            return
        try:
            self._flush()
        except Exception:
            log.warning("Outbox nicht geleert - das Event geht spaeter raus", exc_info=True)
