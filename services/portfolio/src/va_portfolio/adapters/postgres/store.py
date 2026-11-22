"""Depots im Schema ``portfolio`` (D3.1, Port ``DepotStore``).

Nur ``INSERT`` und ``SELECT``. Jede Aenderung schreibt ihre Zeilen und ``portfolio.depot.changed``
in die Outbox in einer Transaktion. Zwei gleichzeitige Speicherungen auf dieselbe Basis scheitern
an der Eindeutigkeit von (depot_id, version): Die zweite ergibt ``VersionConflict``. ``SELECT …
FOR UPDATE`` geht nicht, ``va_portfolio`` hat kein UPDATE-Recht.
"""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING, Any

from sqlalchemy import insert, select, text
from sqlalchemy.exc import IntegrityError

from va_platform.db import session_scope
from va_platform.messaging import Outbox

from ...domain.depots import CashLine, Depot, HoldingLine, Snapshot, VersionConflict
from .models import (
    CashLine as CashLineRow,
)
from .models import (
    Depot as DepotRow,
)
from .models import (
    DepotStatus,
    DepotVersion,
    HoldingSnapshot,
    PortfolioOutbox,
)
from .models import (
    HoldingLine as HoldingLineRow,
)

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime

    from sqlalchemy import Connection, Engine

    from va_contracts import Envelope
    from va_contracts.portfolio import DepotKind, DepotState

    from ...application.depots import EventFactory

# Je Depot die juengste Zeile von Name und Status
_DEPOTS = """
SELECT d.id, d.owner_user_id, d.kind, d.created_at, v.name, v.description, s.status
FROM portfolio.depot d
CROSS JOIN LATERAL (
    SELECT name, description FROM portfolio.depot_version
    WHERE depot_id = d.id ORDER BY id DESC LIMIT 1) v
CROSS JOIN LATERAL (
    SELECT status FROM portfolio.depot_status
    WHERE depot_id = d.id ORDER BY id DESC LIMIT 1) s
"""


def _depot(row: Any) -> Depot:
    return Depot(
        id=row.id,
        owner_user_id=row.owner_user_id,
        kind=row.kind,
        name=row.name,
        description=row.description,
        status=row.status,
        created_at=row.created_at,
    )


