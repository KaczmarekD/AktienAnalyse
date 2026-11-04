# syntax=docker/dockerfile:1.7
# Images entstehen in der CI und die NAS laedt sie aus GHCR (ADR-0008, P0.6b).
# Lokal: make build.
#
# Stufen: base (alles fuer den Lauf) -> j4125-check (base + QEMU, nur zum Pruefen)
#         base -> runtime (Standard-Ziel, das App-Image in GHCR)
#         service-base -> market-data, scoring, notification, web-api (P5.1, je ein Image)
FROM python:3.14-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=Europe/Berlin

RUN apt-get update && apt-get install -y --no-install-recommends \
        tzdata ca-certificates \
    && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime \
    && echo $TZ > /etc/timezone \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Abhaengigkeiten exakt aus uv.lock (ohne Dev-Tools) direkt ins System-Python
# (/usr/local): entrypoint.sh ruft /usr/local/bin/python auf.
# --locked: Abbruch, wenn uv.lock nicht zu pyproject.toml passt.
# --inexact: Pakete des Basis-Images (z. B. pip) bleiben erhalten.
# uv selbst und seine Variablen gibt es nur in diesem Schritt, nicht im Image.
# Zwei Schritte, damit eine Code-Aenderung in packages/ oder services/ die grosse
# Abhaengigkeitsschicht nicht neu entstehen laesst:
# 1. alle Fremdpakete, ohne Workspace-Mitglieder - dafuer braucht uv von den
#    Mitgliedern nur die pyproject.toml (sonst passt --locked nicht zum Lockfile)
# 2. die Workspace-Mitglieder, die der Batch nutzt (ab P1.3), nicht-editierbar:
#    Ein editierbarer Eintrag zeigte auf den Bind-Mount, den es nach RUN nicht mehr gibt.
#    --refresh-package: uv erkennt geaenderten Code der Mitglieder nur an Zeitstempeln
#    und baute sonst lokal aus dem Cache-Mount einen alten Stand ins Image.
RUN --mount=from=ghcr.io/astral-sh/uv:0.12.21,source=/uv,target=/bin/uv \
    --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=packages/va-contracts/pyproject.toml,target=packages/va-contracts/pyproject.toml \
    --mount=type=bind,source=packages/va-platform/pyproject.toml,target=packages/va-platform/pyproject.toml \
    --mount=type=bind,source=services/market-data/pyproject.toml,target=services/market-data/pyproject.toml \
    --mount=type=bind,source=services/scoring/pyproject.toml,target=services/scoring/pyproject.toml \
    --mount=type=bind,source=services/notification/pyproject.toml,target=services/notification/pyproject.toml \
    --mount=type=bind,source=services/web-api/pyproject.toml,target=services/web-api/pyproject.toml \
    UV_PROJECT_ENVIRONMENT=/usr/local UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy \
    uv sync --locked --inexact --no-dev --no-install-project --no-install-workspace
RUN --mount=from=ghcr.io/astral-sh/uv:0.12.21,source=/uv,target=/bin/uv \
    --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=packages,target=packages \
    --mount=type=bind,source=services,target=services \
    UV_PROJECT_ENVIRONMENT=/usr/local UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy \
    uv sync --locked --inexact --no-dev --no-install-project --no-editable \
        --refresh-package va-contracts --refresh-package va-platform \
        --refresh-package va-market-data --refresh-package va-scoring \
        --refresh-package va-notification --refresh-package va-web-api

COPY src/ ./src/
COPY migrations/ ./migrations/
COPY alembic.ini ./
COPY data/ ./data/
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

VOLUME ["/app/data", "/app/logs"]

ENTRYPOINT ["/entrypoint.sh"]

# ---------- Images je Service (P5.1, ADR-0004) ----------------------------------
# Jedes installiert mit uv sync --package nur sein Paket samt va-platform und va-contracts,
# ohne src/ und ohne Cron. Dieselben Pakete aus uv.lock wie im App-Image: Dessen
# J4125-Pruefung deckt sie mit ab. Das App-Image (runtime) bleibt fuer Batch und Migration.
FROM python:3.14-slim AS service-base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=Europe/Berlin

