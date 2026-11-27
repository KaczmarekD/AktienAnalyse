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
- Bewertung (D3.4, DEP-07, DEP-13): Mit ``market`` (Kopien der Marktdaten) tragen Liste und
  Depot ihren Wert aus dem neuesten Depotstand (``value_depot``). Sind die Kopien nicht lesbar,
  fehlt nur die Bewertung, nicht das Depot.
- Datei im eigenen Format (D3.5, DEP-05): ``preview_import`` gleicht ab und speichert nichts;
  ``import_file`` uebernimmt nur eine Datei ohne abgelehnte Zeilen (sonst entfielen deren
  Positionen still), als Depotstand mit Herkunft ``import`` und dem SHA-256 der Datei. Die
  Kasse bleibt, die Datei kennt keine. Fehlt die Einheit, gilt die bisherige der ISIN, sonst
  ``nominal`` fuer Anleihen (Stammdaten), sonst ``pieces``. ``export_file``: dasselbe Format.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Protocol

from va_contracts import new_envelope
from va_contracts.events.v1 import (
    ANALYSIS_COMPLETED,
    COVERAGE_CHANGED,
    DEPOT_CHANGED,
    AnalysisCompletedV1,
    CoverageChangedV1,
    DepotChange,
    DepotChangedV1,
)
from va_contracts.portfolio import DepotAnalysisV1, HintParamsV1

from ..domain.analysis import DepotAnalysis, analyze
from ..domain.depots import (
    CashLine,
    Depot,
    DepotError,
    Diff,
    HoldingLine,
    Snapshot,
    check_holdings,
    check_name,
    diff,
    next_version,
)
from ..domain.hints import Hint, HintInput, TrackedHint, evaluate, track
from ..domain.holdings_file import (
    FileLine,
    ImportEntry,
    RejectedRow,
    compare,
    parse_holdings,
    write_holdings,
)
from ..domain.valuation import DepotValue, value_depot
from .analysis import analysis_input, fund_isins, fund_sizes, securities

if TYPE_CHECKING:
    from va_contracts import Envelope
    from va_contracts.portfolio import DepotKind, DepotState, HoldingUnit, SnapshotSource

    from ..domain.hints import StoredRun
    from .market import MarketReader

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

    # --- D5.2: Laeufe der Analyse mit Hinweisen ---

    def active_depots(self) -> list[Depot]:
        """Alle aktiven Depots und Beobachtungslisten, aller Nutzer."""
        ...

    def latest_run(self, depot_id: int) -> StoredRun | None: ...

    def save_run(
        self,
        depot_id: int,
        *,
        version: int,
        trigger: str,
        fingerprint: str,
        result: dict[str, Any],
        hints: Sequence[TrackedHint],
        at: datetime,
        event: Callable[[int], Envelope[Any]],
    ) -> int:
        """Lauf, Hinweise und Event (mit der ID des Laufs) in einer Transaktion."""
        ...


@dataclass(frozen=True)
class DepotSummary:
    depot: Depot
    version: int  # 0: noch kein Depotstand
    positions: int
    valuation: DepotValue | None = None  # D3.4: ohne Marktdaten keine


@dataclass(frozen=True)
class ImportPreview:
    base_version: int
    entries: list[ImportEntry]
    rejected: tuple[RejectedRow, ...]
    pending: frozenset[str]  # ISINs ohne Stammdaten; leer ohne Marktdaten


@dataclass(frozen=True)
class HistoryEntry:
    version: int
    source: SnapshotSource
    created_at: datetime
    created_by: int | None
    positions: int
    diff: Diff


@dataclass(frozen=True)
class Evaluated:
    """D5.2: Analyse und Hinweise eines Depotstands, vor dem Speichern."""

    version: int
    analysis: DepotAnalysis
    hints: list[Hint]


