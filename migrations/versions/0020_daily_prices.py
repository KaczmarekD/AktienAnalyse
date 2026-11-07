"""Tageskurse (D2.3)

- ``market_data.price_run``: ein Abruf der Tageskurse (nur angefuegt, ohne spaeteren Abschluss)
- ``market_data.daily_close``: Schlusskurs je ISIN, Quelle und Tag, einmal
- ``market_data.fx_daily``: Waehrungskurs nach EUR je Waehrung, Tag und Quelle, einmal
- ``web.price_request``: angestossene Termine des Schedulers im web-api, je Termin einmal

Revision ID: 0020
Revises: 0019
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from va_platform.db.ddl import grant_statements, protect_table, web_grant_statements

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STATUSES = ("ok", "failed")
TABLES = (
    "market_data.price_run",
    "market_data.daily_close",
    "market_data.fx_daily",
    "web.price_request",
)


def _id() -> sa.Column:
    return sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False)


def _at(name: str, *, default: bool = False) -> sa.Column:
    return sa.Column(
        name,
        sa.DateTime(timezone=True),
        server_default=sa.text("now()") if default else None,
        nullable=False,
    )


def upgrade() -> None:
    op.create_table(
        "price_run",
        _id(),
        sa.Column("source", sa.Text(), nullable=False),
        _at("started_at"),
        _at("finished_at"),
        sa.Column("status", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "status IN (" + ", ".join(repr(s) for s in STATUSES) + ")",
            name=op.f("ck_price_run_status"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_price_run")),
        schema="market_data",
    )
    op.create_table(
        "daily_close",
        _id(),
        sa.Column("isin", sa.Text(), nullable=False),
        sa.Column("symbol", sa.Text(), nullable=True),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("close", sa.Double(), nullable=False),
        sa.Column("currency", sa.Text(), nullable=False),
        sa.Column("quote_currency", sa.Text(), nullable=True),
        sa.Column("price_run_id", sa.BigInteger(), nullable=False),
        _at("first_seen_at", default=True),
        sa.ForeignKeyConstraint(
            ["price_run_id"],
            ["market_data.price_run.id"],
            name=op.f("fk_daily_close_price_run_id_price_run"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_daily_close")),
        sa.UniqueConstraint(
            "isin", "source", "trade_date", name=op.f("uq_daily_close_isin_source_trade_date")
        ),
        schema="market_data",
    )
    op.create_table(
        "fx_daily",
        _id(),
        sa.Column("currency", sa.Text(), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("rate_to_eur", sa.Double(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("price_run_id", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["price_run_id"],
            ["market_data.price_run.id"],
            name=op.f("fk_fx_daily_price_run_id_price_run"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_fx_daily")),
        sa.UniqueConstraint(
            "currency", "trade_date", "source", name=op.f("uq_fx_daily_currency_trade_date_source")
        ),
        schema="market_data",
    )
    op.create_table(
        "price_request",
        _at("slot"),
        sa.Column("trade_date", sa.Date(), nullable=False),
        _at("requested_at"),
        sa.PrimaryKeyConstraint("slot", name=op.f("pk_price_request")),
        schema="web",
    )
    for table in TABLES:
        for statement in protect_table(table):
            op.execute(statement)
    op.execute(grant_statements(("market_data",)))
    op.execute(web_grant_statements())


def downgrade() -> None:
    msg = "Downgrades wuerden Daten loeschen und sind nicht vorgesehen"
    raise NotImplementedError(msg)
