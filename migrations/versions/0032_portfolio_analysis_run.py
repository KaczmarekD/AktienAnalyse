"""Schema portfolio: Laeufe der Analyse und ihre Hinweise (D5.2)

- ``analysis_run``: je Lauf Depot, Depotstand, Ausloeser, Fingerabdruck und das ganze
  ``DepotAnalysisV1`` (JSONB); nur angefuegt, wenn sich das Ergebnis aendert.
- ``hint``: je Lauf die Hinweise mit Schwere, Status (neu, besteht, erledigt), Messwert, Schwelle
  und Datenstand.

Nur additiv, nur zum Anfuegen (``protect_table``). Persoenliche Daten: nur ``va_portfolio``
(``portfolio_grant_statements``); ``src.erase_user`` loescht sie mit dem Depot.

Revision ID: 0032
Revises: 0031
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from va_platform.db.ddl import portfolio_grant_statements, protect_table

revision: str = "0032"
down_revision: str | None = "0031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "portfolio"
TRIGGERS = ("holdings", "prices", "scores", "securities", "request")


def upgrade() -> None:
    triggers = ", ".join(f"'{t}'" for t in TRIGGERS)
    op.create_table(
        "analysis_run",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("depot_id", sa.BigInteger(), nullable=False),
        sa.Column("snapshot_version", sa.BigInteger(), nullable=False),
        sa.Column("trigger", sa.Text(), nullable=False),
        sa.Column("fingerprint", sa.Text(), nullable=False),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(f"trigger IN ({triggers})", name=op.f("ck_analysis_run_trigger")),
        sa.ForeignKeyConstraint(
            ["depot_id"], [f"{SCHEMA}.depot.id"], name=op.f("fk_analysis_run_depot_id_depot")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_analysis_run")),
        schema=SCHEMA,
    )
    op.create_index(
        op.f("ix_analysis_run_depot_id"), "analysis_run", ["depot_id"], unique=False, schema=SCHEMA
    )
    op.create_table(
        "hint",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("analysis_run_id", sa.BigInteger(), nullable=False),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("rule", sa.Text(), nullable=False),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("severity", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("measured", sa.Double(), nullable=True),
        sa.Column("threshold", sa.Double(), nullable=True),
        sa.Column("as_of", sa.Date(), nullable=True),
        sa.CheckConstraint(
            "severity IN ('info', 'warning', 'critical')", name=op.f("ck_hint_severity")
        ),
        sa.CheckConstraint(
            "status IN ('new', 'existing', 'resolved')", name=op.f("ck_hint_status")
        ),
        sa.ForeignKeyConstraint(
            ["analysis_run_id"],
            [f"{SCHEMA}.analysis_run.id"],
            name=op.f("fk_hint_analysis_run_id_analysis_run"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_hint")),
        schema=SCHEMA,
    )
    op.create_index(
        op.f("ix_hint_analysis_run_id"), "hint", ["analysis_run_id"], unique=False, schema=SCHEMA
    )
    for table in ("analysis_run", "hint"):
        for statement in protect_table(f"{SCHEMA}.{table}"):
            op.execute(statement)
    op.execute(portfolio_grant_statements())


def downgrade() -> None:
    msg = "Downgrades wuerden Daten loeschen und sind nicht vorgesehen"
    raise NotImplementedError(msg)