class PostgresDepotStore:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._outbox = Outbox(PortfolioOutbox)

    # --- Depots -----------------------------------------------------------------------

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
        with session_scope(self._engine) as session:
            depot_id = session.execute(
                insert(DepotRow)
                .values(owner_user_id=owner_user_id, kind=kind, created_at=at)
                .returning(DepotRow.id)
            ).scalar_one()
            session.execute(
                insert(DepotVersion).values(
                    depot_id=depot_id, name=name, description=description, created_at=at
                )
            )
            session.execute(insert(DepotStatus).values(depot_id=depot_id, status="active", at=at))
            self._outbox.add(session, changed(depot_id))
        return Depot(depot_id, owner_user_id, kind, name, description, "active", at)

    def depots(self, owner_user_id: int, *, include_archived: bool) -> list[Depot]:
        where = "WHERE d.owner_user_id = :owner"
        if not include_archived:
            where += " AND s.status = 'active'"
        with self._engine.connect() as conn:
            rows = conn.execute(text(f"{_DEPOTS} {where} ORDER BY d.id"), {"owner": owner_user_id})
            return [_depot(row) for row in rows]

    def depot(self, depot_id: int) -> Depot | None:
        with self._engine.connect() as conn:
            row = conn.execute(text(f"{_DEPOTS} WHERE d.id = :id"), {"id": depot_id}).first()
        return None if row is None else _depot(row)

    def rename(
        self,
        depot_id: int,
        *,
        name: str,
        description: str | None,
        at: datetime,
        event: Envelope[Any],
    ) -> None:
        with session_scope(self._engine) as session:
            session.execute(
                insert(DepotVersion).values(
                    depot_id=depot_id, name=name, description=description, created_at=at
                )
            )
            self._outbox.add(session, event)

    def set_status(
        self, depot_id: int, status: DepotState, *, at: datetime, event: Envelope[Any]
    ) -> None:
        with session_scope(self._engine) as session:
            session.execute(insert(DepotStatus).values(depot_id=depot_id, status=status, at=at))
            self._outbox.add(session, event)

    # --- Depotstaende -------------------------------------------------------------------

    def newest_version(self, depot_id: int) -> int:
        with self._engine.connect() as conn:
            return self._newest(conn, depot_id)

    @staticmethod
    def _newest(conn: Connection, depot_id: int) -> int:
        return int(
            conn.execute(
                text(
                    "SELECT coalesce(max(version), 0) FROM portfolio.holding_snapshot"
                    " WHERE depot_id = :id"
                ),
                {"id": depot_id},
            ).scalar_one()
        )

    def summary(self, depot_id: int) -> tuple[int, int]:
        with self._engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT s.version, (SELECT count(*) FROM portfolio.holding_line l"
                    " WHERE l.snapshot_id = s.id) AS positions"
                    " FROM portfolio.holding_snapshot s WHERE s.depot_id = :id"
                    " ORDER BY s.version DESC LIMIT 1"
                ),
                {"id": depot_id},
            ).first()
        return (0, 0) if row is None else (int(row.version), int(row.positions))

    def snapshot(self, depot_id: int, version: int | None = None) -> Snapshot | None:
        query = select(HoldingSnapshot).where(HoldingSnapshot.depot_id == depot_id)
        if version is None:
            query = query.order_by(HoldingSnapshot.version.desc()).limit(1)
        else:
            query = query.where(HoldingSnapshot.version == version)
        with self._engine.connect() as conn:
            row = conn.execute(query).first()
            if row is None:
                return None
            return self._snapshots(conn, [row])[0]

    def snapshots(self, depot_id: int) -> list[Snapshot]:
        query = (
            select(HoldingSnapshot)
            .where(HoldingSnapshot.depot_id == depot_id)
            .order_by(HoldingSnapshot.version)
        )
        with self._engine.connect() as conn:
            return self._snapshots(conn, list(conn.execute(query)))

    @staticmethod
    def _snapshots(conn: Connection, rows: Sequence[Any]) -> list[Snapshot]:
        ids = [row.id for row in rows]
        lines: dict[int, list[HoldingLine]] = defaultdict(list)
        cash: dict[int, list[CashLine]] = defaultdict(list)
        if ids:
            for line in conn.execute(
                select(HoldingLineRow)
                .where(HoldingLineRow.snapshot_id.in_(ids))
                .order_by(HoldingLineRow.snapshot_id, HoldingLineRow.position)
            ):
                lines[line.snapshot_id].append(
                    HoldingLine(
                        isin=line.isin,
                        quantity=line.quantity,
                        unit=line.unit,
                        cost_basis_eur=line.cost_basis_eur,
                        note=line.note,
                    )
                )
            for row in conn.execute(
                select(CashLineRow).where(CashLineRow.snapshot_id.in_(ids)).order_by(CashLineRow.id)
            ):
                cash[row.snapshot_id].append(CashLine(amount=row.amount, currency=row.currency))
        return [
            Snapshot(
                depot_id=row.depot_id,
                version=row.version,
                source=row.source,
                created_at=row.created_at,
                created_by=row.created_by,
                lines=tuple(lines[row.id]),
                cash=tuple(cash[row.id]),
            )
            for row in rows
        ]

    def save_snapshot(self, snapshot: Snapshot, *, event: Envelope[Any]) -> None:
        try:
            with session_scope(self._engine) as session:
                snapshot_id = session.execute(
                    insert(HoldingSnapshot)
                    .values(
                        depot_id=snapshot.depot_id,
                        version=snapshot.version,
                        source=snapshot.source,
                        created_by=snapshot.created_by,
                        created_at=snapshot.created_at,
                    )
                    .returning(HoldingSnapshot.id)
                ).scalar_one()
                if snapshot.lines:
                    session.execute(
                        insert(HoldingLineRow),
                        [
                            {
                                "snapshot_id": snapshot_id,
                                "position": position,
                                "isin": line.isin,
                                "quantity": line.quantity,
                                "unit": line.unit,
                                "cost_basis_eur": line.cost_basis_eur,
                                "note": line.note,
                            }
                            for position, line in enumerate(snapshot.lines)
                        ],
                    )
                for row in snapshot.cash:
                    session.execute(
                        insert(CashLineRow).values(
                            snapshot_id=snapshot_id, currency=row.currency, amount=row.amount
                        )
                    )
                self._outbox.add(session, event)
        except IntegrityError as e:
            if "uq_holding_snapshot_depot_id_version" not in str(e.orig):
                raise
            raise VersionConflict(self.newest_version(snapshot.depot_id)) from e
