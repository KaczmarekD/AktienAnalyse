"""Schema market_data: Abdeckung (D2.2)

- ``coverage_version``: eine Fassung der Abdeckung, gueltig ist die juengste
- ``coverage_item``: die Wertpapiere einer Fassung (ISIN, Anlageklasse, Symbole), ohne Nutzer
- ``fundamental_snapshot.role``: ``universe`` (Standard, im Ranking) oder ``coverage``

Alle nur zum Anfuegen. Bestehende Snapshots bekommen ``universe``. Die neue Spalte steht unter dem
UPDATE-Schutz der Tabelle wie alle anderen.

Revision ID: 0019
Revises: 0018
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from va_platform.db.ddl import grant_statements, protect_table

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "market_data"
ASSET_CLASSES = ("equity", "etf", "bond", "other")
ROLES = ("universe", "coverage")
TABLES = ("coverage_version", "coverage_item")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def _id() -> sa.Column:
    return sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False)


def upgrade() -> None:
    op.add_column(
        "fundamental_snapshot",
        sa.Column("role", sa.Text(), server_default=sa.text("'universe'"), nullable=False),
        schema=SCHEMA,
    )
    op.create_check_constraint(
        op.f("ck_fundamental_snapshot_role"),
        "fundamental_snapshot",
        _in("role", ROLES),
        schema=SCHEMA,
    )
    op.create_table(
        "coverage_version",
        _id(),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_coverage_version")),
        schema=SCHEMA,
    )
    op.create_table(
        "coverage_item",
        _id(),
        sa.Column("version_id", sa.BigInteger(), nullable=False),
        sa.Column("isin", sa.Text(), nullable=False),
        sa.Column("asset_class", sa.Text(), nullable=False),
        sa.Column("fundamentals_symbol", sa.Text(), nullable=True),
        sa.Column("price_symbol", sa.Text(), nullable=True),
        sa.Column("name", sa.Text(), nullable=True),
        sa.CheckConstraint(
            _in("asset_class", ASSET_CLASSES), name=op.f("ck_coverage_item_asset_class")
        ),
        sa.ForeignKeyConstraint(
            ["version_id"],
            [f"{SCHEMA}.coverage_version.id"],
            name=op.f("fk_coverage_item_version_id_coverage_version"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_coverage_item")),
        sa.UniqueConstraint("version_id", "isin", name=op.f("uq_coverage_item_version_id_isin")),
        schema=SCHEMA,
    )
    for table in TABLES:
        for statement in protect_table(f"{SCHEMA}.{table}"):
            op.execute(statement)
    op.execute(grant_statements((SCHEMA,)))


def downgrade() -> None:
    msg = "Downgrades wuerden Daten loeschen und sind nicht vorgesehen"
    raise NotImplementedError(msg)
