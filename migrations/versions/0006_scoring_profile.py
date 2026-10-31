"""Scoring-Profile versioniert (ADR-0009, Paket P2b.1)

Revision ID: 0006
Revises: 0005
Erstellt: 2026-10-31

Nur additiv. Alle drei Tabellen sind nur zum Anfuegen da: Speichern legt eine neue Version an,
Aktivieren eine neue Aktivierung (aktiv ist die juengste). Das Profil "Standard" legt der
Batch beim Start aus den ENV-Werten an, nicht die Migration.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from va_platform.db.ddl import grant_statements, protect_table

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = ("scoring.profile", "scoring.profile_version", "scoring.profile_activation")


def upgrade() -> None:
    op.create_table(
        "profile",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_profile")),
        sa.UniqueConstraint("name", name=op.f("uq_profile_name")),
        schema="scoring",
    )
    op.create_table(
        "profile_version",
        sa.Column("profile_id", sa.BigInteger(), nullable=False),
        sa.Column("version", sa.BigInteger(), nullable=False),
        sa.Column("params", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("parent_version", sa.BigInteger(), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "parent_version < version", name=op.f("ck_profile_version_parent_version")
        ),
        sa.CheckConstraint("version >= 1", name=op.f("ck_profile_version_version")),
        sa.ForeignKeyConstraint(
            ["profile_id", "parent_version"],
            ["scoring.profile_version.profile_id", "scoring.profile_version.version"],
            name=op.f("fk_profile_version_profile_id_profile_version"),
        ),
        sa.ForeignKeyConstraint(
            ["profile_id"],
            ["scoring.profile.id"],
            name=op.f("fk_profile_version_profile_id_profile"),
        ),
        sa.PrimaryKeyConstraint("profile_id", "version", name=op.f("pk_profile_version")),
        schema="scoring",
    )
    op.create_table(
        "profile_activation",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("profile_id", sa.BigInteger(), nullable=False),
        sa.Column("version", sa.BigInteger(), nullable=False),
        sa.Column(
            "activated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["profile_id", "version"],
            ["scoring.profile_version.profile_id", "scoring.profile_version.version"],
            name=op.f("fk_profile_activation_profile_id_profile_version"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_profile_activation")),
        schema="scoring",
    )
    # Niemals loeschen/ueberschreiben, Rechte wie bei den uebrigen Tabellen von scoring
    for table in TABLES:
        for statement in protect_table(table):
            op.execute(statement)
    op.execute(grant_statements(("scoring",)))


def downgrade() -> None:
    msg = "Downgrades wuerden Daten loeschen und sind nicht vorgesehen"
    raise NotImplementedError(msg)