RUN apt-get update && apt-get install -y --no-install-recommends tzdata ca-certificates \
    && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime \
    && echo $TZ > /etc/timezone \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

FROM service-base AS market-data
RUN --mount=from=ghcr.io/astral-sh/uv:0.12.21,source=/uv,target=/bin/uv \
    --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=packages/va-contracts/pyproject.toml,target=packages/va-contracts/pyproject.toml \
    --mount=type=bind,source=packages/va-platform/pyproject.toml,target=packages/va-platform/pyproject.toml \
    --mount=type=bind,source=services/market-data/pyproject.toml,target=services/market-data/pyproject.toml \
    --mount=type=bind,source=services/scoring/pyproject.toml,target=services/scoring/pyproject.toml \
    --mount=type=bind,source=services/notification/pyproject.toml,target=services/notification/pyproject.toml \
    --mount=type=bind,source=services/web-api/pyproject.toml,target=services/web-api/pyproject.toml \
    UV_PROJECT_ENVIRONMENT=/usr/local UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy \
    uv sync --locked --inexact --no-dev --package va-market-data --no-install-workspace
RUN --mount=from=ghcr.io/astral-sh/uv:0.12.21,source=/uv,target=/bin/uv \
    --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=packages,target=packages \
    --mount=type=bind,source=services,target=services \
    UV_PROJECT_ENVIRONMENT=/usr/local UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy \
    uv sync --locked --inexact --no-dev --package va-market-data --no-editable \
        --refresh-package va-contracts --refresh-package va-platform --refresh-package va-market-data
# Fallback-CSV des Universums (FALLBACK_CSV, Standard data/dax_mdax_fallback.csv)
COPY data/ ./data/
ENTRYPOINT ["python", "-m", "va_market_data"]

FROM service-base AS scoring
RUN --mount=from=ghcr.io/astral-sh/uv:0.12.21,source=/uv,target=/bin/uv \
    --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=packages/va-contracts/pyproject.toml,target=packages/va-contracts/pyproject.toml \
    --mount=type=bind,source=packages/va-platform/pyproject.toml,target=packages/va-platform/pyproject.toml \
    --mount=type=bind,source=services/market-data/pyproject.toml,target=services/market-data/pyproject.toml \
    --mount=type=bind,source=services/scoring/pyproject.toml,target=services/scoring/pyproject.toml \
    --mount=type=bind,source=services/notification/pyproject.toml,target=services/notification/pyproject.toml \
    --mount=type=bind,source=services/web-api/pyproject.toml,target=services/web-api/pyproject.toml \
    UV_PROJECT_ENVIRONMENT=/usr/local UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy \
    uv sync --locked --inexact --no-dev --package va-scoring --no-install-workspace
RUN --mount=from=ghcr.io/astral-sh/uv:0.12.21,source=/uv,target=/bin/uv \
    --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=packages,target=packages \
    --mount=type=bind,source=services,target=services \
    UV_PROJECT_ENVIRONMENT=/usr/local UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy \
    uv sync --locked --inexact --no-dev --package va-scoring --no-editable \
        --refresh-package va-contracts --refresh-package va-platform --refresh-package va-scoring
ENTRYPOINT ["python", "-m", "va_scoring"]

FROM service-base AS notification
RUN --mount=from=ghcr.io/astral-sh/uv:0.12.21,source=/uv,target=/bin/uv \
    --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=packages/va-contracts/pyproject.toml,target=packages/va-contracts/pyproject.toml \
    --mount=type=bind,source=packages/va-platform/pyproject.toml,target=packages/va-platform/pyproject.toml \
    --mount=type=bind,source=services/market-data/pyproject.toml,target=services/market-data/pyproject.toml \
    --mount=type=bind,source=services/scoring/pyproject.toml,target=services/scoring/pyproject.toml \
    --mount=type=bind,source=services/notification/pyproject.toml,target=services/notification/pyproject.toml \
    --mount=type=bind,source=services/web-api/pyproject.toml,target=services/web-api/pyproject.toml \
    UV_PROJECT_ENVIRONMENT=/usr/local UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy \
    uv sync --locked --inexact --no-dev --package va-notification --no-install-workspace
