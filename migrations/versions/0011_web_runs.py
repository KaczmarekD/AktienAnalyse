"""Runs aus dem web-api: Tabelle web.run_request, Rechte von va_web auf batch.run (Paket P4.7)

Revision ID: 0011
Revises: 0010
Erstellt: 2026-11-04

Nur additiv. ``run_request`` ist nur zum Anfuegen und haelt die Runs fest, die das web-api
angelegt hat (Start aus dem UI, Scheduler). Der eindeutige ``slot`` sorgt dafuer, dass derselbe
Cron-Termin nur einen Run ergibt. ``va_web`` darf Runs in ``batch.run`` anlegen und einmal
abschliessen (``va_guard_finished``), sonst nichts im Schema ``batch``.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from va_platform.db.ddl import protect_table, web_grant_statements, web_run_grant_statements

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RUN_TRIGGERS = ("scheduled", "manual")


def upgrade() -> None:
    op.create_table(
        "run_request",
        sa.Column("run_id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("trigger", sa.Text(), nullable=False),
        sa.Column("slot", sa.DateTime(timezone=True), nullable=True),
        sa.Column("force_refresh", sa.Boolean(), nullable=False),
        sa.Column("dry_run", sa.Boolean(), nullable=False),
        sa.Column("notify", sa.Boolean(), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "trigger IN (" + ", ".join(repr(t) for t in RUN_TRIGGERS) + ")",
            name=op.f("ck_run_request_trigger"),
        ),
        sa.PrimaryKeyConstraint("run_id", name=op.f("pk_run_request")),
        sa.UniqueConstraint("slot", name=op.f("uq_run_request_slot")),
        schema="web",
    )
    for statement in protect_table("web.run_request"):
        op.execute(statement)
    op.execute(web_grant_statements())  # die neue Tabelle fuer va_web und va_read
    op.execute(web_run_grant_statements())


def downgrade() -> None:
    msg = "Downgrades wuerden Daten loeschen und sind nicht vorgesehen"
    raise NotImplementedError(msg)
