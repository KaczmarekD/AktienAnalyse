"""Loeschen der Depots einer Person (D3.1, ADR-0012, nutzer.md).

Depots werden sonst nur archiviert. Auf ausdruecklichen Wunsch einer Person loescht
``erase_user`` alle ihre Zeilen in ``portfolio``, die Outbox eingeschlossen; die anderer bleiben.
Mit der Rolle des Besitzers; der Schutz ist danach wieder an.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError

from va_portfolio.adapters.postgres.erasure import erase_user
from va_portfolio.adapters.postgres.store import PostgresDepotStore
from va_portfolio.application.depots import DepotService
from va_portfolio.domain.depots import CashLine, HoldingLine

T0 = datetime(2026, 11, 22, 10, 0, tzinfo=UTC)
ANNA, BEN = 1, 2
SAP = "DE0007164600"


def _rows(engine: Engine, owner: int) -> dict[str, int]:
    depots = "SELECT id FROM portfolio.depot WHERE owner_user_id = :id"
    snaps = f"SELECT id FROM portfolio.holding_snapshot WHERE depot_id IN ({depots})"
    queries = {
        "depot": "owner_user_id = :id",
        "depot_version": f"depot_id IN ({depots})",
        "depot_status": f"depot_id IN ({depots})",
        "holding_snapshot": f"depot_id IN ({depots})",
        "holding_line": f"snapshot_id IN ({snaps})",
        "cash_line": f"snapshot_id IN ({snaps})",
        "outbox": "(payload -> 'data' ->> 'owner_user_id')::bigint = :id",
    }
    with engine.connect() as conn:
        return {
            table: int(
                conn.execute(
                    text(f"SELECT count(*) FROM portfolio.{table} WHERE {where}"), {"id": owner}
                ).scalar_one()
            )
            for table, where in queries.items()
        }


def _fill(portfolio_engine: Engine, owner: int) -> None:
    service = DepotService(PostgresDepotStore(portfolio_engine), clock=lambda: T0)
    depot = service.create(owner, "depot", "DKB", None).depot
    service.save(owner, depot.id, 0, [HoldingLine(SAP, Decimal("3"))], [CashLine(Decimal("5"))])
    service.update(owner, depot.id, "Neu", None)
    service.archive(owner, depot.id)


def test_all_rows_of_the_person_and_only_them(engine, portfolio_engine):
    _fill(portfolio_engine, ANNA)
    _fill(portfolio_engine, BEN)
    assert all(_rows(engine, ANNA).values())
    rows = erase_user(engine, ANNA)
    assert rows["portfolio.depot"] == 1
    assert rows["portfolio.holding_line"] == 1
    assert rows["portfolio.outbox"] == 4  # created, holdings, renamed, archived
    assert set(_rows(engine, ANNA).values()) == {0}
    assert _rows(engine, BEN) == {
        "depot": 1,
        "depot_version": 2,
        "depot_status": 2,
        "holding_snapshot": 1,
        "holding_line": 1,
        "cash_line": 1,
        "outbox": 4,
    }


def test_a_person_without_depots(engine):
    assert set(erase_user(engine, ANNA).values()) == {0}


def test_the_protection_is_back_on(engine, portfolio_engine):
    _fill(portfolio_engine, BEN)
    erase_user(engine, ANNA)
    with pytest.raises(DBAPIError), engine.begin() as conn:
        conn.execute(text("DELETE FROM portfolio.depot"))


def test_only_the_owner_role_may_erase(portfolio_engine):
    _fill(portfolio_engine, ANNA)
    with pytest.raises(DBAPIError):
        erase_user(portfolio_engine, ANNA)
