"""Rechte der Rolle va_profiles fuer die Profil-Befehle des web-api (Paket P3.3)

Revision ID: 0008
Revises: 0007
Erstellt: 2026-11-01

Nur Rechte, keine Tabellen. Die Rolle selbst legen ``db/init/01_roles.sh`` (neue Datenbank) und
``python -m src.db.migrate`` (bestehende Datenbank, mit ``VA_PROFILES_PASSWORD``) an; fehlt sie
hier noch, vergibt der Migrations-Schritt die Rechte danach selbst.
"""

from collections.abc import Sequence

from alembic import op

from va_platform.db.ddl import profiles_grant_statements

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(profiles_grant_statements())


def downgrade() -> None:
    msg = "Downgrades wuerden Daten loeschen und sind nicht vorgesehen"
    raise NotImplementedError(msg)
