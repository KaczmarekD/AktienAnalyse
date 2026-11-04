"""Eingangsdaten der Bewertung: scoring.input_snapshot (Paket P5.1a)

Revision ID: 0013
Revises: 0012
Erstellt: 2026-11-04

Nur additiv, nur zum Anfuegen. scoring speichert beim Bewerten die flachen Zeilen des Abrufs und
rechnet die Vorschau daraus, ohne ``market_data`` zu lesen (Voraussetzung fuer ein Image und eine
Rolle je Service). Aeltere Laeufe fuellt ``src.db.backfill`` nach.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from va_platform.db.ddl import grant_statements, protect_table

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "input_snapshot",
        sa.Column("fetch_run_id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("symbol", sa.Text(), nullable=False),
        sa.Column("row", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("fetch_run_id", "symbol", name=op.f("pk_input_snapshot")),
        schema="scoring",
    )
    for statement in protect_table("scoring.input_snapshot"):
        op.execute(statement)
    op.execute(grant_statements(("scoring",)))


def downgrade() -> None:
    msg = "Downgrades wuerden Daten loeschen und sind nicht vorgesehen"
    raise NotImplementedError(msg)
