"""Fundamentale Anker im Titel-Detail: web.ranking_anchor (F3.2a)

Revision ID: 0030
Revises: 0029

Die Projektion der Anker aus ``scoring.run.completed`` (``RankingRowV1.anchors``), je
Bewertungslauf und Titel als JSON wie ``web.ranking_factor``. Nur additiv, nur zum Anfuegen; der
Backfill fuellt sie aus ``scoring.anchor_value``. Schreiben darf ``va_web``, lesen auch
``va_read``.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from va_platform.db.ddl import protect_table, web_grant_statements

revision: str = "0030"
down_revision: str | None = "0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ranking_anchor",
        sa.Column("scoring_run_id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("symbol", sa.Text(), nullable=False),
        sa.Column("anchors", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("scoring_run_id", "symbol", name=op.f("pk_ranking_anchor")),
        schema="web",
    )
    op.create_index(
        op.f("ix_ranking_anchor_symbol"), "ranking_anchor", ["symbol"], unique=False, schema="web"
    )
    for statement in protect_table("web.ranking_anchor"):
        op.execute(statement)
    op.execute(web_grant_statements())


def downgrade() -> None:
    msg = "Downgrades wuerden Daten loeschen und sind nicht vorgesehen"
    raise NotImplementedError(msg)
