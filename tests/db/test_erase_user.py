"""``python -m src.erase_user`` (D3.1, ADR-0012): Konto und Depots einer Person loeschen.

Die Depots zuerst (dafuer braucht es die ID des Kontos), dann das Konto. Das Protokoll in
``identity.erasure_log`` nennt die Zeilenzahlen beider Schemas, ohne Inhalte. Die Daten anderer
bleiben. Ohne ``--yes`` oder ohne ``DATABASE_OWNER_URL`` loescht es nichts.
"""

from __future__ import annotations

import io
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import Engine, text

from src import erase_user
from va_portfolio.adapters.postgres.store import PostgresDepotStore
from va_portfolio.application.depots import DepotService
from va_portfolio.domain.depots import HoldingLine
from va_web_api.adapters.postgres.identity_store import PostgresIdentityStore

T0 = datetime(2026, 11, 22, 10, 0, tzinfo=UTC)
HASH = "scrypt$1024$8$1$c2FsdA$aGFzaA"


@pytest.fixture
def people(identity_engine: Engine, portfolio_engine: Engine) -> dict[str, int]:
    accounts = PostgresIdentityStore(identity_engine)
    depots = DepotService(PostgresDepotStore(portfolio_engine), clock=lambda: T0)
    ids: dict[str, int] = {}
    for name in ("anna", "ben"):
        user_id = accounts.create_user(
            username=name, role="user", password_hash=HASH, display_name=None, email=None, at=T0
        )
        depot = depots.create(user_id, "depot", "DKB", None).depot
        depots.save(user_id, depot.id, 0, [HoldingLine("DE0007164600", Decimal("3"))], [])
        ids[name] = user_id
    return ids


def _main(monkeypatch, db_url: str, *argv: str) -> tuple[int, str]:
    monkeypatch.setenv("DATABASE_OWNER_URL", db_url)
    out = io.StringIO()
    monkeypatch.setattr("sys.stdout", out)
    return erase_user.main(list(argv)), out.getvalue()


def _depots(engine: Engine, user_id: int) -> int:
    with engine.connect() as conn:
        return int(
            conn.execute(
                text("SELECT count(*) FROM portfolio.depot WHERE owner_user_id = :id"),
                {"id": user_id},
            ).scalar_one()
        )


def _accounts(engine: Engine, name: str) -> int:
    with engine.connect() as conn:
        return int(
            conn.execute(
                text("SELECT count(*) FROM identity.user_account WHERE username = :n"), {"n": name}
            ).scalar_one()
        )


def test_account_and_depots_go_together(monkeypatch, db_url, engine, people):
    code, out = _main(monkeypatch, db_url, "anna", "--by", "dennis", "--yes")
    assert code == 0
    assert "portfolio.depot: 1" in out
    assert (_depots(engine, people["anna"]), _accounts(engine, "anna")) == (0, 0)
    assert (_depots(engine, people["ben"]), _accounts(engine, "ben")) == (1, 1)
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT rows FROM identity.erasure_log")).scalar_one()
    assert rows["portfolio.holding_line"] == 1
    assert rows["user_account"] == 1


def test_refuses_without_yes(monkeypatch, db_url, engine, people):
    code, _ = _main(monkeypatch, db_url, "anna", "--by", "dennis")
    assert code == 2
    assert _depots(engine, people["anna"]) == 1


def test_unknown_account(monkeypatch, db_url, engine, people):
    code, _ = _main(monkeypatch, db_url, "carla", "--by", "dennis", "--yes")
    assert code == 1
    assert _depots(engine, people["anna"]) == 1


def test_needs_the_owner_url(monkeypatch, people):
    monkeypatch.delenv("DATABASE_OWNER_URL", raising=False)
    assert erase_user.main(["anna", "--by", "dennis", "--yes"]) == 2
