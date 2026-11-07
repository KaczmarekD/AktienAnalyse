"""Schema identity: Mail-Adresse bestaetigen, Protokoll des Loeschkommandos (D1.6)

- ``email_confirmation``: Anfrage mit dem SHA-256 des Tokens aus dem Link, gilt 24 h
- ``email_confirmation_used``: der Link wurde benutzt (einmalig, das Token ist der Schluessel)
- ``erasure_log``: das Loeschkommando lief, ohne Inhalte (Hash der Nutzer-ID, wer, wie viele Zeilen)

Alle nur zum Anfuegen, wie das ganze Schema.

Revision ID: 0017
Revises: 0016
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from va_platform.db.ddl import identity_grant_statements, protect_table

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "identity"
TABLES = ("email_confirmation", "email_confirmation_used", "erasure_log")


def _now() -> sa.TextClause:
    return sa.text("now()")


def _id() -> sa.Column:
    return sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False)


def upgrade() -> None:
    op.create_table(
        "email_confirmation",
        _id(),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            [f"{SCHEMA}.user_account.id"],
            name=op.f("fk_email_confirmation_user_id_user_account"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_email_confirmation")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_email_confirmation_token_hash")),
        schema=SCHEMA,
    )
    op.create_index(
        op.f("ix_email_confirmation_user_id"),
        "email_confirmation",
        ["user_id"],
        unique=False,
        schema=SCHEMA,
    )
    op.create_table(
        "email_confirmation_used",
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), server_default=_now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["token_hash"],
            [f"{SCHEMA}.email_confirmation.token_hash"],
            name=op.f("fk_email_confirmation_used_token_hash_email_confirmation"),
        ),
        sa.PrimaryKeyConstraint("token_hash", name=op.f("pk_email_confirmation_used")),
        schema=SCHEMA,
    )
    op.create_table(
        "erasure_log",
        _id(),
        sa.Column("user_key", sa.Text(), nullable=False),
        sa.Column("by_admin", sa.Text(), nullable=False),
        sa.Column("rows", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), server_default=_now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_erasure_log")),
        schema=SCHEMA,
    )
    for table in TABLES:
        for statement in protect_table(f"{SCHEMA}.{table}"):
            op.execute(statement)
    op.execute(identity_grant_statements())


def downgrade() -> None:
    msg = "Downgrades wuerden Daten loeschen und sind nicht vorgesehen"
    raise NotImplementedError(msg)
