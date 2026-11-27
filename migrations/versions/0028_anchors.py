"""Fundamentale Anker (F3.1, ADR-0011, Punkt 6)

- ``market_data.fundamental_snapshot.nopat_normalized``: mittlerer EBIT nach Steuern in
  Handelswaehrung, die Grundlage des Ertragskraftwerts
- ``scoring.anchor_value``: die Anker je Bewertungslauf und Titel im Long-Format

Nur additiv, nur zum Anfuegen. ``va_scoring`` bekommt seine Rechte ueber die Standardrechte des
Schemas.

Revision ID: 0028
Revises: 0027
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from va_platform.db.ddl import grant_statements, protect_table

revision: str = "0028"
down_revision: str | None = "0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "fundamental_snapshot",
        sa.Column("nopat_normalized", sa.Float(), nullable=True),
        schema="market_data",
    )
    op.create_table(
        "anchor_value",
        sa.Column("scoring_run_id", sa.BigInteger(), nullable=False),
        sa.Column("instrument_id", sa.BigInteger(), nullable=False),
        sa.Column("anchor", sa.Text(), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(
            ["scoring_run_id"],
            ["scoring.scoring_run.id"],
            name=op.f("fk_anchor_value_scoring_run_id_scoring_run"),
        ),
        sa.PrimaryKeyConstraint(
            "scoring_run_id", "instrument_id", "anchor", name=op.f("pk_anchor_value")
        ),
        schema="scoring",
    )
    for statement in protect_table("scoring.anchor_value"):
        op.execute(statement)
    op.execute(grant_statements(("scoring",)))


def downgrade() -> None:
    msg = "Downgrades wuerden Daten loeschen und sind nicht vorgesehen"
    raise NotImplementedError(msg)
