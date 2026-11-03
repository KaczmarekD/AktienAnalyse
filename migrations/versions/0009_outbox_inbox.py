"""Outbox und Inbox in jedem Schema (Paket P4.2)

Revision ID: 0009
Revises: 0008
Erstellt: 2026-11-01

Nur additiv. Jeder spaetere Service sendet ueber die Outbox seines Schemas und empfaengt ueber
dessen Inbox (docs/architecture/events.md). Die Inbox ist nur zum Anfuegen da. Die Outbox ist
die einzige Tabelle, deren Zeilen sich spaeter noch aendern: ``published_at`` wird einmal
gesetzt (Trigger ``va_guard_outbox``), ``va_app`` bekommt nur dafuer ein Spaltenrecht.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from va_platform.db.ddl import grant_statements, outbox_grant_statements, protect_table

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Die Schemas zum Stand dieser Migration, nicht va_platform.db.ddl.SCHEMAS
SCHEMAS = ("batch", "market_data", "scoring", "reporting")

# Ausgeschrieben wie in 0005: Eine Migration beschreibt den Stand ihres Datums.
# Die Outbox darf published_at einmal setzen, sonst nichts.
# Verglichen wird die ganze Zeile ohne published_at, das deckt auch spaetere Spalten ab.
GUARD_OUTBOX = r"""
CREATE OR REPLACE FUNCTION public.va_guard_outbox() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.published_at IS NOT NULL THEN
        RAISE EXCEPTION '%.% %: das Event ist bereits veroeffentlicht und unveraenderlich',
            TG_TABLE_SCHEMA, TG_TABLE_NAME, OLD.id
            USING ERRCODE = 'restrict_violation';
    END IF;
    IF NEW.published_at IS NULL THEN
        RAISE EXCEPTION '%.% %: ein UPDATE muss published_at setzen',
            TG_TABLE_SCHEMA, TG_TABLE_NAME, OLD.id
            USING ERRCODE = 'restrict_violation';
    END IF;
    IF (to_jsonb(NEW) - 'published_at') IS DISTINCT FROM (to_jsonb(OLD) - 'published_at') THEN
        RAISE EXCEPTION 'Auf %.% darf ein UPDATE nur published_at setzen',
            TG_TABLE_SCHEMA, TG_TABLE_NAME
            USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END
$$;
"""


def upgrade() -> None:
    op.execute(GUARD_OUTBOX)
    for schema in SCHEMAS:
        op.create_table(
            "outbox",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("subject", sa.Text(), nullable=False),
            sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
            sa.PrimaryKeyConstraint("id", name=op.f("pk_outbox")),
            schema=schema,
        )
        op.create_index(
            "ix_outbox_pending",
            "outbox",
            ["created_at"],
            unique=False,
            schema=schema,
            postgresql_where=sa.text("published_at IS NULL"),
        )
        op.create_table(
            "inbox",
            sa.Column("message_id", sa.Uuid(), nullable=False),
            sa.Column("consumer", sa.Text(), nullable=False),
            sa.Column(
                "processed_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.Column("error", sa.Text(), nullable=True),
            sa.PrimaryKeyConstraint("message_id", "consumer", name=op.f("pk_inbox")),
            schema=schema,
        )
        for table in (f"{schema}.outbox", f"{schema}.inbox"):
            for statement in protect_table(table):
                op.execute(statement)
    op.execute(grant_statements(SCHEMAS))
    op.execute(outbox_grant_statements(SCHEMAS))


def downgrade() -> None:
    msg = "Downgrades wuerden Daten loeschen und sind nicht vorgesehen"
    raise NotImplementedError(msg)
