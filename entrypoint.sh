#!/bin/bash
set -euo pipefail

# Datenbankschema aktualisieren - vor jedem Start, auch vor manuellen Runs.
# Nutzt DATABASE_OWNER_URL (Fallback DATABASE_URL) und wartet, bis Postgres bereit ist.
# Nicht fatal: Ist die DB (noch) nicht da, soll der Container nicht in eine
# Neustart-Schleife laufen - main.py meldet den Ausfall per Fehlermail (Exit 4),
# und vor jedem Cron-Lauf wird die Migration erneut versucht.
echo "[entrypoint] Migriere Datenbankschema"
python -m src.db.migrate || echo "[entrypoint] WARNUNG: Migration fehlgeschlagen - Lauf meldet den DB-Fehler"

# Wenn Argumente uebergeben werden, direkt ausfuehren (manueller Run).
if [ "$#" -gt 0 ]; then
    exec "$@"
fi

CRON_SCHEDULE="${CRON_SCHEDULE:-30 7 * * 6}"
echo "[entrypoint] Cron-Schedule: ${CRON_SCHEDULE}"

# ENV in eine Datei dumpen, die der Cron-Job vor jedem Run sourct.
# (Cron startet eine minimale Shell ohne Container-ENV.)
# printf %q quotet Leerzeichen/Sonderzeichen (z.B. "[Value-Screening DAX/MDAX]"
# oder Gmail-App-Passwoerter mit Leerzeichen) - sonst bricht das Sourcen ab.
# DATABASE_OWNER_URL wird nur fuer die Migration vor jedem Lauf gebraucht.
ENV_PATTERN='^(SMTP_|MAIL_|UNIVERSE$|TOP_N$|BOTTOM_N$|MIN_MARKET_CAP$|VALUE_WEIGHT$|QUALITY_WEIGHT$|DEFAULT_TAX_RATE$|HEALTHCHECK_URL$|DATABASE_URL$|DATABASE_OWNER_URL$|TZ$|DATA_DIR$|LOGS_DIR$)'
{
    for var in $(compgen -e); do
        if [[ "$var" =~ $ENV_PATTERN ]]; then
            printf 'export %s=%q\n' "$var" "${!var}"
        fi
    done
} > /app/.env.cron

# Dynamisches crontab-File schreiben
cat > /etc/cron.d/value-analyzer <<CRONEOF
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
${CRON_SCHEDULE} root . /app/.env.cron && cd /app && { /usr/local/bin/python -m src.db.migrate; /usr/local/bin/python -m src.main; } >> /var/log/cron.log 2>&1

CRONEOF
chmod 0644 /etc/cron.d/value-analyzer

echo "[entrypoint] Starte cron und tail -F /var/log/cron.log"
cron
exec tail -F /var/log/cron.log
