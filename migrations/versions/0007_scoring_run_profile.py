"""Profil-Version im Bewertungslauf (ADR-0009, Paket P2b.3)

Revision ID: 0007
Revises: 0006
Erstellt: 2026-10-31

Nur additiv: zwei leere Spalten. Alte Laeufe, Import und Replay bleiben ohne Profil. Kein
UPDATE noetig, der Schutz von ``scoring_run`` gegen Aenderungen bleibt.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "scoring_run", sa.Column("profile_id", sa.BigInteger(), nullable=True), schema="scoring"
    )
    op.add_column(
        "scoring_run",
        sa.Column("profile_version", sa.BigInteger(), nullable=True),
        schema="scoring",
    )
    op.create_foreign_key(
        op.f("fk_scoring_run_profile_id_profile_version"),
        "scoring_run",
        "profile_version",
        ["profile_id", "profile_version"],
        ["profile_id", "version"],
        source_schema="scoring",
        referent_schema="scoring",
    )
    # Profil und Version nur zusammen (Alembic erkennt CHECK-Constraints nicht selbst)
    op.create_check_constraint(
        op.f("ck_scoring_run_profile"),
        "scoring_run",
        "(profile_id IS NULL) = (profile_version IS NULL)",
        schema="scoring",
    )


def downgrade() -> None:
    msg = "Downgrades wuerden Daten loeschen und sind nicht vorgesehen"
    raise NotImplementedError(msg)
