#!/bin/bash
set -euo pipefail

# Wenn argumente uebergeben werden, direkt ausfuehren (manueller Run).
if [ "$#" -gt 0 ]; then
    exec "$@"
fi

CRON_SCHEDULE="${CRON_SCHEDULE:-30 7 * * 6}"
echo "[entrypoint] Cron-Schedule: ${CRON_SCHEDULE}"

# ENV in eine Datei dumpen, die der Cron-Job vor jedem Run sourct.
# (Cron startet eine minimale Shell ohne Container-ENV.)
{
    printenv | grep -E '^(SMTP_|MAIL_|UNIVERSE|TOP_N|BOTTOM_N|MIN_MARKET_CAP|VALUE_WEIGHT|QUALITY_WEIGHT|DEFAULT_TAX_RATE|HEALTHCHECK_URL|TZ|DATA_DIR|LOGS_DIR)=' \
        | sed 's/^\(.*\)$/export \1/g'
} > /app/.env.cron

# Dynamisches crontab-File schreiben
cat > /etc/cron.d/value-analyzer <<CRONEOF
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
${CRON_SCHEDULE} root . /app/.env.cron && cd /app && /usr/local/bin/python -m src.main >> /var/log/cron.log 2>&1

CRONEOF
chmod 0644 /etc/cron.d/value-analyzer

echo "[entrypoint] Starte cron und tail -F /var/log/cron.log"
cron
exec tail -F /var/log/cron.log
