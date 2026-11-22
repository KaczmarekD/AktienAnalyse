"""Netto-Emission (F2.2, ADR-0011): Veraenderung der Aktienanzahl in 12 Monaten

Eine Spalte in ``market_data.fundamental_snapshot`` und in der Projektion ``web.snapshot_row``.
Nur additiv: Bestehende Zeilen bleiben ohne Wert (NULL), neue Abrufe fuellen sie. Die Spalte
steht unter dem UPDATE-Schutz ihrer Tabelle wie alle anderen.

Revision ID: 0024
Revises: 0023
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0024"
down_revision: str | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = (("market_data", "fundamental_snapshot"), ("web", "snapshot_row"))


def upgrade() -> None:
    for schema, table in TABLES:
        op.add_column(
            table, sa.Column("net_share_issuance", sa.Float(), nullable=True), schema=schema
        )


def downgrade() -> None:
    for schema, table in TABLES:
        op.drop_column(table, "net_share_issuance", schema=schema)
