"""SQL-Bausteine fuer Migrationen: Loeschschutz und Rollenrechte.

Jede neue Tabelle braucht ``protect_table()`` in ihrer Migration - der Test
``tests/db/test_protection.py`` prueft das fuer alle Tabellen der App-Schemas.

Rollen (legt ``db/init/01_roles.sh`` an, bzw. der DBA bei fremdem Postgres):
- Owner (``POSTGRES_USER``): fuehrt Migrationen aus.
- ``va_app``: SELECT/INSERT, UPDATE nur fuer Laufabschluss und ISIN - kein DELETE.
- ``va_read``: nur SELECT, fuer Auswertungen aus dem LAN.
"""

from __future__ import annotations

from collections.abc import Iterable

SCHEMAS = ("batch", "market_data", "scoring", "reporting")

# Tabellen, die genau einmal aktualisiert werden duerfen (Abschluss bzw. ISIN)
UPDATABLE_TABLES = ("batch.run", "market_data.fetch_run", "market_data.instrument")

CREATE_FUNCTIONS = r"""
CREATE OR REPLACE FUNCTION public.va_forbid_change() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION '% auf %.% ist verboten - Daten werden niemals geloescht oder ueberschrieben',
        TG_OP, TG_TABLE_SCHEMA, TG_TABLE_NAME
        USING ERRCODE = 'restrict_violation';
END
$$;

CREATE OR REPLACE FUNCTION public.va_guard_finished() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.finished_at IS NOT NULL THEN
        RAISE EXCEPTION '%.% #% ist bereits abgeschlossen und unveraenderlich',
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

CREATE OR REPLACE FUNCTION public.va_guard_instrument() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.id <> OLD.id
       OR NEW.symbol IS DISTINCT FROM OLD.symbol
       OR NEW.first_seen_at IS DISTINCT FROM OLD.first_seen_at
       OR (OLD.isin IS NOT NULL AND NEW.isin IS DISTINCT FROM OLD.isin) THEN
        RAISE EXCEPTION 'Aendern von market_data.instrument #% ist verboten (nur ISIN nachtragen)',
            OLD.id
            USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END
$$;
"""


def protect_table(table: str) -> list[str]:
    """Trigger-DDL fuer eine Tabelle (``schema.name``): nie loeschen, nie ueberschreiben."""
    statements = [
        f"CREATE TRIGGER va_no_delete BEFORE DELETE ON {table} "
        "FOR EACH STATEMENT EXECUTE FUNCTION public.va_forbid_change()",
        f"CREATE TRIGGER va_no_truncate BEFORE TRUNCATE ON {table} "
        "FOR EACH STATEMENT EXECUTE FUNCTION public.va_forbid_change()",
    ]
    if table == "market_data.instrument":
        statements.append(
            f"CREATE TRIGGER va_guard_update BEFORE UPDATE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION public.va_guard_instrument()"
        )
    elif table in UPDATABLE_TABLES:
        statements.append(
            f"CREATE TRIGGER va_guard_update BEFORE UPDATE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION public.va_guard_finished()"
        )
    else:
        statements.append(
            f"CREATE TRIGGER va_no_update BEFORE UPDATE ON {table} "
            "FOR EACH STATEMENT EXECUTE FUNCTION public.va_forbid_change()"
        )
    return statements


def grant_statements(schemas: Iterable[str] = SCHEMAS) -> str:
    """Rechte fuer va_app/va_read - nur, wenn die Rollen existieren (idempotent)."""
    schema_list = ", ".join(f"'{s}'" for s in schemas)
    updatable = ", ".join(UPDATABLE_TABLES)
    return f"""
DO $$
DECLARE s text;
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'va_app') THEN
        FOREACH s IN ARRAY ARRAY[{schema_list}] LOOP
            EXECUTE format('GRANT USAGE ON SCHEMA %I TO va_app', s);
            EXECUTE format('GRANT SELECT, INSERT ON ALL TABLES IN SCHEMA %I TO va_app', s);
            EXECUTE format('GRANT USAGE ON ALL SEQUENCES IN SCHEMA %I TO va_app', s);
            EXECUTE format('ALTER DEFAULT PRIVILEGES IN SCHEMA %I '
                           'GRANT SELECT, INSERT ON TABLES TO va_app', s);
            EXECUTE format('ALTER DEFAULT PRIVILEGES IN SCHEMA %I '
                           'GRANT USAGE ON SEQUENCES TO va_app', s);
        END LOOP;
        EXECUTE 'GRANT UPDATE ON {updatable} TO va_app';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'va_read') THEN
        FOREACH s IN ARRAY ARRAY[{schema_list}] LOOP
            EXECUTE format('GRANT USAGE ON SCHEMA %I TO va_read', s);
            EXECUTE format('GRANT SELECT ON ALL TABLES IN SCHEMA %I TO va_read', s);
            EXECUTE format('ALTER DEFAULT PRIVILEGES IN SCHEMA %I '
                           'GRANT SELECT ON TABLES TO va_read', s);
        END LOOP;
    END IF;
END
$$;
"""
