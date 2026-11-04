#!/usr/bin/env bash
# Smoke-Test der Service-Images (P5.1): Aufruf docker/service_smoke.sh <tag>, etwa ci.
# Je Image: Der Service ist importierbar, kein anderer Service steckt darin, und der Start
# ohne Konfiguration endet mit Exit 2 (Konfigurationsfehler, kein Absturz).
set -euo pipefail

tag="${1:-ci}"
modules=(va_market_data va_scoring va_notification va_web_api)
declare -A images=(
  [va_market_data]=va-market-data
  [va_scoring]=va-scoring
  [va_notification]=va-notification
  [va_web_api]=va-web-api
)

for module in "${modules[@]}"; do
  image="${images[$module]}:$tag"
  echo "== $image"
  docker run --rm --entrypoint python "$image" -c "import $module; import va_platform.service"
  for other in "${modules[@]}"; do
    [[ "$other" == "$module" ]] && continue
    if docker run --rm --entrypoint python "$image" -c "import $other" 2>/dev/null; then
      echo "FEHLER: $image enthaelt auch $other" >&2
      exit 1
    fi
  done
  if [[ "$module" != "va_web_api" ]]; then
    status=0
    docker run --rm "$image" >/dev/null 2>&1 || status=$?
    if [[ "$status" -ne 2 ]]; then
      echo "FEHLER: $image endet ohne Konfiguration mit $status statt 2" >&2
      exit 1
    fi
  fi
done
echo "Service-Images in Ordnung"