def _fingerprint(version: int, result: dict[str, Any], hints: Sequence[Hint]) -> str:
    """Gleich, wenn sich weder Depotstand noch Analyse noch Hinweise geaendert haben."""
    payload = {"version": version, "analysis": result, "hints": [asdict(h) for h in hints]}
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def _analysis_completed(depot: Depot, run_id: int, tracked: Sequence[TrackedHint]) -> Envelope[Any]:
    """D5.2: nur IDs und Zahlen; erledigte Hinweise zaehlen nicht."""
    active = [t for t in tracked if t.status != "resolved"]

    def count(severity: str) -> int:
        return sum(t.hint.severity == severity for t in active)

    return new_envelope(
        ANALYSIS_COMPLETED,
        AnalysisCompletedV1(
            depot_id=depot.id,
            owner_user_id=depot.owner_user_id,
            analysis_run_id=run_id,
            critical=count("critical"),
            warning=count("warning"),
            info=count("info"),
            new=sum(t.status == "new" for t in active),
        ),
        source=SOURCE,
    )


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
        market: MarketReader | None = None,
    ) -> None:
        self._store = store
        self._clock = clock
        self._flush = flush
        self._market = market

    # --- Depots -----------------------------------------------------------------------

    def list(self, user_id: int, *, include_archived: bool = False) -> list[DepotSummary]:
        return self._summaries(self._store.depots(user_id, include_archived=include_archived))

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
        return self._summaries([self._owned(user_id, depot_id)])[0]

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
        source_ref: str | None = None,
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
            source_ref=source_ref,
        )
        before = self._held()
        self._store.save_snapshot(snapshot, event=_changed(depot.id, user_id, "holdings", version))
        self._coverage_since(before)
        # D5.2: der neue Depotstand bekommt gleich seine Analyse; ein Fehler kostet nur sie
        try:
            self._refresh(depot, "holdings")
        except Exception:
            log.warning("Analyse von Depot %s nicht gespeichert", depot.id, exc_info=True)
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
        return [  # ohne Bewertung: der Export enthaelt nur, was der Nutzer erfasst hat
            (self._summary(depot), self._store.snapshots(depot.id))
            for depot in self._store.depots(user_id, include_archived=True)
        ]

    # --- Datei im eigenen Format (D3.5) ------------------------------------------------

    def preview_import(self, user_id: int, depot_id: int, content: bytes) -> ImportPreview:
        """Abgleich der Datei mit dem aktuellen Depotstand; speichert nichts."""
        depot = self._writable(user_id, depot_id)
        parsed = parse_holdings(content, depot.kind)
        current = self._store.snapshot(depot.id) or Snapshot(depot.id, 0)
        lines, securities = self._with_units(parsed.lines, current.lines)
        pending = (
            frozenset()
            if securities is None
            else frozenset(line.isin for line in lines if line.isin not in securities)
        )
        return ImportPreview(
            current.version, compare(current.lines, lines), parsed.rejected, pending
        )

    def import_file(
        self, user_id: int, depot_id: int, base_version: int, content: bytes
    ) -> Snapshot:
        """Die Datei als neuer Depotstand; ``DepotError``, wenn eine Zeile nicht erkannt ist."""
        depot = self._writable(user_id, depot_id)
        parsed = parse_holdings(content, depot.kind)
        if parsed.rejected:
            first = parsed.rejected[0]
            msg = (
                f"{len(parsed.rejected)} Zeilen der Datei sind nicht erkannt"
                f" (Zeile {first.line}: {first.reason})"
            )
            raise DepotError(msg)
        current = self._store.snapshot(depot.id) or Snapshot(depot.id, 0)
        lines, _ = self._with_units(parsed.lines, current.lines)
        return self.save(
            user_id,
            depot_id,
            base_version,
            lines,
            current.cash,
            source="import",
            source_ref=hashlib.sha256(content).hexdigest(),
        )

    def export_file(
        self, user_id: int, depot_id: int, version: int | None = None
    ) -> tuple[str, bytes]:
        """Die Positionen eines Depotstands im eigenen Format; der Name enthaelt nur Zahlen."""
        snapshot = self.holdings(user_id, depot_id, version)
        return f"depot-{depot_id}-v{snapshot.version}.csv", write_holdings(snapshot.lines)

    def _with_units(
        self, lines: Sequence[FileLine], current: Sequence[HoldingLine]
    ) -> tuple[list[HoldingLine], set[str] | None]:
        """Die Einheit fuer Zeilen ohne: bisherige der ISIN, sonst nach den Stammdaten."""
        known: dict[str, HoldingUnit] = {line.isin: line.unit for line in current}
        securities: dict[str, str] | None = None
        if self._market is not None:
            try:
                copies = self._market.market({line.isin for line in lines}).securities
                securities = {isin: info.asset_class for isin, info in copies.items()}
            except Exception:
                log.warning("Stammdaten nicht lesbar - Einheit ohne sie", exc_info=True)
        bonds = {isin for isin, kind in (securities or {}).items() if kind == "bond"}

        def unit(line: FileLine) -> HoldingUnit:
            if line.unit is not None:
                return line.unit
            fallback: HoldingUnit = "nominal" if line.isin in bonds else "pieces"
            return known.get(line.isin) or fallback

        resolved = [
            HoldingLine(line.isin, line.quantity, unit(line), line.cost_basis_eur, line.note)
            for line in lines
        ]
        return resolved, None if securities is None else set(securities)

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

    def analysis(self, user_id: int, depot_id: int) -> DepotAnalysis | None:
        """D4.4: Analyse des neuesten Depotstands; ``None`` ohne lesbare Marktdaten."""
        evaluated = self._evaluate(self._owned(user_id, depot_id))
        return None if evaluated is None else evaluated.analysis

    def hints(self, user_id: int, depot_id: int) -> StoredRun | None:
        """D5.2: der juengste Lauf mit Hinweisen; ohne Lauf wird zuerst einer gerechnet."""
        depot = self._owned(user_id, depot_id)
        if self._store.latest_run(depot.id) is None:
            self._refresh(depot, "request")
        return self._store.latest_run(depot.id)

    def refresh_all(self, trigger: str) -> int:
        """D5.2: alle aktiven Depots neu rechnen (neue Kurse, Scores, Stammdaten); wirft nicht."""
        runs = 0
        try:
            depots = self._store.active_depots()
        except Exception:
            log.warning("Depots nicht lesbar - keine neue Analyse", exc_info=True)
            return 0
        for depot in depots:
            try:
                runs += self._refresh(depot, trigger) is not None
            except Exception:
                log.warning("Analyse von Depot %s nicht gespeichert", depot.id, exc_info=True)
        if runs:
            self._after_write()
        return runs

    def _refresh(self, depot: Depot, trigger: str) -> int | None:
        """Ein neuer Lauf, wenn sich Analyse oder Hinweise geaendert haben; sonst ``None``."""
        evaluated = self._evaluate(depot)
        if evaluated is None:
            return None
        result = DepotAnalysisV1.model_validate(asdict(evaluated.analysis)).model_dump(mode="json")
        fingerprint = _fingerprint(evaluated.version, result, evaluated.hints)
        previous = self._store.latest_run(depot.id)
        if previous is not None and previous.fingerprint == fingerprint:
            return None
        tracked = track(previous.hints if previous else [], evaluated.hints)
        return self._store.save_run(
            depot.id,
            version=evaluated.version,
            trigger=trigger,
            fingerprint=fingerprint,
            result=result,
            hints=tracked,
            at=self._clock(),
            event=lambda run_id: _analysis_completed(depot, run_id, tracked),
        )

    def _evaluate(self, depot: Depot) -> Evaluated | None:
        """Analyse und Hinweise des neuesten Depotstands; ``None`` ohne lesbare Marktdaten."""
        if self._market is None:
            return None
        snapshot = self._store.snapshot(depot.id) or Snapshot(depot.id, 0)
        isins = {line.isin for line in snapshot.lines}
        try:
            market = self._market.market(isins)
            found = securities(self._market.security_payloads(isins))
            inside = fund_isins(found) - isins
            scores = {**market.scores, **(self._market.market(inside).scores if inside else {})}
            previous = self._market.previous_scores(isins)
        except Exception:
            log.warning("Marktdaten nicht lesbar - Depot ohne Analyse", exc_info=True)
            return None
        value = value_depot(depot.kind, snapshot.lines, snapshot.cash, market)
        data = analysis_input(value, found, scores)
        analysis = analyze(data)
        source = HintInput(
            data,
            analysis,
            self._clock().date(),
            leis={i: s.lei for i, s in found.items() if s.lei},
            fund_sizes=fund_sizes(found, market.fx),
            previous_scores=previous,
        )
        return Evaluated(snapshot.version, analysis, evaluate(source, HintParamsV1()))

    def _summary(self, depot: Depot) -> DepotSummary:
        version, positions = self._store.summary(depot.id)
        return DepotSummary(depot, version, positions)

    def _summaries(self, depots: Sequence[Depot]) -> list[DepotSummary]:
        """Mit Bewertung, wenn es Marktdaten gibt: je Depot der neueste Depotstand, die Kopien
        der Marktdaten einmal fuer alle zusammen."""
        if self._market is None:
            return [self._summary(depot) for depot in depots]
        snapshots = {d.id: self._store.snapshot(d.id) or Snapshot(d.id, 0) for d in depots}
        try:
            market = self._market.market(
                {line.isin for snap in snapshots.values() for line in snap.lines}
            )
        except Exception:
            log.warning("Marktdaten nicht lesbar - Depots ohne Bewertung", exc_info=True)
            market = None
        return [
            DepotSummary(
                depot,
                snapshots[depot.id].version,
                len(snapshots[depot.id].lines),
                None
                if market is None
                else value_depot(
                    depot.kind, snapshots[depot.id].lines, snapshots[depot.id].cash, market
                ),
            )
            for depot in depots
        ]

    def _after_write(self) -> None:
        if self._flush is None:
            return
        try:
            self._flush()
        except Exception:
            log.warning("Outbox nicht geleert - das Event geht spaeter raus", exc_info=True)
