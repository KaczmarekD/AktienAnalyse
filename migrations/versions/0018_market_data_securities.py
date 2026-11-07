"""Schema market_data: Wertpapiere ueber die ISIN (D2.1)

- ``security``: ein Eintrag je ISIN mit Anlageklasse
- ``security_master``: Stammdaten je Quelle (JSONB), neue Zeile nur bei geaendertem Inhalt
- ``listing``: weitere Listings neben ``instrument`` (Symbol eindeutig, falls vorhanden)

Alle nur zum Anfuegen. ``va_app`` und ``va_read`` bekommen ihre Rechte wie bei 0002 bis 0004,
``va_market_data`` ueber die Standardrechte des Schemas (``service_grant_statements``). Die
Tabellen verraten, welche Titel jemand haelt, aber nicht wer (depot/README.md).

Revision ID: 0018
Revises: 0017
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from va_platform.db.ddl import grant_statements, protect_table

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "market_data"
ASSET_CLASSES = ("equity", "etf", "bond", "other")
TABLES = ("security", "security_master", "listing")


def _now() -> sa.TextClause:
    return sa.text("now()")


def _id() -> sa.Column:
    return sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False)


def upgrade() -> None:
    op.create_table(
        "security",
        _id(),
        sa.Column("isin", sa.Text(), nullable=False),
        sa.Column("asset_class", sa.Text(), nullable=False),
        sa.Column(
            "first_seen_at", sa.DateTime(timezone=True), server_default=_now(), nullable=False
        ),
        sa.CheckConstraint(
            "asset_class IN (" + ", ".join(repr(v) for v in ASSET_CLASSES) + ")",
            name=op.f("ck_security_asset_class"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_security")),
        sa.UniqueConstraint("isin", name=op.f("uq_security_isin")),
        schema=SCHEMA,
    )
    op.create_table(
        "security_master",
        _id(),
        sa.Column("isin", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["isin"],
            [f"{SCHEMA}.security.isin"],
            name=op.f("fk_security_master_isin_security"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_security_master")),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_security_master_isin_source",
        "security_master",
        ["isin", "source"],
        unique=False,
        schema=SCHEMA,
    )
    op.create_table(
        "listing",
        _id(),
        sa.Column("isin", sa.Text(), nullable=False),
        sa.Column("symbol", sa.Text(), nullable=True),
        sa.Column("ticker", sa.Text(), nullable=True),
        sa.Column("exchange", sa.Text(), nullable=True),
        sa.Column("currency", sa.Text(), nullable=True),
        sa.Column(
            "first_seen_at", sa.DateTime(timezone=True), server_default=_now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["isin"], [f"{SCHEMA}.security.isin"], name=op.f("fk_listing_isin_security")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_listing")),
        sa.UniqueConstraint("symbol", name=op.f("uq_listing_symbol")),
        sa.UniqueConstraint(
            "isin", "ticker", "exchange", name=op.f("uq_listing_isin_ticker_exchange")
        ),
        schema=SCHEMA,
    )
    op.create_index(op.f("ix_listing_isin"), "listing", ["isin"], unique=False, schema=SCHEMA)
    for table in TABLES:
        for statement in protect_table(f"{SCHEMA}.{table}"):
            op.execute(statement)
    op.execute(grant_statements((SCHEMA,)))


def downgrade() -> None:
    msg = "Downgrades wuerden Daten loeschen und sind nicht vorgesehen"
    raise NotImplementedError(msg)
