#!/bin/bash
set -euo pipefail

# App-Image (Batch, Migration, Werkzeuge). Seit P5.4 ohne Cron: Den Wochenlauf plant das web-api
# (WEB_API_SCHEDULE), ausgefuehrt wird er von den Services ueber NATS.
#
# Datenbankschema aktualisieren - vor jedem Befehl, auch vor manuellen Runs.
# Nutzt DATABASE_OWNER_URL (Fallback DATABASE_URL) und wartet, bis Postgres bereit ist.
# Nicht fatal: Ist die DB (noch) nicht da, meldet main.py den Ausfall per Fehlermail (Exit 4).
echo "[entrypoint] Migriere Datenbankschema"
python -m src.db.migrate || echo "[entrypoint] WARNUNG: Migration fehlgeschlagen - Lauf meldet den DB-Fehler"

# Mit Argumenten den Befehl ausfuehren, etwa einen manuellen Lauf (python -m src.main)
if [ "$#" -gt 0 ]; then
    exec "$@"
fi
echo "[entrypoint] Kein Befehl - nur migriert"
