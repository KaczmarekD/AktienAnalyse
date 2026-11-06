"""Profil, Parameter und Perzentile je Bewertungslauf: web.ranking_profile, web.ranking_factor

Revision ID: 0016
Revises: 0015
Erstellt: 2026-11-06

Track G (G3, docs/architecture/ui-neugestaltung.md): Das UI nennt Gewichte, Schwellen und Faktoren
des Laufs und zeigt im Titel-Detail das Perzentil je Faktor. Nur additiv: zwei neue Tabellen statt
neuer Spalten, denn ``web.ranking_run`` und ``web.ranking_row`` sind nur zum Anfuegen, und der
Backfill kann neue Tabellen fuer die Historie ganz fuellen. Schreiben darf ``va_web``, lesen auch
``va_read``.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from va_platform.db.ddl import protect_table, web_grant_statements

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ranking_profile",
        sa.Column("scoring_run_id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("profile_id", sa.BigInteger(), nullable=True),
        sa.Column("profile_version", sa.BigInteger(), nullable=True),
        sa.Column("profile_name", sa.Text(), nullable=True),
        sa.Column("params", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("scoring_run_id", name=op.f("pk_ranking_profile")),
        schema="web",
    )
    op.create_table(
        "ranking_factor",
        sa.Column("scoring_run_id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("symbol", sa.Text(), nullable=False),
        sa.Column("ranks", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("scoring_run_id", "symbol", name=op.f("pk_ranking_factor")),
        schema="web",
    )
    op.create_index(
        op.f("ix_ranking_factor_symbol"), "ranking_factor", ["symbol"], unique=False, schema="web"
    )
    for table in ("web.ranking_profile", "web.ranking_factor"):
        for statement in protect_table(table):
            op.execute(statement)
    op.execute(web_grant_statements())  # die neuen Tabellen fuer va_web und va_read


def downgrade() -> None:
    msg = "Downgrades wuerden Daten loeschen und sind nicht vorgesehen"
    raise NotImplementedError(msg)
