# syntax=docker/dockerfile:1.7
# ---------- Builder-Stage --------------------------------------------------
FROM python:3.12-slim AS builder

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY requirements.lock requirements.in ./

# Wheels in /wheels vorbauen, damit der Runtime-Stage sie ohne Compiler installieren kann.
RUN pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.lock

# ---------- Runtime-Stage --------------------------------------------------
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

# Wheels aus Builder kopieren und ohne Netzzugriff installieren
COPY --from=builder /wheels /wheels
COPY requirements.lock .
RUN pip install --no-cache-dir --no-index --find-links=/wheels -r requirements.lock \
    && rm -rf /wheels

COPY src/ ./src/
COPY data/ ./data/
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh && touch /var/log/cron.log

VOLUME ["/app/data", "/app/logs"]

ENTRYPOINT ["/entrypoint.sh"]
