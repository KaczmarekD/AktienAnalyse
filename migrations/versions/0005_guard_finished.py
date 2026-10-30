"""Ein Lauf wird nur durch seinen Abschluss geaendert (P1.10)

Revision ID: 0005
Revises: 0004
Erstellt: 2026-10-30

Verschaerft die Trigger-Funktion ``va_guard_finished`` fuer ``batch.run`` und
``market_data.fetch_run``: Ein UPDATE auf einen offenen Lauf muss ``finished_at`` setzen.
Bisher liess sie beliebig viele Aenderungen zu, solange der Lauf offen war.

Die Funktion steht hier ausgeschrieben und wird nicht aus ``va_platform.db.ddl``
importiert: Eine Migration beschreibt den Stand ihres Datums. ``ddl.py`` hat dieselbe
Fassung, damit eine frische Datenbank (``0001`` bis hier) gleich aussieht wie eine
migrierte. Nichts wird geloescht, die Tabellen bleiben unveraendert.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

GUARD_FINISHED = r"""
CREATE OR REPLACE FUNCTION public.va_guard_finished() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.finished_at IS NOT NULL THEN
        RAISE EXCEPTION '%.% #% ist bereits abgeschlossen und unveraenderlich',
            TG_TABLE_SCHEMA, TG_TABLE_NAME, OLD.id
            USING ERRCODE = 'restrict_violation';
    END IF;
    IF NEW.finished_at IS NULL THEN
        RAISE EXCEPTION '%.% #%: ein UPDATE muss den Lauf abschliessen (finished_at)',
            TG_TABLE_SCHEMA, TG_TABLE_NAME, OLD.id
            USING ERRCODE = 'restrict_violation';
    END IF;
    IF NEW.id <> OLD.id OR NEW.started_at IS DISTINCT FROM OLD.started_at THEN
        RAISE EXCEPTION 'Aendern von id/started_at auf %.% ist verboten',
            TG_TABLE_SCHEMA, TG_TABLE_NAME
            USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END
$$;
"""


def upgrade() -> None:
    op.execute(GUARD_FINISHED)


def downgrade() -> None:
    msg = "Downgrades sind nicht vorgesehen"
    raise NotImplementedError(msg)
