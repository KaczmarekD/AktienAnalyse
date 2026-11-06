"""Eine Datenbank-Rolle je Service (P5.3): Rechte nur im eigenen Schema.

``va_market_data``, ``va_scoring`` und ``va_notification`` lesen und fuegen nur in ihrem Schema an
(``market_data``, ``scoring``, ``reporting``). Geaendert werden darf nur, was ``va_app`` auch
aendern darf (Abschluss, ISIN, ``published_at`` der Outbox); geloescht wird nie. Dass die Services
damit laufen, zeigt ``tests/db/test_services_nats.py``.
"""

from __future__ import annotations

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError

from tests.db.conftest import _role_engine
from va_platform.db.ddl import SERVICE_ROLES

SCHEMAS = ("batch", "market_data", "scoring", "reporting", "web", "identity")


def _tables(engine: Engine) -> list[tuple[str, str]]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT table_schema, table_name FROM information_schema.tables "
                "WHERE table_schema = ANY(:schemas) AND table_type = 'BASE TABLE'"
            ),
            {"schemas": list(SCHEMAS)},
        ).all()
    return [(str(s), str(t)) for s, t in rows]


def _allowed(engine: Engine, role: str, table: str, privilege: str) -> bool:
    with engine.connect() as conn:
        return bool(
            conn.execute(
                text("SELECT has_table_privilege(:role, :table, :privilege)"),
                {"role": role, "table": table, "privilege": privilege},
            ).scalar_one()
        )


def test_the_three_roles():
    assert SERVICE_ROLES == {
        "va_market_data": "market_data",
        "va_scoring": "scoring",
        "va_notification": "reporting",
    }


@pytest.mark.parametrize("role", sorted(SERVICE_ROLES))
def test_reads_and_appends_only_in_its_own_schema(engine, role):
    own = SERVICE_ROLES[role]
    tables = _tables(engine)
    assert tables
    for schema, name in tables:
        table = f"{schema}.{name}"
        for privilege in ("SELECT", "INSERT"):
            assert _allowed(engine, role, table, privilege) == (schema == own), (
                role,
                table,
                privilege,
            )
        assert not _allowed(engine, role, table, "DELETE"), (role, table)
        assert not _allowed(engine, role, table, "TRUNCATE"), (role, table)


@pytest.mark.parametrize("role", sorted(SERVICE_ROLES))
def test_updates_only_what_the_app_may_update(engine, role):
    own = SERVICE_ROLES[role]
    with engine.connect() as conn:
        updatable = {
            f"{schema}.{name}"
            for schema, name in conn.execute(
                text(
                    "SELECT DISTINCT table_schema, table_name "
                    "FROM information_schema.column_privileges "
                    "WHERE grantee = :role AND privilege_type = 'UPDATE'"
                ),
                {"role": role},
            ).all()
        }
    expected = {
        "va_market_data": {
            "market_data.fetch_run",
            "market_data.instrument",
            "market_data.outbox",
        },
        "va_scoring": {"scoring.outbox"},
        "va_notification": {"reporting.outbox"},
    }[role]
    assert updatable == expected
    assert all(table.startswith(f"{own}.") for table in updatable)


def test_scoring_cannot_read_market_data(db_url):
    """Das Beispiel aus dem Plan: scoring sieht die Abrufe von market-data nicht."""
    engine = _role_engine(db_url, "va_scoring")
    try:
        for table in ("market_data.fundamental_snapshot", "market_data.instrument"):
            with pytest.raises(DBAPIError, match="permission denied"), engine.connect() as conn:
                conn.execute(text(f"SELECT 1 FROM {table} LIMIT 1"))
        with engine.connect() as conn:
            assert conn.execute(text("SELECT count(*) FROM scoring.profile")).scalar_one() == 0
    finally:
        engine.dispose()


def test_notification_cannot_read_scoring(db_url):
    engine = _role_engine(db_url, "va_notification")
    try:
        with pytest.raises(DBAPIError, match="permission denied"), engine.connect() as conn:
            conn.execute(text("SELECT 1 FROM scoring.score_result LIMIT 1"))
    finally:
        engine.dispose()
