#!/usr/bin/env bash
# Container-Smoke des frontend (P3.6): nginx vor dem web-api, wie auf der NAS.
#   docker/frontend-smoke.sh <frontend-image> <app-image>
# Prueft: nginx -t, Angular-Routen liefern index.html, /api/ geht ueber nginx an das web-api,
# Sicherheits-Header, und ein unbekannter Hostname bekommt keine Antwort (return 444).
set -euo pipefail

FRONTEND=$1
APP=$2
NET="va-smoke-$$"
URL="http://127.0.0.1:18080"

cleanup() {
    docker rm -f va-smoke-frontend va-smoke-web-api >/dev/null 2>&1 || true
    docker network rm "$NET" >/dev/null 2>&1 || true
}
trap cleanup EXIT

fail() {
    echo "FEHLER: $*"
    echo "--- frontend"; docker logs va-smoke-frontend 2>&1 | tail -20 || true
    echo "--- web-api"; docker logs va-smoke-web-api 2>&1 | tail -20 || true
    exit 1
}

docker network create "$NET" >/dev/null
# Health braucht keine Datenbank; die Adresse fuehrt bewusst ins Leere
docker run -d --name va-smoke-web-api --network "$NET" --network-alias web-api \
    -e WEB_API_DATABASE_URL=postgresql+psycopg://va_read:x@127.0.0.1:1/none \
    --entrypoint python "$APP" \
    -m uvicorn --factory va_web_api.main:create_app --host 0.0.0.0 --port 8000 >/dev/null
docker run -d --name va-smoke-frontend --network "$NET" -p 127.0.0.1:18080:8080 \
    -e VA_SERVER_NAMES="localhost 127.0.0.1" "$FRONTEND" >/dev/null

for _ in $(seq 1 30); do
    curl -fsS "$URL/api/v1/health" >/dev/null 2>&1 && break
    sleep 1
done

docker exec va-smoke-frontend nginx -t || fail "nginx -t"
curl -fsS "$URL/" | grep -q "<app-root" || fail "/ liefert nicht index.html"
curl -fsS "$URL/runs/1" | grep -q "<app-root" || fail "/runs/1 liefert nicht index.html"
curl -fsS "$URL/api/v1/health" | grep -q '"status":"ok"' || fail "/api/v1/health nicht ueber nginx"
headers=$(curl -fsSI "$URL/")
grep -qi "x-content-type-options: nosniff" <<<"$headers" || fail "X-Content-Type-Options fehlt"
grep -qi "content-security-policy:" <<<"$headers" || fail "Content-Security-Policy fehlt"
grep -qi "cache-control: no-cache" <<<"$headers" || fail "index.html wird gecacht"
if curl -sS -H "Host: boese.example" "$URL/" -o /dev/null 2>/dev/null; then
    fail "ein unbekannter Hostname bekam eine Antwort"
fi
echo "Frontend-Smoke bestanden"
