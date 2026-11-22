"""Momentum und Grund des Value-Trap-Flags (F2.3, ADR-0011, Punkt 5)

- ``momentum_12_1`` in ``market_data.fundamental_snapshot`` und in der Projektion
  ``web.snapshot_row``
- ``value_trap_reason`` ("quality" oder "momentum") in ``scoring.score_result`` und in der
  Projektion ``web.ranking_row``

Nur additiv: Bestehende Zeilen bleiben ohne Wert (NULL); ein Flag ohne Grund stammt von der
bisherigen Regel. Die Spalten stehen unter dem UPDATE-Schutz ihrer Tabellen wie alle anderen.

Revision ID: 0026
Revises: 0025
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0026"
down_revision: str | None = "0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

COLUMNS = (
    ("market_data", "fundamental_snapshot", "momentum_12_1", sa.Float()),
    ("web", "snapshot_row", "momentum_12_1", sa.Float()),
    ("scoring", "score_result", "value_trap_reason", sa.Text()),
    ("web", "ranking_row", "value_trap_reason", sa.Text()),
)


def upgrade() -> None:
    for schema, table, column, kind in COLUMNS:
        op.add_column(table, sa.Column(column, kind, nullable=True), schema=schema)


def downgrade() -> None:
    for schema, table, column, _kind in reversed(COLUMNS):
        op.drop_column(table, column, schema=schema)
