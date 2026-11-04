#!/usr/bin/env bash
# E2E-Test (U5.2, docs/architecture/umgebungen.md): die ganze Kette mit Replay-Daten statt Yahoo.
#   docker/e2e.sh        (make local-e2e baut vorher die Images; die CI nutzt ihre eigenen)
#
# Wegwerf-Stack aus docker-compose.e2e.yml: Datenbank auf tmpfs, UI unter 127.0.0.1:18080,
# Mailpit unter 127.0.0.1:18025. Seit P5.2 der ganze Stack: NATS, die drei Services, das web-api
# mit Projektionen. Ablauf: Datenbank, NATS und Mailpit starten, migrieren, Services und UI
# starten, den Lauf ueber die API ausloesen (docker/e2e_run.py), dann die Pruefungen unter
# tests/e2e/ (uv) und der Browser-Test unter frontend/e2e/ (Playwright, Chromium aus
# make ui-e2e-install). Danach wird der Stack entfernt, auch bei einem Fehler.
# Images: E2E_APP_IMAGE, E2E_FRONTEND_IMAGE, E2E_WEB_API_IMAGE und E2E_<SERVICE>_IMAGE
# (Standard: value-analyzer:local fuer alles ausser va-frontend:e2e).
# E2E_KEEP=1 laesst den Stack nach dem Test stehen, zum Ansehen im Browser.
set -euo pipefail

cd "$(dirname "$0")/.."
set -a
# shellcheck source=docker/e2e.env
. docker/e2e.env
set +a

COMPOSE=(docker compose --env-file docker/e2e.env
    -f docker-compose.yml -f docker-compose.local.yml -f docker-compose.e2e.yml)
export E2E_BASE_URL=http://127.0.0.1:18080
export E2E_MAILPIT_URL=http://127.0.0.1:18025

passed=0
cleanup() {
    if [ "$passed" -ne 1 ]; then
        echo "--- Logs des E2E-Stacks"
        "${COMPOSE[@]}" logs --no-color --tail 40 || true
    fi
    if [ "${E2E_KEEP:-0}" = "1" ]; then
        echo "Stack bleibt stehen: UI $E2E_BASE_URL, Mailpit $E2E_MAILPIT_URL"
        echo "Entfernen: ${COMPOSE[*]} down"
    else
        "${COMPOSE[@]}" down --remove-orphans >/dev/null 2>&1 || true
    fi
}
trap cleanup EXIT

echo "=== E2E: Datenbank, NATS und Mailpit starten"
"${COMPOSE[@]}" down --remove-orphans >/dev/null 2>&1 || true
"${COMPOSE[@]}" up -d --no-build --wait db nats mailpit

echo "=== E2E: Migration (App-Image)"
"${COMPOSE[@]}" run --rm --no-deps --entrypoint python value-analyzer -m src.db.migrate

echo "=== E2E: Services, web-api und frontend starten"
"${COMPOSE[@]}" up -d --no-build --wait market-data scoring notification web-api frontend
"${COMPOSE[@]}" exec -T frontend nginx -t

echo "=== E2E: Lauf ueber die API mit tests/fixtures/replay/$E2E_FIXTURE"
uv run --no-project python -I docker/e2e_run.py "$E2E_BASE_URL"

echo "=== E2E: Pruefungen (tests/e2e)"
uv run --locked pytest tests/e2e -p no:cacheprovider

# Chromium unter .local/playwright (make ui-e2e-install, in der CI ebenso), relativ zu frontend/
echo "=== E2E: Browser (frontend/e2e, Playwright)"
(cd frontend && PLAYWRIGHT_BROWSERS_PATH="${PLAYWRIGHT_BROWSERS_PATH:-../.local/playwright}" npx playwright test)

passed=1
echo "E2E bestanden"
