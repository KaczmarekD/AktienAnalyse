"""Schema market_data: Kennzahlen neu abgedeckter Aktien, sofort geholt (D4.6)

- ``coverage_fetch``: je sofortigem Abruf und Aktie das ganze ``FundamentalsV1`` (JSONB), ISIN
  und Symbol. Ausserhalb eines Abrufs des Universums: ``fetch_run`` und ``fundamental_snapshot``
  bleiben dem Wochenlauf vorbehalten, ihn wiederverwendet sonst der naechste Lauf als Abruf
  des Tages.

Nur additiv, nur zum Anfuegen (``protect_table``). Ohne Nutzer und Mengen; Rechte wie im
uebrigen Schema ``market_data`` (``grant_statements``, die Rolle ``va_market_data`` ueber die
Standardrechte des Schemas).

Revision ID: 0031
Revises: 0030
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from va_platform.db.ddl import grant_statements, protect_table

revision: str = "0031"
down_revision: str | None = "0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "market_data"


def upgrade() -> None:
    op.create_table(
        "coverage_fetch",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("isin", sa.Text(), nullable=False),
        sa.Column("symbol", sa.Text(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_coverage_fetch")),
        schema=SCHEMA,
    )
    op.create_index(
        op.f("ix_coverage_fetch_isin_fetched_at"),
        "coverage_fetch",
        ["isin", "fetched_at"],
        unique=False,
        schema=SCHEMA,
    )
    for statement in protect_table(f"{SCHEMA}.coverage_fetch"):
        op.execute(statement)
    op.execute(grant_statements((SCHEMA,)))


def downgrade() -> None:
    msg = "Downgrades wuerden Daten loeschen und sind nicht vorgesehen"
    raise NotImplementedError(msg)
