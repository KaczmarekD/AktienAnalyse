# Betrieb auf der Synology

> **Status:** Plan (30.09.2026). Entscheidungen: [ADR-0007](../adr/0007-lan-only-ohne-login.md)
> (nur LAN) und [ADR-0008](../adr/0008-zielhardware-j4125.md) (Zielhardware).

## Zielhardware

| Eigenschaft | Wert | Folge |
|---|---|---|
| CPU | Intel Celeron J4125: x86_64, 4 Kerne, 2,0–2,7 GHz | reicht; der Engpass ist Yahoos Rate-Limit, nicht die CPU |
| Befehlssatz | bis SSE4.2 (x86-64-v2), **kein AVX/AVX2** | keine Pakete, die x86-64-v3 voraussetzen |
| RAM | 18 GB | kein Engpass; Speicherlimits dienen nur als Sicherheitsnetz |
| Betriebssystem | DSM 7.x, Plattform geminilake, **Kernel 4.4** | nichts, was einen neueren Kernel voraussetzt |
| Container | Container Manager (Docker 24 mit Compose) | Compose-Datei wie unten |

## Drei feste Regeln

1. **Images nur für `linux/amd64`, gebaut ausschließlich in GitHub Actions.** Die NAS lädt fertige
   Images aus der GitHub Container Registry (GHCR) und baut selbst nichts. Kernel 4.4 fehlen
   neuere Systemaufrufe wie `statx` (erst ab 4.11), daran scheitern moderne Build-Tools. Für Bun
   ist das auf genau diesem Prozessor dokumentiert. Node läuft deshalb nie auf der NAS.
2. **Kein AVX2-Code.** NumPy setzt seit Version 2.4 x86-64-v2 voraus, das schafft der J4125 gerade
   noch. Pakete, die x86-64-v3 brauchen, stürzen mit `Illegal instruction` ab. Nach jedem
   Dependency-Upgrade und vor dem Deployment prüfen (die CI macht dasselbe bei jedem Push):
   ```
   make check-j4125
   ```
   Das baut die Stufe `j4125-check` des Dockerfiles, also das App-Image plus QEMU, und führt
   Python darin mit dem CPU-Modell Denverton aus (Goldmont, dieselbe Klasse wie der J4125:
   SSE4.2, kein AVX; ein Goldmont-Plus-Modell hat QEMU nicht). Zuerst führt `run.sh` eine
   einzelne AVX2-Instruktion aus. Sie muss mit SIGILL enden, sonst fängt die Emulation AVX2
   nicht ab und die Prüfung bricht ab. Danach stellt das Prüfskript
   (`docker/j4125-check/check_imports.py`) sicher, dass das CPU-Modell kein AVX meldet, lädt
   jede native Erweiterung im Image und den Importgraph der App und rechnet wie im Wochenlauf:
   Ranking, Mail-Report, Parquet-Durchlauf. Ein Paket mit AVX-Code beendet den Lauf mit
   Exit-Code 132.

   Bis die Images aus der CI kommen (P0.6), baut die NAS ihr Image noch selbst. Der Build
   braucht BuildKit (`RUN --mount` im Dockerfile); mit Docker 24 im Container Manager ist das
   Standard. Nach jedem Build dort zusätzlich auf der echten CPU prüfen (ohne DB, ohne
   Migration):
   ```
   docker compose run --rm --no-deps --entrypoint python value-analyzer -c "import src.main"
   ```
3. **Keine Kernel-Features jenseits von 4.4.** Postgres 18 bleibt beim Standard-`io_method`, die
   neue `io_uring`-Option wird nicht aktiviert. Es gibt keine cgroup-v2-Features.

## Netzwerk

- Nur der `frontend`-Container veröffentlicht einen Port (8080). web-api, Postgres und NATS hängen
  ausschließlich im internen Docker-Netz.
- Zugriff über `http://<nas>:8080`. Die DSM-Firewall gibt den Port nur für das eigene Subnetz frei.
- HTTPS ist optional über den DSM-Reverse-Proxy möglich. Dann dort die WebSocket-Header
  aktivieren: Reverse Proxy → Benutzerdefinierter Header → Erstellen → WebSocket.
