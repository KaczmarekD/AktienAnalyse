"""Historie der Aktienanzahl je Tag (ADR-0010, Paket F1.3)

Revision ID: 0003
Revises: 0002
Erstellt: 2026-10-19

Nur additiv. Versioniert wie ``statement_value``: neue Zeile nur fuer einen neuen
Tag oder einen geaenderten Wert.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from va_platform.db.ddl import grant_statements, protect_table

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "market_data.share_count"


def upgrade() -> None:
    op.create_table(
        "share_count",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("instrument_id", sa.BigInteger(), nullable=False),
        sa.Column("as_of", sa.Date(), nullable=False),
        sa.Column("shares", sa.BigInteger(), nullable=False),
        sa.Column("first_seen_fetch_run_id", sa.BigInteger(), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("shares > 0", name=op.f("ck_share_count_shares")),
        sa.ForeignKeyConstraint(
            ["first_seen_fetch_run_id"],
            ["market_data.fetch_run.id"],
            name=op.f("fk_share_count_first_seen_fetch_run_id_fetch_run"),
        ),
        sa.ForeignKeyConstraint(
            ["instrument_id"],
            ["market_data.instrument.id"],
            name=op.f("fk_share_count_instrument_id_instrument"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_share_count")),
        schema="market_data",
    )
    op.create_index(
        "ix_share_count_key",
        "share_count",
        ["instrument_id", "as_of", "first_seen_at"],
        unique=False,
        schema="market_data",
    )

    # Niemals loeschen/ueberschreiben, Rechte wie bei den Tabellen aus 0001
    for statement in protect_table(TABLE):
        op.execute(statement)
    op.execute(grant_statements(("market_data",)))


def downgrade() -> None:
    msg = "Downgrades wuerden Daten loeschen und sind nicht vorgesehen"
    raise NotImplementedError(msg)
