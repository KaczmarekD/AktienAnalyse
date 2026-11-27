"""Depots und Marktdaten im Speicher (Ports ``DepotStore``, ``MarketStore``), fuer Tests.

Verhaelt sich wie ``PostgresDepotStore``: Daten und Event einer Aenderung gemeinsam, eine
vergebene Version ergibt ``VersionConflict``. Die Events sammelt ``events`` (statt der Outbox).
"""

from __future__ import annotations

import threading
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from ..domain.depots import Depot, Snapshot, VersionConflict
from ..domain.valuation import Market, Quote, Score, SecurityInfo

if TYPE_CHECKING:
    from collections.abc import Collection, Sequence
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


class MemoryMarketStore:
    """Kopien der Marktdaten (D3.4): je ISIN bzw. Waehrung gilt das Juengste."""

    def __init__(self) -> None:
        self.securities: dict[str, tuple[date, SecurityInfo]] = {}
        self.quotes: dict[str, Quote] = {}
        self.fx: dict[str, tuple[date, Decimal]] = {}
        self.payloads: dict[str, dict[str, Any]] = {}
        self.scores: dict[str, Score] = {}

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
            known = self.scores.get(score.isin)
            if known is None or known.scoring_run_id <= score.scoring_run_id:
                self.scores[score.isin] = score

    def market(self, isins: Collection[str]) -> Market:
        wanted = set(isins)
        return Market(
            securities={i: s for i, (_, s) in self.securities.items() if i in wanted},
            quotes={i: q for i, q in self.quotes.items() if i in wanted},
            fx={c: rate for c, (_, rate) in self.fx.items()},
            scores={i: s for i, s in self.scores.items() if i in wanted},
        )
