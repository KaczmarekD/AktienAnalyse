"""ETF-Zusammensetzungen (D2.4)

- ``market_data.etf_composition``: Stand eines Fonds bei einer Quelle (iShares, yfinance), je
  ISIN, Quelle und Stand einmal. Fondsdaten, Gewichte und alle bekannten Positionen als JSONB,
  die Positionen spaltenweise.

Nur zum Anfuegen. ``va_app`` und ``va_read`` bekommen ihre Rechte wie bei 0018,
``va_market_data`` ueber die Standardrechte des Schemas.

Revision ID: 0021
Revises: 0020
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from va_platform.db.ddl import grant_statements, protect_table

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "market_data"
TABLE = "etf_composition"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("isin", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("as_of", sa.Date(), nullable=False),
        sa.Column("complete", sa.Boolean(), nullable=False),
        sa.Column("holdings_count", sa.BigInteger(), nullable=False),
        sa.Column("facts", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("holdings", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("weights", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["isin"],
            [f"{SCHEMA}.security.isin"],
            name=op.f("fk_etf_composition_isin_security"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_etf_composition")),
        sa.UniqueConstraint(
            "isin", "source", "as_of", name=op.f("uq_etf_composition_isin_source_as_of")
        ),
        schema=SCHEMA,
    )
    for statement in protect_table(f"{SCHEMA}.{TABLE}"):
        op.execute(statement)
    op.execute(grant_statements((SCHEMA,)))


def downgrade() -> None:
    msg = "Downgrades wuerden Daten loeschen und sind nicht vorgesehen"
    raise NotImplementedError(msg)
