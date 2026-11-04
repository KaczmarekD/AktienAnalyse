#!/bin/bash
# Laeuft nur beim allerersten Start des Postgres-Containers (leeres pgdata/).
# Legt die Rollen an; Schemas, Tabellen, Trigger und Rechte erzeugt die
# Migration (python -m src.db.migrate) beim Start des App-Containers.
#
#   va_app      - App: SELECT/INSERT, UPDATE nur fuer Laufabschluss/ISIN, kein DELETE
#   va_read     - Auswertungen aus dem LAN (DBeaver, Jupyter, Excel): nur SELECT
#   va_profiles - web-api: Profile lesen, Versionen und Aktivierungen anfuegen (P3.3)
#   va_web      - web-api: Projektionen im Schema web schreiben (P4.4)
#   va_market_data, va_scoring, va_notification - je Service nur das eigene Schema (P5.3)
set -euo pipefail

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
    -v app_pw="$VA_APP_PASSWORD" -v read_pw="$VA_READ_PASSWORD" <<'SQL'
CREATE ROLE va_app LOGIN PASSWORD :'app_pw';
CREATE ROLE va_read LOGIN PASSWORD :'read_pw';
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
SQL

# Ohne Passwort keine Rolle: Das web-api antwortet beim Speichern dann mit 503
if [ -n "${VA_PROFILES_PASSWORD:-}" ]; then
    psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
        -v profiles_pw="$VA_PROFILES_PASSWORD" <<'SQL'
CREATE ROLE va_profiles LOGIN PASSWORD :'profiles_pw';
SQL
fi

# Ohne Passwort keine Rolle: Das web-api laeuft dann ohne Projektionen
if [ -n "${VA_WEB_PASSWORD:-}" ]; then
    psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
        -v web_pw="$VA_WEB_PASSWORD" <<'SQL'
CREATE ROLE va_web LOGIN PASSWORD :'web_pw';
SQL
fi

# P5.3: eine Rolle je Service; ohne Passwort keine Rolle (die Services laufen erst mit NATS)
for pair in "va_market_data:${VA_MARKET_DATA_PASSWORD:-}"             "va_scoring:${VA_SCORING_PASSWORD:-}"             "va_notification:${VA_NOTIFICATION_PASSWORD:-}"; do
    role="${pair%%:*}"
    password="${pair#*:}"
    if [ -n "$password" ]; then
        psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB"             -v pw="$password" <<SQL
CREATE ROLE $role LOGIN PASSWORD :'pw';
SQL
    fi
done
