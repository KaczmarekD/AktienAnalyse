"""Schema portfolio: Kopie der Scores fuer die Depots (D4.2)

- ``score_view``: Ranking-Zeilen und Einordnungen mit ISIN aus ``scoring.run.completed``; gueltig
  ist je ISIN der juengste Bewertungslauf. ``scoring_run_id`` nur als Verweis (anderes Schema).

Nur additiv, nur zum Anfuegen (``protect_table``). Keine persoenlichen Daten, aber im Schema
``portfolio``: Lesen und anfuegen darf nur ``va_portfolio`` (``portfolio_grant_statements``
erneut, die Rechte gelten je Tabelle).

Revision ID: 0028
Revises: 0027
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from va_platform.db.ddl import portfolio_grant_statements, protect_table

revision: str = "0028"
down_revision: str | None = "0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "portfolio"


def upgrade() -> None:
    op.create_table(
        "score_view",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("isin", sa.Text(), nullable=False),
        sa.Column("scoring_run_id", sa.BigInteger(), nullable=False),
        sa.Column("as_of", sa.Date(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_score_view")),
        schema=SCHEMA,
    )
    op.create_index(
        op.f("ix_score_view_isin_scoring_run_id"),
        "score_view",
        ["isin", "scoring_run_id"],
        unique=False,
        schema=SCHEMA,
    )
    for statement in protect_table(f"{SCHEMA}.score_view"):
        op.execute(statement)
    op.execute(portfolio_grant_statements())


def downgrade() -> None:
    msg = "Downgrades wuerden Daten loeschen und sind nicht vorgesehen"
    raise NotImplementedError(msg)
