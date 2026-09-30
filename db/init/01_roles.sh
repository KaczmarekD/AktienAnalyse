#!/bin/bash
# Laeuft nur beim allerersten Start des Postgres-Containers (leeres pgdata/).
# Legt die Rollen an; Schemas, Tabellen, Trigger und Rechte erzeugt die
# Migration (python -m src.db.migrate) beim Start des App-Containers.
#
#   va_app  - App: SELECT/INSERT, UPDATE nur fuer Laufabschluss/ISIN, kein DELETE
#   va_read - Auswertungen aus dem LAN (DBeaver, Jupyter, Excel): nur SELECT
set -euo pipefail

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
    -v app_pw="$VA_APP_PASSWORD" -v read_pw="$VA_READ_PASSWORD" <<'SQL'
CREATE ROLE va_app LOGIN PASSWORD :'app_pw';
CREATE ROLE va_read LOGIN PASSWORD :'read_pw';
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
SQL
