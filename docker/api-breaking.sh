#!/usr/bin/env bash
# Schutz der Schnittstelle (P3.8, docs/architecture/frontend.md): Die REST-API bleibt unter
# /api/v1 abwaertskompatibel. oasdiff vergleicht den OpenAPI-Snapshot mit dem Stand am
# Abzweigpunkt von main und bricht bei inkompatiblen Aenderungen ab (entfernte Pfade, entfernte
# Pflichtfelder einer Antwort, neue Pflichtfelder einer Anfrage). Neues ist erlaubt.
#   docker/api-breaking.sh [ref]     (Standard: origin/main; make api-breaking)
# Auf main selbst gilt der Stand davor. Dass der Snapshot zur App passt, prueft
# tests/test_openapi.py.
set -euo pipefail

cd "$(dirname "$0")/.."
REF=${1:-origin/main}
IMAGE=tufin/oasdiff:v1.34.0
SNAPSHOT=tests/golden/openapi/v1.json
WORK=.local/oasdiff

base=$(git merge-base HEAD "$REF")
if [ "$base" = "$(git rev-parse HEAD)" ]; then
    base=$(git rev-parse HEAD^)
fi
mkdir -p "$WORK"
if ! git show "$base:$SNAPSHOT" > "$WORK/base.json" 2>/dev/null; then
    echo "Kein OpenAPI-Snapshot in $base - nichts zu vergleichen"
    exit 0
fi
cp "$SNAPSHOT" "$WORK/revision.json"

# Unter Git Bash (Windows) braucht docker den Windows-Pfad und keine Pfad-Umsetzung
host=$(cd "$WORK" && (pwd -W 2>/dev/null || pwd))
echo "OpenAPI: $(git rev-parse --short "$base") -> Arbeitsstand ($IMAGE)"
MSYS_NO_PATHCONV=1 docker run --rm -v "$host:/specs:ro" "$IMAGE" \
    breaking /specs/base.json /specs/revision.json --fail-on ERR
