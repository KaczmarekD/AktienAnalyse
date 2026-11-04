"""Lesemodelle des web-api: web.snapshot_row, web.ranking_run (Paket P4.9)

Revision ID: 0012
Revises: 0011
Erstellt: 2026-11-04

Nur additiv. Beide Tabellen sind nur zum Anfuegen und werden aus den Events gefuellt
(``marketdata.snapshot.completed``, ``scoring.run.completed``), die Historie fuellt
``src.db.backfill`` aus den Tabellen nach. Dazu ein Index auf ``web.ranking_row.symbol`` fuer den
Score-Verlauf eines Titels. Schreiben darf ``va_web``, lesen auch ``va_read``.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from va_platform.db.ddl import protect_table, web_grant_statements

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ORIGINS = ("live", "rescore", "import")
METRICS = (
    "price",
    "market_cap",
    "ev_ebit",
    "pe_ratio",
    "pb_ratio",
    "p_fcf",
    "dividend_yield",
    "shareholder_yield",
    "roic",
    "fcf_margin",
    "operating_margin",
    "net_debt_ebitda",
    "earnings_stability",
    "revenue_growth_5y",
    "eps_growth_5y",
)


def _now() -> sa.TextClause:
    return sa.text("now()")


def upgrade() -> None:
    op.create_table(
        "snapshot_row",
        sa.Column("fetch_run_id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("symbol", sa.Text(), nullable=False),
        sa.Column("fetched_on", sa.Date(), nullable=False),
        sa.Column("fetch_ok", sa.Boolean(), nullable=False),
        sa.Column("isin", sa.Text(), nullable=True),
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column("index_name", sa.Text(), nullable=True),
        sa.Column("sector", sa.Text(), nullable=True),
        sa.Column("industry", sa.Text(), nullable=True),
        sa.Column("currency", sa.Text(), nullable=True),
        *(sa.Column(name, sa.Double(), nullable=True) for name in METRICS),
        sa.Column(
            "errors",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_now(), nullable=False),
        sa.PrimaryKeyConstraint("fetch_run_id", "symbol", name=op.f("pk_snapshot_row")),
        schema="web",
    )
    op.create_index(
        op.f("ix_snapshot_row_symbol"), "snapshot_row", ["symbol"], unique=False, schema="web"
    )
    op.create_table(
        "ranking_run",
        sa.Column("scoring_run_id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("run_id", sa.BigInteger(), nullable=True),
        sa.Column("fetch_run_id", sa.BigInteger(), nullable=True),
        sa.Column("origin", sa.Text(), nullable=False),
        sa.Column("as_of", sa.Date(), nullable=True),
        sa.Column("universe_source", sa.Text(), nullable=True),
        sa.Column("value_weight", sa.Double(), nullable=True),
        sa.Column("quality_weight", sa.Double(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "origin IN (" + ", ".join(repr(o) for o in ORIGINS) + ")",
            name=op.f("ck_ranking_run_origin"),
        ),
        sa.PrimaryKeyConstraint("scoring_run_id", name=op.f("pk_ranking_run")),
        schema="web",
    )
    op.create_index(
        op.f("ix_ranking_row_symbol"), "ranking_row", ["symbol"], unique=False, schema="web"
    )
    for table in ("web.snapshot_row", "web.ranking_run"):
        for statement in protect_table(table):
            op.execute(statement)
    op.execute(web_grant_statements())  # die neuen Tabellen fuer va_web und va_read


def downgrade() -> None:
    msg = "Downgrades wuerden Daten loeschen und sind nicht vorgesehen"
    raise NotImplementedError(msg)
