# syntax=docker/dockerfile:1.7
# Ziel (ADR-0008): Images entstehen in der CI und die NAS laedt sie nur (P0.6).
# Bis dahin baut die NAS wie bisher selbst (docker compose build).
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=Europe/Berlin

RUN apt-get update && apt-get install -y --no-install-recommends \
        cron tzdata ca-certificates \
    && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime \
    && echo $TZ > /etc/timezone \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Abhaengigkeiten exakt aus uv.lock (ohne Dev-Tools) direkt ins System-Python
# (/usr/local): entrypoint.sh und Cron rufen /usr/local/bin/python auf.
# --locked: Abbruch, wenn uv.lock nicht zu pyproject.toml passt.
# --inexact: Pakete des Basis-Images (z. B. pip) bleiben erhalten.
# uv selbst und seine Variablen gibt es nur in diesem Schritt, nicht im Image.
RUN --mount=from=ghcr.io/astral-sh/uv:0.12.21,source=/uv,target=/bin/uv \
    --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    UV_PROJECT_ENVIRONMENT=/usr/local UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy \
    uv sync --locked --inexact --no-dev --no-install-project

COPY src/ ./src/
COPY migrations/ ./migrations/
COPY alembic.ini ./
COPY data/ ./data/
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh && touch /var/log/cron.log

VOLUME ["/app/data", "/app/logs"]

ENTRYPOINT ["/entrypoint.sh"]
