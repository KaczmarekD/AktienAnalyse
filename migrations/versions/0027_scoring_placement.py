"""Schema scoring: Einordnung der Depot-Aktien ins Referenzuniversum (D4.1)

- ``placement``: je Bewertungslauf und eingeordneter Aktie Scores, Composite-Perzentil,
  Faktor-Ränge (JSONB), Value-Trap mit Grund, Branchenregel, „unter dem Größenfilter“ und der
  Grund ohne Composite. ISIN und Instrument nur als Verweis.

Nur additiv, nur zum Anfügen (``protect_table``). Ohne Nutzer und Mengen; die Rechte wie im
übrigen Schema ``scoring`` (``grant_statements``).

Revision ID: 0027
Revises: 0026
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from va_platform.db.ddl import grant_statements, protect_table

revision: str = "0027"
down_revision: str | None = "0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "scoring"


def upgrade() -> None:
    op.create_table(
        "placement",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("scoring_run_id", sa.BigInteger(), nullable=False),
        sa.Column("symbol", sa.Text(), nullable=False),
        sa.Column("isin", sa.Text(), nullable=True),
        sa.Column("instrument_id", sa.BigInteger(), nullable=True),
        sa.Column("value_score", sa.Double(), nullable=True),
        sa.Column("quality_score", sa.Double(), nullable=True),
        sa.Column("composite_score", sa.Double(), nullable=True),
        sa.Column("composite_percentile", sa.Double(), nullable=True),
        sa.Column("factor_ranks", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("value_trap_flag", sa.Boolean(), nullable=False),
        sa.Column("value_trap_reason", sa.Text(), nullable=True),
        sa.Column("industry_rule", sa.Boolean(), nullable=False),
        sa.Column("below_size_filter", sa.Boolean(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "reason IS NULL OR reason IN ('no_value', 'no_quality', 'no_data')",
            name=op.f("ck_placement_reason"),
        ),
        sa.ForeignKeyConstraint(
            ["scoring_run_id"],
            [f"{SCHEMA}.scoring_run.id"],
            name=op.f("fk_placement_scoring_run_id_scoring_run"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_placement")),
        schema=SCHEMA,
    )
    op.create_index(
        op.f("ix_placement_scoring_run_id"),
        "placement",
        ["scoring_run_id"],
        unique=False,
        schema=SCHEMA,
    )
    for statement in protect_table(f"{SCHEMA}.placement"):
        op.execute(statement)
    op.execute(grant_statements((SCHEMA,)))


def downgrade() -> None:
    msg = "Downgrades wuerden Daten loeschen und sind nicht vorgesehen"
    raise NotImplementedError(msg)
