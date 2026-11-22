"""Schema portfolio: Kopien der Marktdaten fuer die Bewertung der Depots (D3.4)

- ``security_view``: Stammdaten aus ``marketdata.securities.updated`` (ganzes ``SecurityV1``)
- ``price_view``: Schlusskurse aus ``marketdata.prices.completed``
- ``fx_view``: Waehrungskurse (1 Einheit in EUR) aus demselben Event

Nur additiv, nur zum Anfuegen (``protect_table``). Keine persoenlichen Daten, aber im Schema
``portfolio``: Lesen und anfuegen darf nur ``va_portfolio`` (``portfolio_grant_statements``
erneut, die Rechte gelten je Tabelle).

Revision ID: 0025
Revises: 0024
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from va_platform.db.ddl import portfolio_grant_statements, protect_table

revision: str = "0025"
down_revision: str | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "portfolio"
TABLES = ("security_view", "price_view", "fx_view")


def _id() -> sa.Column:
    return sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False)


def _received() -> sa.Column:
    return sa.Column("received_at", sa.DateTime(timezone=True), nullable=False)


def upgrade() -> None:
    op.create_table(
        "security_view",
        _id(),
        sa.Column("isin", sa.Text(), nullable=False),
        sa.Column("as_of", sa.Date(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("asset_class", sa.Text(), nullable=False),
        sa.Column("currency", sa.Text(), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        _received(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_security_view")),
        schema=SCHEMA,
    )
    op.create_table(
        "price_view",
        _id(),
        sa.Column("isin", sa.Text(), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("close", sa.Numeric(), nullable=False),
        sa.Column("currency", sa.Text(), nullable=False),
        sa.Column("percent_of_par", sa.Boolean(), nullable=False),
        sa.Column("source", sa.Text(), nullable=True),
        sa.Column("symbol", sa.Text(), nullable=True),
        _received(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_price_view")),
        schema=SCHEMA,
    )
    op.create_table(
        "fx_view",
        _id(),
        sa.Column("currency", sa.Text(), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("rate_to_eur", sa.Numeric(), nullable=False),
        _received(),
        sa.CheckConstraint("rate_to_eur > 0", name=op.f("ck_fx_view_rate_to_eur")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_fx_view")),
        schema=SCHEMA,
    )
    for table, columns in (
        ("security_view", ["isin", "as_of"]),
        ("price_view", ["isin", "trade_date"]),
        ("fx_view", ["currency", "trade_date"]),
    ):
        op.create_index(
            op.f(f"ix_{table}_{'_'.join(columns)}"), table, columns, unique=False, schema=SCHEMA
        )
    for table in TABLES:
        for statement in protect_table(f"{SCHEMA}.{table}"):
            op.execute(statement)
    op.execute(portfolio_grant_statements())


def downgrade() -> None:
    msg = "Downgrades wuerden Daten loeschen und sind nicht vorgesehen"
    raise NotImplementedError(msg)
