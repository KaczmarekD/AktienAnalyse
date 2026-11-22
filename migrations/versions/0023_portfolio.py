"""Schema portfolio: Depots und Depotstaende des Dienstes portfolio (D3.1)

- ``depot``, ``depot_version`` (Name), ``depot_status`` (aktiv/archiviert)
- ``holding_snapshot`` (Depotstand je Version), ``holding_line``, ``cash_line``
- ``outbox``, ``inbox`` wie in jedem Schema

Nur additiv. Persoenliche Daten (ADR-0013): Lesen und anfuegen darf nur ``va_portfolio``
(``portfolio_grant_statements``); ``portfolio`` steht nicht in ``SCHEMAS`` von
``va_platform.db.ddl``, also bekommen ``va_read`` und ``va_app`` hier nichts. Die Rolle legen
``db/init/01_roles.sh`` (neue Datenbank) und ``python -m src.db.migrate`` (bestehende, mit
``VA_PORTFOLIO_PASSWORD``) an.

Revision ID: 0023
Revises: 0022
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from va_platform.db.ddl import portfolio_grant_statements, protect_table

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "portfolio"
KINDS = ("depot", "watchlist")
STATES = ("active", "archived")
UNITS = ("pieces", "nominal")
SOURCES = ("manual", "import", "bank")
TABLES = (
    "depot",
    "depot_version",
    "depot_status",
    "holding_snapshot",
    "holding_line",
    "cash_line",
    "inbox",
    "outbox",
)


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def _id() -> sa.Column:
    return sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False)


def _at(name: str) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=False)


def _fk(table: str, column: str, target: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        [column], [f"{SCHEMA}.{target}.id"], name=op.f(f"fk_{table}_{column}_{target}")
    )


def upgrade() -> None:
    op.execute(f"CREATE SCHEMA {SCHEMA}")
    op.create_table(
        "depot",
        _id(),
        sa.Column("owner_user_id", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        _at("created_at"),
        sa.CheckConstraint(_in("kind", KINDS), name=op.f("ck_depot_kind")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_depot")),
        schema=SCHEMA,
    )
    op.create_table(
        "depot_version",
        _id(),
        sa.Column("depot_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        _at("created_at"),
        _fk("depot_version", "depot_id", "depot"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_depot_version")),
        schema=SCHEMA,
    )
    op.create_table(
        "depot_status",
        _id(),
        sa.Column("depot_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        _at("at"),
        sa.CheckConstraint(_in("status", STATES), name=op.f("ck_depot_status_status")),
        _fk("depot_status", "depot_id", "depot"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_depot_status")),
        schema=SCHEMA,
    )
    op.create_table(
        "holding_snapshot",
        _id(),
        sa.Column("depot_id", sa.BigInteger(), nullable=False),
        sa.Column("version", sa.BigInteger(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("source_ref", sa.Text(), nullable=True),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        _at("created_at"),
        sa.CheckConstraint(_in("source", SOURCES), name=op.f("ck_holding_snapshot_source")),
        sa.CheckConstraint("version >= 1", name=op.f("ck_holding_snapshot_version")),
        _fk("holding_snapshot", "depot_id", "depot"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_holding_snapshot")),
        sa.UniqueConstraint(
            "depot_id", "version", name=op.f("uq_holding_snapshot_depot_id_version")
        ),
        schema=SCHEMA,
    )
    op.create_table(
        "holding_line",
        _id(),
        sa.Column("snapshot_id", sa.BigInteger(), nullable=False),
        sa.Column("position", sa.BigInteger(), nullable=False),
        sa.Column("isin", sa.Text(), nullable=False),
        sa.Column("quantity", sa.Numeric(), nullable=True),
        sa.Column("unit", sa.Text(), nullable=False),
        sa.Column("cost_basis_eur", sa.Numeric(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.CheckConstraint(_in("unit", UNITS), name=op.f("ck_holding_line_unit")),
        sa.CheckConstraint(
            "quantity IS NULL OR quantity > 0", name=op.f("ck_holding_line_quantity")
        ),
        _fk("holding_line", "snapshot_id", "holding_snapshot"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_holding_line")),
        sa.UniqueConstraint("snapshot_id", "isin", name=op.f("uq_holding_line_snapshot_id_isin")),
        schema=SCHEMA,
    )
    op.create_table(
        "cash_line",
        _id(),
        sa.Column("snapshot_id", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.Text(), nullable=False),
        sa.Column("amount", sa.Numeric(), nullable=False),
        _fk("cash_line", "snapshot_id", "holding_snapshot"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_cash_line")),
        schema=SCHEMA,
    )
    op.create_table(
        "inbox",
        sa.Column("message_id", sa.Uuid(), nullable=False),
        sa.Column("consumer", sa.Text(), nullable=False),
        sa.Column(
            "processed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("message_id", "consumer", name=op.f("pk_inbox")),
        schema=SCHEMA,
    )
    op.create_table(
        "outbox",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_outbox")),
        schema=SCHEMA,
    )
    for table, columns in (
        ("depot", ["owner_user_id"]),
        ("depot_version", ["depot_id"]),
        ("depot_status", ["depot_id"]),
    ):
        op.create_index(
            op.f(f"ix_{table}_{'_'.join(columns)}"), table, columns, unique=False, schema=SCHEMA
        )
    op.create_index(
        "ix_outbox_pending",
        "outbox",
        ["created_at"],
        unique=False,
        schema=SCHEMA,
        postgresql_where=sa.text("published_at IS NULL"),
    )
    for table in TABLES:
        for statement in protect_table(f"{SCHEMA}.{table}"):
            op.execute(statement)
    op.execute(portfolio_grant_statements())


def downgrade() -> None:
    msg = "Downgrades wuerden Daten loeschen und sind nicht vorgesehen"
    raise NotImplementedError(msg)
