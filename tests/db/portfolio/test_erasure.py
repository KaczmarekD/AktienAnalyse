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

from va_contracts.portfolio import HintParamsV1, TargetAllocationV1
from va_portfolio.adapters.postgres.erasure import erase_user
from va_portfolio.adapters.postgres.market import PostgresMarketStore
from va_portfolio.adapters.postgres.store import PostgresDepotStore
from va_portfolio.application.depots import DepotService
from va_portfolio.domain.depots import CashLine, HoldingLine
from va_portfolio.domain.valuation import Quote

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
        # D5.2: Laeufe der Analyse und ihre Hinweise
        "analysis_run": f"depot_id IN ({depots})",
        "hint": f"analysis_run_id IN (SELECT id FROM portfolio.analysis_run WHERE depot_id IN ({depots}))",
        # D5.3: Schwellen, Zielallokation, Kenntnisnahmen
        "hint_params": f"depot_id IN ({depots})",
        "target_allocation": f"depot_id IN ({depots})",
        "hint_ack": f"depot_id IN ({depots})",
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
    market = PostgresMarketStore(portfolio_engine)
    market.record_prices([Quote(SAP, T0.date(), Decimal(100), "EUR")], [], at=T0)
    store = PostgresDepotStore(portfolio_engine)
    service = DepotService(store, clock=lambda: T0, market=market)
    depot = service.create(owner, "depot", "DKB", None).depot
    service.save(owner, depot.id, 0, [HoldingLine(SAP, Decimal("3"))], [CashLine(Decimal("5"))])
    # D5.3: eigene Schwellen und Ziele, ein Hinweis zur Kenntnis genommen
    service.save_hint_params(owner, depot.id, 0, HintParamsV1(k01_warning=0.5, k01_critical=0.9))
    service.save_target(owner, depot.id, 0, TargetAllocationV1(shares={"equity": 1.0}))
    run = store.latest_run(depot.id)
    assert run is not None
    service.acknowledge(owner, depot.id, run.hints[0].hint.key)
    service.update(owner, depot.id, "Neu", None)
    service.archive(owner, depot.id)


def test_all_rows_of_the_person_and_only_them(engine, portfolio_engine):
    _fill(portfolio_engine, ANNA)
    _fill(portfolio_engine, BEN)
    assert all(_rows(engine, ANNA).values())
    ben = _rows(engine, BEN)
    rows = erase_user(engine, ANNA)
    assert rows["portfolio.depot"] == 1
    assert rows["portfolio.holding_line"] == 1
    # D5.2: der neue Depotstand bekam seine Analyse, D5.3: die neuen Schwellen eine zweite
    assert rows["portfolio.analysis_run"] == 2
    assert rows["portfolio.hint"] >= 1
    assert (rows["portfolio.hint_params"], rows["portfolio.target_allocation"]) == (1, 1)
    assert rows["portfolio.hint_ack"] == 1
    # created, holdings, analysis.completed (Depotstand, Schwellen), renamed, archived
    assert rows["portfolio.outbox"] == 6
    assert set(_rows(engine, ANNA).values()) == {0}
    assert _rows(engine, BEN) == ben


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
