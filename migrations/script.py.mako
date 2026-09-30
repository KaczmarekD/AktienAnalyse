"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Erstellt: ${create_date}

Nur additiv: keine Tabelle/Spalte mit Daten entfernen. Neue Tabellen mit
``protect_table()`` aus ``src.db.ddl`` schuetzen.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
${imports if imports else ""}

revision: str = ${repr(up_revision)}
down_revision: str | None = ${repr(down_revision)}
branch_labels: str | Sequence[str] | None = ${repr(branch_labels)}
depends_on: str | Sequence[str] | None = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    msg = "Downgrades wuerden Daten loeschen und sind nicht vorgesehen"
    raise NotImplementedError(msg)
