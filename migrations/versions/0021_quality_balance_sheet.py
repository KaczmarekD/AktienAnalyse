"""Bilanzqualitaet (F2.1, ADR-0011): F-Score, Accruals, CFO/Bilanzsumme

Je drei Spalten in ``market_data.fundamental_snapshot`` und in der Projektion
``web.snapshot_row``. Nur additiv: Bestehende Zeilen bleiben ohne Werte (NULL), neue Abrufe
fuellen sie. Die Spalten stehen unter dem UPDATE-Schutz ihrer Tabellen wie alle anderen.

Revision ID: 0021
Revises: 0020
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = (("market_data", "fundamental_snapshot"), ("web", "snapshot_row"))


def upgrade() -> None:
    for schema, table in TABLES:
        op.add_column(table, sa.Column("f_score", sa.SmallInteger(), nullable=True), schema=schema)
        op.add_column(
            table, sa.Column("operating_accruals", sa.Float(), nullable=True), schema=schema
        )
        op.add_column(table, sa.Column("cfo_assets", sa.Float(), nullable=True), schema=schema)


def downgrade() -> None:
    for schema, table in TABLES:
        for column in ("cfo_assets", "operating_accruals", "f_score"):
            op.drop_column(table, column, schema=schema)
