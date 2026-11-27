"""Depots und Marktdaten im Speicher (Ports ``DepotStore``, ``MarketStore``), fuer Tests.

Verhaelt sich wie ``PostgresDepotStore``: Daten und Event einer Aenderung gemeinsam, eine
vergebene Version ergibt ``VersionConflict``. Die Events sammelt ``events`` (statt der Outbox).
"""

from __future__ import annotations

import threading
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from ..domain.depots import Depot, Snapshot, VersionConflict
from ..domain.hints import (
    Ack,
    SettingsHistory,
    SettingsVersion,
    StoredRun,
    StoredSettings,
    TrackedHint,
)
from ..domain.valuation import Market, Quote, Score, SecurityInfo

if TYPE_CHECKING:
    from collections.abc import Callable, Collection, Sequence
    from datetime import date, datetime
    from decimal import Decimal

    from va_contracts import Envelope
    from va_contracts.portfolio import DepotKind, DepotState

    from ..application.depots import CoverageFactory, EventFactory
    from ..application.market import FxRate, SecurityCopy


class MemoryDepotStore:
    def __init__(self) -> None:
        self.depots_by_id: dict[int, Depot] = {}
        self.snaps: dict[int, list[Snapshot]] = {}
        self.events: list[Envelope[Any]] = []
        # Simuliert eine gleichzeitige Speicherung: Die Version ist schon vergeben
        self.race = False
        self._lock = threading.Lock()
        self.runs: list[StoredRun] = []  # D5.2
        self.results: dict[int, dict[str, Any]] = {}
        # D5.3: je Depot die Versionen der Schwellen und Ziele, die Kenntnisnahmen
        self.params: dict[int, list[SettingsVersion]] = {}
        self.targets: dict[int, list[SettingsVersion]] = {}
        self.ack_rows: list[tuple[int, Ack]] = []

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

    # --- D5.2: Laeufe der Analyse mit Hinweisen ---

    def active_depots(self) -> list[Depot]:
        return [d for d in self.depots_by_id.values() if d.status == "active"]

    def latest_run(self, depot_id: int) -> StoredRun | None:
        runs = [r for r in self.runs if r.depot_id == depot_id]
        return runs[-1] if runs else None

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
        del trigger
        with self._lock:
            run = StoredRun(len(self.runs) + 1, depot_id, version, fingerprint, at, list(hints))
            self.runs.append(run)
            self.results[run.id] = result
            self.events.append(event(run.id))
            return run.id

    # --- D5.3: Einstellungen und Kenntnisnahme ---

    def settings(self, depot_id: int) -> StoredSettings:
        params = self.params.get(depot_id, [])
        targets = self.targets.get(depot_id, [])
        return StoredSettings(
            hint_params=params[-1].values if params else {},
            hint_params_version=len(params),
            target=targets[-1].values if targets else {},  # type: ignore[arg-type]
            target_version=len(targets),
        )

    @staticmethod
    def _append(
        versions: list[SettingsVersion], version: int, values: dict[str, Any], at: datetime
    ) -> None:
        if version != len(versions) + 1:
            raise VersionConflict(len(versions))
        versions.append(SettingsVersion(version, values, at))

    def save_hint_params(
        self, depot_id: int, *, version: int, params: dict[str, Any], by: int, at: datetime
    ) -> None:
        del by
        with self._lock:
            self._append(self.params.setdefault(depot_id, []), version, params, at)

    def save_target(
        self, depot_id: int, *, version: int, shares: dict[str, float], by: int, at: datetime
    ) -> None:
        del by
        with self._lock:
            self._append(self.targets.setdefault(depot_id, []), version, dict(shares), at)

    def acks(self, depot_id: int) -> dict[str, Ack]:
        return {ack.key: ack for d, ack in self.ack_rows if d == depot_id}

    def save_ack(
        self,
        depot_id: int,
        *,
        key: str,
        user_id: int,
        run_id: int,
        measured: float | None,
        severity: str,
        at: datetime,
    ) -> None:
        del user_id
        ack = Ack(key, measured, severity, at, run_id)  # type: ignore[arg-type]
        self.ack_rows.append((depot_id, ack))

    def since_new(self, depot_id: int) -> dict[str, int]:
        since: dict[str, int] = {}
        for run in self.runs:
            if run.depot_id != depot_id:
                continue
            for tracked in run.hints:
                if tracked.status == "new":
                    since[tracked.hint.key] = max(since.get(tracked.hint.key, 0), run.id)
        return since

    def settings_history(self, depot_id: int) -> SettingsHistory:
        return SettingsHistory(
            hint_params=list(self.params.get(depot_id, [])),
            targets=list(self.targets.get(depot_id, [])),
            acks=[ack for d, ack in self.ack_rows if d == depot_id],
        )


class MemoryMarketStore:
    """Kopien der Marktdaten (D3.4): je ISIN bzw. Waehrung gilt das Juengste."""

    def __init__(self) -> None:
        self.securities: dict[str, tuple[date, SecurityInfo]] = {}
        self.quotes: dict[str, Quote] = {}
        self.fx: dict[str, tuple[date, Decimal]] = {}
        self.payloads: dict[str, dict[str, Any]] = {}
        self.scores: dict[str, Score] = {}
        self.score_history: list[Score] = []  # D5.2

    def record_securities(
        self, copies: Sequence[SecurityCopy], *, as_of: date, at: datetime
    ) -> None:
        del at
        for copy in copies:
            known = self.securities.get(copy.info.isin)
            if known is None or known[0] <= as_of:
                self.securities[copy.info.isin] = (as_of, copy.info)
                self.payloads[copy.info.isin] = copy.payload

    def record_prices(
        self, quotes: Sequence[Quote], rates: Sequence[FxRate], *, at: datetime
    ) -> None:
        del at
        for quote in quotes:
            known = self.quotes.get(quote.isin)
            if known is None or known.trade_date <= quote.trade_date:
                self.quotes[quote.isin] = quote
        for rate in rates:
            known_rate = self.fx.get(rate.currency)
            if known_rate is None or known_rate[0] <= rate.trade_date:
                self.fx[rate.currency] = (rate.trade_date, rate.rate_to_eur)

    def record_scores(self, scores: Sequence[Score], *, at: datetime) -> None:
        del at
        for score in scores:
            self.score_history.append(score)
            known = self.scores.get(score.isin)
            if known is None or known.scoring_run_id <= score.scoring_run_id:
                self.scores[score.isin] = score

    def previous_scores(self, isins: Collection[str]) -> dict[str, Score]:
        previous: dict[str, Score] = {}
        for isin in set(isins):
            runs = sorted({s.scoring_run_id for s in self.score_history if s.isin == isin})
            if len(runs) >= 2:
                previous[isin] = [
                    s for s in self.score_history if s.isin == isin and s.scoring_run_id == runs[-2]
                ][-1]
        return previous

    def security_payloads(self, isins: Collection[str]) -> dict[str, dict[str, Any]]:
        return {i: p for i, p in self.payloads.items() if i in set(isins)}

    def market(self, isins: Collection[str]) -> Market:
        wanted = set(isins)
        return Market(
            securities={i: s for i, (_, s) in self.securities.items() if i in wanted},
            quotes={i: q for i, q in self.quotes.items() if i in wanted},
            fx={c: rate for c, (_, rate) in self.fx.items()},
            scores={i: s for i, s in self.scores.items() if i in wanted},
        )
