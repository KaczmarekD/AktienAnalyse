"""Konsens-Snapshots der Analysten je Abruf (ADR-0010, Paket F1.1)

Revision ID: 0002
Revises: 0001
Erstellt: 2026-09-30

Nur additiv. Die erlaubten Werte stehen hier bewusst fest und werden nicht aus
``src.consensus`` importiert: Eine Migration beschreibt den Stand ihres Datums.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from src.db.ddl import grant_statements, protect_table

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "market_data.consensus_snapshot"


def upgrade() -> None:
    op.create_table(
        "consensus_snapshot",
        sa.Column("fetch_run_id", sa.BigInteger(), nullable=False),
        sa.Column("instrument_id", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "kind IN ('eps_trend', 'eps_revisions', 'earnings_estimate', 'revenue_estimate', "
            "'growth_estimates', 'analyst_price_targets')",
            name=op.f("ck_consensus_snapshot_kind"),
        ),
        sa.CheckConstraint(
            "status IN ('ok', 'empty', 'error')", name=op.f("ck_consensus_snapshot_status")
        ),
        sa.CheckConstraint(
            "(status = 'ok') = (payload IS NOT NULL)",
            name=op.f("ck_consensus_snapshot_payload_only_if_ok"),
        ),
        sa.CheckConstraint(
            "(status = 'error') = (error IS NOT NULL)",
            name=op.f("ck_consensus_snapshot_error_only_if_error"),
        ),
        sa.ForeignKeyConstraint(
            ["fetch_run_id"],
            ["market_data.fetch_run.id"],
            name=op.f("fk_consensus_snapshot_fetch_run_id_fetch_run"),
        ),
        sa.ForeignKeyConstraint(
            ["instrument_id"],
            ["market_data.instrument.id"],
            name=op.f("fk_consensus_snapshot_instrument_id_instrument"),
        ),
        sa.PrimaryKeyConstraint(
            "fetch_run_id", "instrument_id", "kind", name=op.f("pk_consensus_snapshot")
        ),
        schema="market_data",
    )

    # Niemals loeschen/ueberschreiben, Rechte wie bei den Tabellen aus 0001
    for statement in protect_table(TABLE):
        op.execute(statement)
    op.execute(grant_statements(("market_data",)))


def downgrade() -> None:
    msg = "Downgrades wuerden Daten loeschen und sind nicht vorgesehen"
    raise NotImplementedError(msg)
