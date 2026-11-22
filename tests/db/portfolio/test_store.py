"""Depots im Schema portfolio (D3.1, DEP-01, 03, 04, 06; ADR-0013).

Mit der Rolle des Dienstes (``va_portfolio``): lesen und anfuegen, nie aendern oder loeschen.
- Ein Depot mit Name, Status und Depotstaenden; Name und Status gelten in der juengsten Zeile.
- Mengen und Betraege als ``numeric``, zurueck als ``Decimal``, Reihenfolge der Eingabe.
- Zwei Speicherungen auf dieselbe Version: die zweite ist ein Konflikt mit der neuesten.
- Jede Aenderung legt ``portfolio.depot.changed`` in dieselbe Transaktion (Outbox).
- Persoenliche Daten: ``va_read``, ``va_app`` und die anderen Rollen sehen nichts.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError

from va_contracts import new_envelope
from va_contracts.events.v1 import DEPOT_CHANGED, DepotChangedV1
from va_platform.db.ddl import SERVICE_ROLES
from va_portfolio.adapters.postgres.store import PostgresDepotStore
from va_portfolio.application.depots import DepotService
from va_portfolio.domain.depots import CashLine, HoldingLine, Snapshot, VersionConflict

T0 = datetime(2026, 11, 22, 10, 0, tzinfo=UTC)
ANNA, BEN = 1, 2
SAP = "DE0007164600"
BUND = "DE0001102580"
OTHER_ROLES = ("va_app", "va_read", "va_web", "va_profiles", "va_identity", *SERVICE_ROLES)
TABLES = (
    "depot",
    "depot_version",
    "depot_status",
    "holding_snapshot",
    "holding_line",
    "cash_line",
    "outbox",
    "inbox",
)


def _event(depot_id: int, change: str = "holdings", version: int = 1):
    data = DepotChangedV1(depot_id=depot_id, owner_user_id=ANNA, change=change, version=version)  # type: ignore[arg-type]
    return new_envelope(DEPOT_CHANGED, data, source="va/test")


def _count(engine: Engine, table: str) -> int:
    with engine.connect() as conn:
        return int(conn.execute(text(f"SELECT count(*) FROM portfolio.{table}")).scalar_one())


@pytest.fixture
def store(portfolio_engine: Engine) -> PostgresDepotStore:
    return PostgresDepotStore(portfolio_engine)


def _depot(store: PostgresDepotStore, owner: int = ANNA, name: str = "DKB"):
    return store.create_depot(
        owner_user_id=owner,
        kind="depot",
        name=name,
        description=None,
        at=T0,
        changed=lambda depot_id: _event(depot_id, "created", 0),
    )


class TestDepots:
    def test_create_read_rename_archive(self, store, engine):
        depot = _depot(store)
        assert store.depot(depot.id) == depot
        store.rename(
            depot.id, name="Altersvorsorge", description="Sparplan", at=T0, event=_event(depot.id)
        )
        store.set_status(depot.id, "archived", at=T0, event=_event(depot.id))
        current = store.depot(depot.id)
        assert current is not None
        assert (current.name, current.description, current.status) == (
            "Altersvorsorge",
            "Sparplan",
            "archived",
        )
        assert store.depots(ANNA, include_archived=False) == []
        assert [d.id for d in store.depots(ANNA, include_archived=True)] == [depot.id]
        assert _count(engine, "depot_version") == 2  # angefuegt, nicht ueberschrieben
        assert _count(engine, "outbox") == 3

    def test_only_own_depots_are_listed(self, store):
        _depot(store, ANNA, "Annas")
        _depot(store, BEN, "Bens")
        assert [d.name for d in store.depots(ANNA, include_archived=True)] == ["Annas"]

    def test_unknown(self, store):
        assert store.depot(999) is None


class TestSnapshots:
    def _snapshot(self, depot_id: int, version: int, *lines: HoldingLine) -> Snapshot:
        return Snapshot(
            depot_id=depot_id,
            version=version,
            source="manual",
            created_at=T0 + timedelta(minutes=version),
            created_by=ANNA,
            lines=lines,
            cash=(CashLine(Decimal("250.10")),),
        )

    def test_round_trip_with_decimals(self, store):
        depot = _depot(store)
        lines = (
            HoldingLine(SAP, Decimal("12.5"), cost_basis_eur=Decimal("1500.25"), note="Kauf"),
            HoldingLine(BUND, Decimal("10000"), unit="nominal"),
        )
        snapshot = self._snapshot(depot.id, 1, *lines)
        store.save_snapshot(snapshot, event=_event(depot.id))
        assert store.newest_version(depot.id) == 1
        assert store.summary(depot.id) == (1, 2)
        assert store.snapshot(depot.id) == snapshot
        assert store.snapshot(depot.id, 1) == snapshot
        assert store.snapshot(depot.id, 2) is None

    def test_history_oldest_first(self, store):
        depot = _depot(store)
        for version in (1, 2, 3):
            store.save_snapshot(
                self._snapshot(depot.id, version, HoldingLine(SAP, Decimal(version))),
                event=_event(depot.id, version=version),
            )
        assert [s.version for s in store.snapshots(depot.id)] == [1, 2, 3]
        assert store.snapshot(depot.id).version == 3  # type: ignore[union-attr]

    def test_a_taken_version_is_a_conflict(self, store, engine):
        depot = _depot(store)
        store.save_snapshot(self._snapshot(depot.id, 1), event=_event(depot.id))
        with pytest.raises(VersionConflict) as caught:
            store.save_snapshot(self._snapshot(depot.id, 1), event=_event(depot.id))
        assert caught.value.newest == 1
        assert _count(engine, "holding_snapshot") == 1
        assert _count(engine, "outbox") == 2  # created und der erste Stand, nicht der zweite

    def test_without_snapshot_version_0(self, store):
        depot = _depot(store)
        assert (store.newest_version(depot.id), store.snapshot(depot.id)) == (0, None)
        assert store.summary(depot.id) == (0, 0)

    def test_the_service_on_postgres(self, store):
        service = DepotService(store, clock=lambda: T0)
        depot = service.create(ANNA, "depot", "DKB", None).depot
        service.save(ANNA, depot.id, 0, [HoldingLine(SAP, Decimal("3"))], [])
        service.save(ANNA, depot.id, 1, [HoldingLine(SAP, Decimal("4"))], [])
        [newest, first] = service.history(ANNA, depot.id)
        assert (newest.version, newest.diff.changed, first.diff.added) == (2, 1, 1)


class TestRoles:
    def test_the_service_role_never_changes_or_deletes(self, store, portfolio_engine):
        depot = _depot(store)
        for statement in (
            "DELETE FROM portfolio.depot",
            "UPDATE portfolio.depot SET kind = 'watchlist'",
            "TRUNCATE portfolio.depot_version",
        ):
            with pytest.raises(DBAPIError), portfolio_engine.begin() as conn:
                conn.execute(text(statement))
        assert store.depot(depot.id) is not None

    @pytest.mark.parametrize("role", OTHER_ROLES)
    def test_no_other_role_reads_portfolio(self, engine, role):
        with engine.connect() as conn:
            for table in TABLES:
                allowed = conn.execute(
                    text("SELECT has_table_privilege(:role, :table, 'SELECT')"),
                    {"role": role, "table": f"portfolio.{table}"},
                ).scalar_one()
                assert not allowed, (role, table)

    def test_the_service_role_sees_no_other_schema(self, portfolio_engine):
        for table in ("identity.user_account", "market_data.security", "web.run_status"):
            with pytest.raises(DBAPIError), portfolio_engine.connect() as conn:
                conn.execute(text(f"SELECT 1 FROM {table} LIMIT 1"))

    @pytest.mark.parametrize("table", TABLES)
    def test_every_table_is_protected(self, engine, table):
        with pytest.raises(DBAPIError), engine.begin() as conn:
            conn.execute(text(f"DELETE FROM portfolio.{table}"))
