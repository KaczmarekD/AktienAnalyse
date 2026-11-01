"""``python -m va_platform.nats``: Stream und Consumer anlegen bzw. angleichen (P4.1).

Die Adresse kommt aus ``NATS_URL``, z. B. ``nats://nats:4222`` im Docker-Netz oder
``nats://127.0.0.1:4222`` lokal (``make nats-provision``).
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys

import nats

from . import provision

log = logging.getLogger("va_platform.nats")


async def _run(url: str) -> None:
    nc = await nats.connect(url, connect_timeout=5, max_reconnect_attempts=3)
    try:
        await provision(nc.jsm())
    finally:
        await nc.close()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-7s | %(message)s")
    url = os.environ.get("NATS_URL", "").strip()
    if not url:
        log.error("NATS_URL fehlt, z. B. nats://127.0.0.1:4222")
        return 2
    try:
        asyncio.run(_run(url))
    except Exception:
        log.exception("Provisionierung fehlgeschlagen")
        return 1
    log.info("JetStream ist eingerichtet")
    return 0


if __name__ == "__main__":
    sys.exit(main())