RUN --mount=from=ghcr.io/astral-sh/uv:0.12.21,source=/uv,target=/bin/uv \
    --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=packages,target=packages \
    --mount=type=bind,source=services,target=services \
    UV_PROJECT_ENVIRONMENT=/usr/local UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy \
    uv sync --locked --inexact --no-dev --package va-notification --no-editable \
        --refresh-package va-contracts --refresh-package va-platform --refresh-package va-notification
ENTRYPOINT ["python", "-m", "va_notification"]

FROM service-base AS web-api
RUN --mount=from=ghcr.io/astral-sh/uv:0.12.21,source=/uv,target=/bin/uv \
    --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=packages/va-contracts/pyproject.toml,target=packages/va-contracts/pyproject.toml \
    --mount=type=bind,source=packages/va-platform/pyproject.toml,target=packages/va-platform/pyproject.toml \
    --mount=type=bind,source=services/market-data/pyproject.toml,target=services/market-data/pyproject.toml \
    --mount=type=bind,source=services/scoring/pyproject.toml,target=services/scoring/pyproject.toml \
    --mount=type=bind,source=services/notification/pyproject.toml,target=services/notification/pyproject.toml \
    --mount=type=bind,source=services/web-api/pyproject.toml,target=services/web-api/pyproject.toml \
    UV_PROJECT_ENVIRONMENT=/usr/local UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy \
    uv sync --locked --inexact --no-dev --package va-web-api --no-install-workspace
RUN --mount=from=ghcr.io/astral-sh/uv:0.12.21,source=/uv,target=/bin/uv \
    --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=packages,target=packages \
    --mount=type=bind,source=services,target=services \
    UV_PROJECT_ENVIRONMENT=/usr/local UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy \
    uv sync --locked --inexact --no-dev --package va-web-api --no-editable \
        --refresh-package va-contracts --refresh-package va-platform --refresh-package va-web-api
# Ohne src: Vorschau und Profile nur ueber NATS (WEB_API_NATS_URL), ab P5.4 Standard
ENTRYPOINT ["python", "-m", "uvicorn", "--factory", "va_web_api.main:create_app", "--host", "0.0.0.0", "--port", "8000"]

# ---------- J4125-Pruefung (ADR-0008) ------------------------------------------
# Dasselbe Image plus QEMU: Python laeuft unter dem CPU-Modell Denverton (Goldmont,
# SSE4.2, kein AVX - dieselbe Klasse wie der J4125 der NAS). Aufruf: make check-j4125
FROM base AS j4125-check
RUN apt-get update && apt-get install -y --no-install-recommends qemu-user tini \
    && rm -rf /var/lib/apt/lists/*
COPY docker/j4125-check/check_imports.py docker/j4125-check/avx2_probe.py /opt/j4125/
COPY --chmod=0755 docker/j4125-check/run.sh /opt/j4125/run.sh
# tini als PID 1: Trifft QEMU auf AVX, beendet es sich selbst mit SIGILL. Als PID 1 wuerde
# der Kernel dieses Signal verwerfen und QEMU ewig haengen statt mit Exit-Code 132 zu enden.
# In run.sh: -cpu Denverton,-xsavec - die Emulation (TCG) bildet XSAVEC nicht nach und
# wuerde sonst bei jedem Start warnen; fuer die AVX-Frage spielt es keine Rolle.
ENTRYPOINT ["tini", "--", "/opt/j4125/run.sh"]
CMD ["/opt/j4125/check_imports.py"]

# ---------- Laufzeit-Image (Standard-Ziel) -------------------------------------
FROM base AS runtime
