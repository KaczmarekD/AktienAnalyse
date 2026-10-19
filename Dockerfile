# syntax=docker/dockerfile:1.7
# Ziel (ADR-0008): Images entstehen in der CI und die NAS laedt sie nur (P0.6).
# Bis dahin baut die NAS wie bisher selbst (docker compose build).
#
# Stufen: base (alles fuer den Lauf) -> j4125-check (base + QEMU, nur zum Pruefen)
#         base -> runtime (Standard-Ziel, docker-compose.yml nutzt target: runtime)
FROM python:3.14-slim AS base

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
