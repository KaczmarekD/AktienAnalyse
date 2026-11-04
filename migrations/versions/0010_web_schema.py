"""Schema web: Projektionen des web-api mit Inbox und Outbox (Paket P4.4)

Revision ID: 0010
Revises: 0009
Erstellt: 2026-11-04

Nur additiv. ``run_status`` ist eine Projektion und darf aktualisiert werden, geloescht wird
auch hier nie (``protect_table`` kennt sie als veraenderlich). ``ranking_row`` und die Inbox
sind nur zum Anfuegen, die Outbox setzt ``published_at`` einmal (Trigger aus ``0009``).
Schreiben darf die Rolle ``va_web``, lesen auch ``va_read``. Die Rolle selbst legen
``db/init/01_roles.sh`` (neue Datenbank) und ``python -m src.db.migrate`` (bestehende, mit
``VA_WEB_PASSWORD``) an.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from va_platform.db.ddl import protect_table, web_grant_statements

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RUN_STATES = ("requested", "fetched", "scored", "reported", "failed", "no_data")
TABLES = ("web.inbox", "web.outbox", "web.run_status", "web.ranking_row")


def _now() -> sa.TextClause:
    return sa.text("now()")


def upgrade() -> None:
    op.execute("CREATE SCHEMA web")
    op.create_table(
        "run_status",
        sa.Column("run_id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("trigger", sa.Text(), nullable=True),
        sa.Column("fetch_run_id", sa.BigInteger(), nullable=True),
        sa.Column("scoring_run_id", sa.BigInteger(), nullable=True),
        sa.Column("report_id", sa.BigInteger(), nullable=True),
        sa.Column("universe_size", sa.BigInteger(), nullable=True),
        sa.Column("scored_count", sa.BigInteger(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("last_event_type", sa.Text(), nullable=False),
        sa.Column("last_event_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=_now(), nullable=False),
        sa.CheckConstraint(
            "status IN (" + ", ".join(repr(s) for s in RUN_STATES) + ")",
            name=op.f("ck_run_status_status"),
        ),
        sa.PrimaryKeyConstraint("run_id", name=op.f("pk_run_status")),
        schema="web",
    )
    op.create_table(
        "ranking_row",
        sa.Column("scoring_run_id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("symbol", sa.Text(), nullable=False),
        sa.Column("run_id", sa.BigInteger(), nullable=True),
        sa.Column("as_of", sa.Date(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("index", sa.Text(), nullable=False),
        sa.Column("rank_overall", sa.BigInteger(), nullable=False),
        sa.Column("composite_score", sa.Double(), nullable=True),
        sa.Column("value_score", sa.Double(), nullable=True),
        sa.Column("quality_score", sa.Double(), nullable=True),
        sa.Column("value_trap", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_now(), nullable=False),
        sa.PrimaryKeyConstraint("scoring_run_id", "symbol", name=op.f("pk_ranking_row")),
        schema="web",
    )
    op.create_table(
        "inbox",
        sa.Column("message_id", sa.Uuid(), nullable=False),
        sa.Column("consumer", sa.Text(), nullable=False),
        sa.Column(
            "processed_at", sa.DateTime(timezone=True), server_default=_now(), nullable=False
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("message_id", "consumer", name=op.f("pk_inbox")),
        schema="web",
    )
    op.create_table(
        "outbox",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_now(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_outbox")),
        schema="web",
    )
    op.create_index(
        "ix_outbox_pending",
        "outbox",
        ["created_at"],
        unique=False,
        schema="web",
        postgresql_where=sa.text("published_at IS NULL"),
    )
    for table in TABLES:
        for statement in protect_table(table):
            op.execute(statement)
    op.execute(web_grant_statements())


def downgrade() -> None:
    msg = "Downgrades wuerden Daten loeschen und sind nicht vorgesehen"
    raise NotImplementedError(msg)
