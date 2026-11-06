"""Schema identity: Konten, Anmeldungen und Sitzungen des web-api (Paket D1.1)

Revision ID: 0015
Revises: 0014
Erstellt: 2026-11-06

Nur additiv. Persoenliche Daten (ADR-0012): Lesen und anfuegen darf nur ``va_identity``
(``identity_grant_statements``). ``identity`` steht nicht in ``SCHEMAS`` von
``va_platform.db.ddl``, also bekommen ``va_read`` und ``va_app`` hier nichts. Alle Tabellen sind
nur zum Anfuegen (``protect_table``), die Outbox setzt ``published_at`` einmal (Trigger aus
``0009``). Die Rolle selbst legen ``db/init/01_roles.sh`` (neue Datenbank) und
``python -m src.db.migrate`` (bestehende, mit ``VA_IDENTITY_PASSWORD``) an.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from va_platform.db.ddl import identity_grant_statements, protect_table

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "identity"
ROLES = ("admin", "user")
STATUSES = ("active", "disabled")
LOGIN_REASONS = ("ok", "wrong_password", "unknown_user", "locked", "disabled")
REVOKE_REASONS = ("logout", "admin", "password_changed", "disabled")
TABLES = (
    "user_account",
    "user_profile_version",
    "user_status",
    "password_credential",
    "session",
    "session_seen",
    "session_revocation",
    "login_event",
    "inbox",
    "outbox",
)


def _now() -> sa.TextClause:
    return sa.text("now()")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def _id() -> sa.Column:
    return sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False)


def _user_fk(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["user_id"],
        [f"{SCHEMA}.user_account.id"],
        name=op.f(f"fk_{table}_user_id_user_account"),
    )


def upgrade() -> None:
    op.execute(f"CREATE SCHEMA {SCHEMA}")
    op.create_table(
        "user_account",
        _id(),
        sa.Column("username", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_now(), nullable=False),
        sa.CheckConstraint(_in("role", ROLES), name=op.f("ck_user_account_role")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_user_account")),
        sa.UniqueConstraint("username", name=op.f("uq_user_account_username")),
        schema=SCHEMA,
    )
    op.create_table(
        "user_profile_version",
        _id(),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=True),
        sa.Column("email", sa.Text(), nullable=True),
        sa.Column("email_confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_now(), nullable=False),
        _user_fk("user_profile_version"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_user_profile_version")),
        schema=SCHEMA,
    )
    op.create_table(
        "user_status",
        _id(),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("at", sa.DateTime(timezone=True), server_default=_now(), nullable=False),
        sa.CheckConstraint(_in("status", STATUSES), name=op.f("ck_user_status_status")),
        _user_fk("user_status"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_user_status")),
        schema=SCHEMA,
    )
    op.create_table(
        "password_credential",
        _id(),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("hash", sa.Text(), nullable=False),
        sa.Column("must_change", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_now(), nullable=False),
        _user_fk("password_credential"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_password_credential")),
        schema=SCHEMA,
    )
    op.create_table(
        "session",
        sa.Column("id_hash", sa.Text(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_now(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("ip", sa.Text(), nullable=True),
        _user_fk("session"),
        sa.PrimaryKeyConstraint("id_hash", name=op.f("pk_session")),
        schema=SCHEMA,
    )
    op.create_table(
        "session_seen",
        _id(),
        sa.Column("id_hash", sa.Text(), nullable=False),
        sa.Column("seen_at", sa.DateTime(timezone=True), server_default=_now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["id_hash"],
            [f"{SCHEMA}.session.id_hash"],
            name=op.f("fk_session_seen_id_hash_session"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_session_seen")),
        schema=SCHEMA,
    )
    op.create_table(
        "session_revocation",
        sa.Column("id_hash", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), server_default=_now(), nullable=False),
        sa.CheckConstraint(
            _in("reason", REVOKE_REASONS), name=op.f("ck_session_revocation_reason")
        ),
        sa.ForeignKeyConstraint(
            ["id_hash"],
            [f"{SCHEMA}.session.id_hash"],
            name=op.f("fk_session_revocation_id_hash_session"),
        ),
        sa.PrimaryKeyConstraint("id_hash", name=op.f("pk_session_revocation")),
        schema=SCHEMA,
    )
    op.create_table(
        "login_event",
        _id(),
        sa.Column("username", sa.Text(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=True),
        sa.Column("ip", sa.Text(), nullable=True),
        sa.Column("ok", sa.Boolean(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), server_default=_now(), nullable=False),
        sa.CheckConstraint(_in("reason", LOGIN_REASONS), name=op.f("ck_login_event_reason")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_login_event")),
        schema=SCHEMA,
    )
    op.create_table(
        "inbox",
        sa.Column("message_id", sa.Uuid(), nullable=False),
        sa.Column("consumer", sa.Text(), nullable=False),
        sa.Column(
            "processed_at", sa.DateTime(timezone=True), server_default=_now(), nullable=False
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("message_id", "consumer", name=op.f("pk_inbox")),
        schema=SCHEMA,
    )
    op.create_table(
        "outbox",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_now(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_outbox")),
        schema=SCHEMA,
    )
    for table, columns in (
        ("user_profile_version", ["user_id"]),
        ("user_status", ["user_id"]),
        ("password_credential", ["user_id"]),
        ("session", ["user_id"]),
        ("session_seen", ["id_hash", "seen_at"]),
        ("login_event", ["username", "at"]),
        ("login_event", ["ip", "at"]),
    ):
        op.create_index(
            op.f(f"ix_{table}_{'_'.join(columns)}"), table, columns, unique=False, schema=SCHEMA
        )
    op.create_index(
        "ix_outbox_pending",
        "outbox",
        ["created_at"],
        unique=False,
        schema=SCHEMA,
        postgresql_where=sa.text("published_at IS NULL"),
    )
    for table in TABLES:
        for statement in protect_table(f"{SCHEMA}.{table}"):
            op.execute(statement)
    op.execute(identity_grant_statements())


def downgrade() -> None:
    msg = "Downgrades wuerden Daten loeschen und sind nicht vorgesehen"
    raise NotImplementedError(msg)