- Weitere Sicherheitsregeln (Origin-Prüfung, nur JSON, Hostnamen-Filter):
  [web-api-realtime.md](web-api-realtime.md#sicherheitsregeln-lan-ohne-login).

## Compose (Skizze, Zielbild ab Phase 5)

```yaml
# deploy/compose.yaml
x-base: &base
  restart: unless-stopped
  networks: [internal]
x-py: &py
  <<: *base
  env_file: .env

services:
  frontend:                       # einziger Container mit Port im LAN
    <<: *base
    image: ${REG}/va-frontend:${VERSION}
    ports: ["8080:8080"]
    mem_limit: 128m
  web-api:     { <<: *py, image: "${REG}/va-web-api:${VERSION}",     mem_limit: 1g }
  market-data: { <<: *py, image: "${REG}/va-market-data:${VERSION}", mem_limit: 1g }
  scoring:     { <<: *py, image: "${REG}/va-scoring:${VERSION}",     mem_limit: 1g }
  notification:
    <<: *py
    image: ${REG}/va-notification:${VERSION}
    mem_limit: 512m
    secrets: [smtp_password]      # -> /run/secrets, gelesen via pydantic secrets_dir
  postgres:
    <<: *py
    image: postgres:18-alpine
    command: postgres -c shared_buffers=512MB
    volumes: ["./volumes/postgres:/var/lib/postgresql"]   # ab PG 18 nicht mehr .../data
    mem_limit: 2g
  nats:
    <<: *base
    image: nats:2.12-alpine
    command: -js -sd /data        # JetStream mit Datei-Storage
    volumes: ["./volumes/nats:/data"]
    mem_limit: 512m

networks:
  internal: {}
secrets:
  smtp_password: { file: ./secrets/smtp_password }
```

`REG` (z. B. `ghcr.io/kaczmarekd`) und `VERSION` stehen in der `.env` neben der Compose-Datei.
Bei 18 GB RAM sind die Limits großzügig. Sie verhindern nur, dass ein fehlerhafter Service DSM
den Speicher wegnimmt.

## Build und Deployment

```dockerfile
# services/scoring/Dockerfile – Skizze (Build nur in CI)
FROM python:3.14-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /usr/local/bin/uv
WORKDIR /repo
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY . .
RUN uv sync --frozen --no-dev --package va-scoring --no-editable

FROM python:3.14-slim
COPY --from=build /repo/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"
CMD ["faststream", "run", "va_scoring.entrypoints.worker:app"]
```

Die Version des uv-Images in der Skizze ist nur ein Platzhalter und wird bei der Umsetzung
festgelegt.

Ablauf eines Updates:

1. Tag oder Merge auf `main` → GitHub Actions baut alle geänderten Images (`linux/amd64`) und
   schiebt sie nach GHCR.
2. Auf der NAS: `VERSION` in der `.env` setzen, dann `docker compose pull`.
3. Import-Test (Regel 2), danach `docker compose up -d`.
4. Jeder Service migriert beim Start sein eigenes Schema mit der Owner-Rolle.

Sind die Images privat, braucht die NAS einmalig `docker login ghcr.io` mit einem Token, das nur
`read:packages` darf.

## Secrets

Secrets liegen als Docker-Secrets unter `/run/secrets` und werden über `secrets_dir` in
pydantic-settings gelesen. Sie stehen nicht in einer großen `.env`. Über die API sind sie nie
lesbar.

## Backup

- Täglich `pg_dump` per Cron-Container in ein eigenes Volume, das Hyper Backup mitsichert.
- NATS braucht kein Backup. Der Stream hält nur Zustellungen der letzten 30 Tage, die Wahrheit
  liegt in Postgres.

## Überwachung

- Healthchecks.io bleibt der Dead-Man's-Switch. Gepingt wird nur bei geplanten Runs
  ([events.md](events.md)).
- Jeder Container hat einen Healthcheck.
- Logs gehen als JSON auf stdout, Docker rotiert sie.
- Optional ab Phase 5: OpenTelemetry-Tracing über alle Services mit einem Grafana-Stack (z. B.
  `grafana/otel-lgtm`). Der RAM reicht dafür. Weil es Go-Binaries sind, ist kein AVX nötig, trotzdem
  vorher auf der NAS testen.
