"""Kurshistorie je Handelstag (ADR-0010, Paket F1.4)

Revision ID: 0004
Revises: 0003
Erstellt: 2026-10-19

Nur additiv. Versioniert wie ``statement_value``: neue Zeile nur fuer einen neuen
Handelstag oder einen geaenderten Wert (Split, Korrektur, Dividendenanpassung).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from va_platform.db.ddl import grant_statements, protect_table

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "market_data.price_bar"


def upgrade() -> None:
    op.create_table(
        "price_bar",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("instrument_id", sa.BigInteger(), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("close", sa.Double(), nullable=False),
        sa.Column("adj_close", sa.Double(), nullable=True),
        sa.Column("dividend", sa.Double(), nullable=False),
        sa.Column("split", sa.Double(), nullable=False),
        sa.Column("first_seen_fetch_run_id", sa.BigInteger(), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("close > 0", name=op.f("ck_price_bar_close")),
        sa.CheckConstraint("dividend >= 0", name=op.f("ck_price_bar_dividend")),
        sa.CheckConstraint("split >= 0", name=op.f("ck_price_bar_split")),
        sa.ForeignKeyConstraint(
            ["first_seen_fetch_run_id"],
            ["market_data.fetch_run.id"],
            name=op.f("fk_price_bar_first_seen_fetch_run_id_fetch_run"),
        ),
        sa.ForeignKeyConstraint(
            ["instrument_id"],
            ["market_data.instrument.id"],
            name=op.f("fk_price_bar_instrument_id_instrument"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_price_bar")),
        schema="market_data",
    )
    op.create_index(
        "ix_price_bar_key",
        "price_bar",
        ["instrument_id", "trade_date", "first_seen_at"],
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
