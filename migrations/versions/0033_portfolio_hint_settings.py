"""Schema portfolio: Schwellen, Zielallokation und Kenntnisnahme der Hinweise (D5.3)

- ``hint_params``: Schwellen je Depot (``HintParamsV1``), versioniert, gueltig die juengste.
- ``target_allocation``: Zielallokation je Anlageklasse, versioniert, gueltig die juengste.
- ``hint_ack``: ein Hinweis zur Kenntnis genommen, mit Messwert, Schwere und juengstem Lauf in
  diesem Moment.
- ``analysis_run.trigger`` kennt dazu ``settings``.

Nur additiv, nur zum Anfuegen (``protect_table``). Persoenliche Daten: nur ``va_portfolio``;
``src.erase_user`` loescht sie mit dem Depot.

Revision ID: 0033
Revises: 0032
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from va_platform.db.ddl import portfolio_grant_statements, protect_table

revision: str = "0033"
down_revision: str | None = "0032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "portfolio"
TRIGGERS = ("holdings", "prices", "scores", "securities", "request", "settings")


def _versioned(table: str, column: str) -> None:
    op.create_table(
        table,
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("depot_id", sa.BigInteger(), nullable=False),
        sa.Column("version", sa.BigInteger(), nullable=False),
        sa.Column(column, postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_by", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["depot_id"], [f"{SCHEMA}.depot.id"], name=op.f(f"fk_{table}_depot_id_depot")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{table}")),
        sa.UniqueConstraint("depot_id", "version", name=op.f(f"uq_{table}_depot_id_version")),
        schema=SCHEMA,
    )


def upgrade() -> None:
    _versioned("hint_params", "params")
    _versioned("target_allocation", "shares")
    op.create_table(
        "hint_ack",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("depot_id", sa.BigInteger(), nullable=False),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("analysis_run_id", sa.BigInteger(), nullable=False),
        sa.Column("measured", sa.Double(), nullable=True),
        sa.Column("severity", sa.Text(), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "severity IN ('info', 'warning', 'critical')", name=op.f("ck_hint_ack_severity")
        ),
        sa.ForeignKeyConstraint(
            ["analysis_run_id"],
            [f"{SCHEMA}.analysis_run.id"],
            name=op.f("fk_hint_ack_analysis_run_id_analysis_run"),
        ),
        sa.ForeignKeyConstraint(
            ["depot_id"], [f"{SCHEMA}.depot.id"], name=op.f("fk_hint_ack_depot_id_depot")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_hint_ack")),
        schema=SCHEMA,
    )
    op.create_index(
        op.f("ix_hint_ack_depot_id_key"),
        "hint_ack",
        ["depot_id", "key"],
        unique=False,
        schema=SCHEMA,
    )
    # Ein Ausloeser mehr: die Pruefung um "settings" erweitert, keine Zeile aendert sich
    op.drop_constraint(op.f("ck_analysis_run_trigger"), "analysis_run", schema=SCHEMA)
    triggers = ", ".join(f"'{t}'" for t in TRIGGERS)
    op.create_check_constraint(
        op.f("ck_analysis_run_trigger"), "analysis_run", f"trigger IN ({triggers})", schema=SCHEMA
    )
    for table in ("hint_params", "target_allocation", "hint_ack"):
        for statement in protect_table(f"{SCHEMA}.{table}"):
            op.execute(statement)
    op.execute(portfolio_grant_statements())


def downgrade() -> None:
    msg = "Downgrades wuerden Daten loeschen und sind nicht vorgesehen"
    raise NotImplementedError(msg)
