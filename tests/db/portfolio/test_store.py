"""Depots im Schema portfolio (D3.1, DEP-01, 03, 04, 06; ADR-0013).

Mit der Rolle des Dienstes (``va_portfolio``): lesen und anfuegen, nie aendern oder loeschen.
- Ein Depot mit Name, Status und Depotstaenden; Name und Status gelten in der juengsten Zeile.
- Mengen und Betraege als ``numeric``, zurueck als ``Decimal``, Reihenfolge der Eingabe.
- Zwei Speicherungen auf dieselbe Version: die zweite ist ein Konflikt mit der neuesten.
- Jede Aenderung legt ``portfolio.depot.changed`` in dieselbe Transaktion (Outbox).
- D3.3: Die Abdeckung sind die ISINs der neuesten Staende aktiver Depots, aller Nutzer.
- Persoenliche Daten: ``va_read``, ``va_app`` und die anderen Rollen sehen nichts.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError

from va_contracts import new_envelope
from va_contracts.events.v1 import (
    COVERAGE_CHANGED,
    DEPOT_CHANGED,
    CoverageChangedV1,
    DepotChangedV1,
)
from va_platform.db.ddl import SERVICE_ROLES
from va_portfolio.adapters.postgres.store import PostgresDepotStore
from va_portfolio.application.depots import DepotService
from va_portfolio.domain.depots import CashLine, HoldingLine, Snapshot, VersionConflict

T0 = datetime(2026, 11, 22, 10, 0, tzinfo=UTC)
ANNA, BEN = 1, 2
SAP = "DE0007164600"
BUND = "DE0001102580"
APPLE = "US0378331005"
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
    "security_view",  # D3.4
    "price_view",
    "fx_view",
    "analysis_run",  # D5.2
    "hint",
    "hint_params",  # D5.3
    "target_allocation",
    "hint_ack",
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

    def test_import_keeps_the_hash_of_the_file(self, store):
        """D3.5: Herkunft ``import`` mit dem SHA-256 der Datei in ``source_ref``."""
        depot = _depot(store)
        snapshot = Snapshot(
            depot_id=depot.id,
            version=1,
            source="import",
            created_at=T0,
            created_by=ANNA,
            lines=(HoldingLine(SAP, Decimal(1)),),
            source_ref="ab" * 32,
        )
        store.save_snapshot(snapshot, event=_event(depot.id))
        assert store.snapshot(depot.id) == snapshot

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


def _coverage_event(isins: list[str]):
    return new_envelope(COVERAGE_CHANGED, CoverageChangedV1(isins=isins), source="va/test")


def _outbox(engine: Engine, subject: str) -> list[dict]:
    with engine.connect() as conn:
        return list(
            conn.execute(
                text(
                    "SELECT payload FROM portfolio.outbox WHERE subject = :s"
                    " ORDER BY created_at, id"
                ),
                {"s": subject},
            ).scalars()
        )


class TestCoverage:
    def _save(self, store, depot_id: int, version: int, *isins: str) -> None:
        store.save_snapshot(
            Snapshot(
                depot_id=depot_id,
                version=version,
                source="manual",
                created_at=T0,
                created_by=ANNA,
                lines=tuple(HoldingLine(isin, Decimal(1)) for isin in isins),
            ),
            event=_event(depot_id, version=version),
        )

    def test_newest_snapshots_of_active_depots_of_all_users(self, store):
        annas, bens, archived = _depot(store, ANNA), _depot(store, BEN), _depot(store, ANNA)
        self._save(store, annas.id, 1, SAP, BUND)
        self._save(store, annas.id, 2, SAP)  # BUND verkauft
        self._save(store, bens.id, 1, APPLE, SAP)
        self._save(store, archived.id, 1, BUND)
        store.set_status(archived.id, "archived", at=T0, event=_event(archived.id))
        assert store.held_isins() == sorted({SAP, APPLE})

    def test_add_coverage_only_on_change(self, store, engine):
        depot = _depot(store)
        self._save(store, depot.id, 1, SAP)
        assert store.add_coverage(_coverage_event, unless=[SAP]) is False
        assert store.add_coverage(_coverage_event, unless=[]) is True
        assert store.add_coverage(_coverage_event) is True  # ohne Vergleich immer
        events = _outbox(engine, "va.portfolio.coverage.changed")
        assert [e["data"]["isins"] for e in events] == [[SAP], [SAP]]

    def test_the_service_reports_coverage_on_postgres(self, store, engine):
        service = DepotService(store, clock=lambda: T0)
        depot = service.create(ANNA, "watchlist", "Ideen", None).depot
        service.save(ANNA, depot.id, 0, [HoldingLine(SAP, None)], [])
        service.archive(ANNA, depot.id)
        events = _outbox(engine, "va.portfolio.coverage.changed")
        assert [e["data"]["isins"] for e in events] == [[SAP], []]


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


class TestRuns:
    """D5.2: Laeufe der Analyse mit Hinweisen, Event in derselben Transaktion."""

    def test_round_trip_with_hints_and_event(self, store, engine):
        from va_contracts.events.v1 import ANALYSIS_COMPLETED, AnalysisCompletedV1
        from va_portfolio.domain.hints import Hint, TrackedHint

        depot = _depot(store)
        hints = [
            TrackedHint(Hint("HIN-K01", SAP, "critical", 0.3, 0.2, T0.date()), "new"),
            TrackedHint(Hint("HIN-A02", "depot", "info", 0.7, 0.1), "resolved"),
        ]

        def event(run_id: int):
            data = AnalysisCompletedV1(
                depot_id=depot.id, owner_user_id=ANNA, analysis_run_id=run_id, critical=1
            )
            return new_envelope(ANALYSIS_COMPLETED, data, source="va/test")

        run_id = store.save_run(
            depot.id,
            version=1,
            trigger="holdings",
            fingerprint="abc",
            result={"value_eur": "10.00"},
            hints=hints,
            at=T0,
            event=event,
        )
        run = store.latest_run(depot.id)
        assert run is not None
        assert (run.id, run.version, run.fingerprint) == (run_id, 1, "abc")
        assert [(t.hint.key, t.status, t.hint.as_of) for t in run.hints] == [
            (f"HIN-K01:{SAP}", "new", T0.date()),
            ("HIN-A02:depot", "resolved", None),
        ]
        [payload] = _outbox(engine, ANALYSIS_COMPLETED.subject)
        assert payload["data"]["analysis_run_id"] == run_id
        assert store.latest_run(depot.id + 1) is None

    def test_only_active_depots(self, store):
        active = _depot(store, name="Aktiv")
        archived = _depot(store, name="Archiv")
        store.set_status(archived.id, "archived", at=T0, event=_event(archived.id, "archived"))
        assert [d.id for d in store.active_depots()] == [active.id]


class TestSettings:
    """D5.3: Schwellen und Zielallokation versioniert, Kenntnisnahmen je Schluessel."""

    def test_versions_and_conflict(self, store):
        depot = _depot(store)
        empty = store.settings(depot.id)
        assert (empty.hint_params, empty.hint_params_version) == ({}, 0)
        assert (dict(empty.target), empty.target_version) == ({}, 0)
        store.save_hint_params(depot.id, version=1, params={"k01_warning": 0.2}, by=ANNA, at=T0)
        store.save_target(depot.id, version=1, shares={"equity": 0.6, "cash": 0.4}, by=ANNA, at=T0)
        store.save_hint_params(depot.id, version=2, params={"k01_warning": 0.3}, by=ANNA, at=T0)
        settings = store.settings(depot.id)
        assert (settings.hint_params, settings.hint_params_version) == ({"k01_warning": 0.3}, 2)
        assert (dict(settings.target), settings.target_version) == ({"equity": 0.6, "cash": 0.4}, 1)
        with pytest.raises(VersionConflict) as conflict:
            store.save_hint_params(depot.id, version=2, params={}, by=ANNA, at=T0)
        assert conflict.value.newest == 2
        with pytest.raises(VersionConflict) as conflict:
            store.save_target(depot.id, version=1, shares={}, by=ANNA, at=T0)
        assert conflict.value.newest == 1
        assert store.settings(depot.id + 1).hint_params_version == 0

    def test_the_latest_ack_per_key(self, store):
        depot = _depot(store)
        run_id = _run(store, depot.id, [("HIN-K01", "X", "new")])
        later = T0 + timedelta(hours=1)
        for key, measured, severity, at in (
            ("HIN-K01:X", 0.2, "warning", T0),
            ("HIN-K01:X", 0.25, "critical", later),
            ("HIN-A02:depot", None, "info", T0),
        ):
            store.save_ack(
                depot.id,
                key=key,
                user_id=ANNA,
                run_id=run_id,
                measured=measured,
                severity=severity,
                at=at,
            )
        acks = store.acks(depot.id)
        assert {k: (a.measured, a.severity, a.at, a.run_id) for k, a in acks.items()} == {
            "HIN-K01:X": (0.25, "critical", later, run_id),
            "HIN-A02:depot": (None, "info", T0, run_id),
        }
        assert store.acks(depot.id + 1) == {}
        assert [a.measured for a in store.settings_history(depot.id).acks] == [0.2, 0.25, None]

    def test_since_new_is_the_latest_run_where_a_hint_appeared(self, store):
        depot = _depot(store)
        first = _run(store, depot.id, [("HIN-K01", "X", "new"), ("HIN-A02", "depot", "new")])
        _run(store, depot.id, [("HIN-K01", "X", "existing"), ("HIN-A02", "depot", "existing")])
        _run(store, depot.id, [("HIN-K01", "X", "resolved"), ("HIN-A02", "depot", "existing")])
        again = _run(store, depot.id, [("HIN-K01", "X", "new"), ("HIN-A02", "depot", "existing")])
        assert store.since_new(depot.id) == {"HIN-K01:X": again, "HIN-A02:depot": first}
        assert store.since_new(depot.id + 1) == {}

    def test_the_history_of_the_settings(self, store):
        depot = _depot(store)
        later = T0 + timedelta(days=1)
        store.save_hint_params(depot.id, version=1, params={"a02_cash": 0.2}, by=ANNA, at=T0)
        store.save_hint_params(depot.id, version=2, params={"a02_cash": 0.3}, by=ANNA, at=later)
        store.save_target(depot.id, version=1, shares={"equity": 1.0}, by=ANNA, at=T0)
        history = store.settings_history(depot.id)
        assert [(v.version, dict(v.values), v.created_at) for v in history.hint_params] == [
            (1, {"a02_cash": 0.2}, T0),
            (2, {"a02_cash": 0.3}, later),
        ]
        assert [dict(v.values) for v in history.targets] == [{"equity": 1.0}]
        assert history.acks == []

    def test_the_trigger_settings_is_allowed(self, store):
        depot = _depot(store)
        run_id = _run(store, depot.id, [("HIN-A02", "depot", "new")], trigger="settings")
        run = store.latest_run(depot.id)
        assert run is not None
        assert run.id == run_id


def _run(store, depot_id: int, hints, trigger: str = "holdings") -> int:
    """Ein Lauf mit Hinweisen (Regel, Gegenstand, Status), wie ihn ``_refresh`` speichert."""
    from va_contracts.events.v1 import ANALYSIS_COMPLETED, AnalysisCompletedV1
    from va_portfolio.domain.hints import Hint, TrackedHint

    def event(run_id: int):
        data = AnalysisCompletedV1(
            depot_id=depot_id, owner_user_id=ANNA, analysis_run_id=run_id, info=len(hints)
        )
        return new_envelope(ANALYSIS_COMPLETED, data, source="va/test")

    return store.save_run(
        depot_id,
        version=1,
        trigger=trigger,
        fingerprint=f"{trigger}-{hints}",
        result={},
        hints=[
            TrackedHint(Hint(rule, subject, "info", 0.7, 0.1), status)
            for rule, subject, status in hints
        ],
        at=T0,
        event=event,
    )
