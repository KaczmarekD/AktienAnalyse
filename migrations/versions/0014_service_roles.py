"""Rechte der Service-Rollen va_market_data, va_scoring, va_notification (Paket P5.3)

Revision ID: 0014
Revises: 0013
Erstellt: 2026-11-04

Keine Tabelle, nur Rechte: Jede Service-Rolle liest und fuegt nur im eigenen Schema an
(``va_platform.db.ddl.service_grant_statements``). Die Rollen selbst legen ``db/init/01_roles.sh``
(neue Datenbank) und ``python -m src.db.migrate`` (bestehende, mit ``VA_<SERVICE>_PASSWORD``) an;
fehlt eine, tut die Migration fuer sie nichts.
"""

from collections.abc import Sequence

from alembic import op

from va_platform.db.ddl import SERVICE_ROLES, service_grant_statements

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for role in SERVICE_ROLES:
        op.execute(service_grant_statements(role))


def downgrade() -> None:
    msg = "Downgrades sind nicht vorgesehen"
    raise NotImplementedError(msg)
