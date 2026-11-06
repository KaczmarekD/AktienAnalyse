"""Schema ``identity`` (D1.1): nur die Rolle ``va_identity`` kommt an Konten und Sitzungen.

``identity`` steht in ``APP_SCHEMAS`` (Loeschschutz und Outbox-Pruefung gelten), aber nicht in
``SCHEMAS`` von ``va_platform.db.ddl``: Dort vergeben die Grants jede Tabelle automatisch an
``va_read`` und ``va_app``. Persoenliche Daten duerfen die nie lesen, auch nicht nachdem eine
spaetere Migration die Grants erneut ausfuehrt (docs/architecture/depot/nutzer.md).
"""

from __future__ import annotations

import pytest
from sqlalchemy import Engine, text

from va_platform.db.ddl import (
    IDENTITY_ROLE,
    SCHEMAS,
    SERVICE_ROLES,
    grant_statements,
    identity_grant_statements,
    profiles_grant_statements,
    service_grant_statements,
    web_grant_statements,
)

OTHER_ROLES = ("va_app", "va_read", "va_web", "va_profiles", *SERVICE_ROLES)


def _identity_tables(engine: Engine) -> list[str]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT table_schema || '.' || table_name FROM information_schema.tables "
                "WHERE table_schema = 'identity' AND table_type = 'BASE TABLE'"
            )
        ).scalars()
        return sorted(rows)


def _allowed(engine: Engine, role: str, table: str, privilege: str) -> bool:
    with engine.connect() as conn:
        return bool(
            conn.execute(
                text("SELECT has_table_privilege(:role, :table, :privilege)"),
                {"role": role, "table": table, "privilege": privilege},
            ).scalar_one()
        )


def test_schema_is_not_shared_by_the_batch_grants():
    assert "identity" not in SCHEMAS
    assert IDENTITY_ROLE == "va_identity"


def test_tables_of_d1_1(engine):
    assert _identity_tables(engine) == [
        "identity.inbox",
        "identity.login_event",
        "identity.outbox",
        "identity.password_credential",
        "identity.session",
        "identity.session_revocation",
        "identity.session_seen",
        "identity.user_account",
        "identity.user_profile_version",
        "identity.user_status",
    ]


def test_identity_role_reads_and_appends_but_never_deletes(engine):
    for table in _identity_tables(engine):
        assert _allowed(engine, IDENTITY_ROLE, table, "SELECT"), table
        assert _allowed(engine, IDENTITY_ROLE, table, "INSERT"), table
        assert not _allowed(engine, IDENTITY_ROLE, table, "DELETE"), table
        assert not _allowed(engine, IDENTITY_ROLE, table, "TRUNCATE"), table


def test_identity_role_updates_only_published_at_of_its_outbox(engine):
    with engine.connect() as conn:
        updatable = sorted(
            f"{schema}.{name}.{column}"
            for schema, name, column in conn.execute(
                text(
                    "SELECT table_schema, table_name, column_name "
                    "FROM information_schema.column_privileges "
                    "WHERE grantee = :role AND privilege_type = 'UPDATE'"
                ),
                {"role": IDENTITY_ROLE},
            ).all()
        )
    assert updatable == ["identity.outbox.published_at"]


def test_identity_role_sees_no_other_schema(engine):
    with engine.connect() as conn:
        usable = set(
            conn.execute(
                text(
                    "SELECT nspname FROM pg_namespace "
                    "WHERE has_schema_privilege(:role, nspname, 'USAGE') "
                    "AND nspname NOT IN ('public', 'pg_catalog', 'information_schema') "
                    "AND nspname NOT LIKE 'pg_%'"
                ),
                {"role": IDENTITY_ROLE},
            ).scalars()
        )
    assert usable == {"identity"}


@pytest.mark.parametrize("role", OTHER_ROLES)
def test_no_other_role_reads_identity(engine, role):
    tables = _identity_tables(engine)
    assert tables
    for table in tables:
        for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
            assert not _allowed(engine, role, table, privilege), (role, table, privilege)


def test_rerunning_all_grants_keeps_identity_private(engine):
    """Eine spaetere Migration fuehrt die Grants erneut aus: ``identity`` bleibt privat."""
    with engine.begin() as conn:
        conn.execute(text(grant_statements()))
        conn.execute(text(web_grant_statements()))
        conn.execute(text(profiles_grant_statements()))
        for role in SERVICE_ROLES:
            conn.execute(text(service_grant_statements(role)))
        conn.execute(text(identity_grant_statements()))
    for role in OTHER_ROLES:
        for table in _identity_tables(engine):
            assert not _allowed(engine, role, table, "SELECT"), (role, table)


def test_the_session_table_holds_no_cookie_values(engine):
    with engine.connect() as conn:
        columns = set(
            conn.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = 'identity' AND table_name = 'session'"
                )
            ).scalars()
        )
    assert "id_hash" in columns
    assert not columns & {"id", "token", "cookie", "session_id"}
