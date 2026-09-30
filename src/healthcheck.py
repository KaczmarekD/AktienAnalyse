"""Healthchecks.io-kompatibler Heartbeat (optional).

Wenn ``HEALTHCHECK_URL`` gesetzt ist, pingt diese Funktion am Ende des
Runs den Endpoint. Bei Fehler wird ``/fail`` angehaengt, sodass der
Dienst eine Stoerung erkennt und z.B. eine Mail/Push schickt, falls der
Cron nicht laeuft.

Funktioniert mit https://healthchecks.io und kompatiblen
Self-Hosted-Alternativen.
"""

from __future__ import annotations

import logging
from urllib.parse import urlsplit

import requests

log = logging.getLogger(__name__)


def ping(url: str | None, success: bool, message: str | None = None) -> bool | None:
    """Pingt den Endpoint. None = kein Endpoint konfiguriert, sonst Erfolg des Pings.

    Fehler werden nie geworfen - Healthcheck darf den Run nicht abbrechen.
    """
    if not url:
        return None
    target = url if success else f"{url.rstrip('/')}/fail"
    try:
        response = requests.post(target, data=(message or "").encode("utf-8"), timeout=10)
        response.raise_for_status()
    except requests.RequestException as e:
        # Nur Typ + Host loggen: die Exception-Meldung enthaelt die URL samt UUID,
        # und das Log landet dauerhaft in batch.run_log
        log.warning(
            "Healthcheck-Ping an %s fehlgeschlagen (%s)", ping_target(url), type(e).__name__
        )
        return False
    log.info("Healthcheck-Ping (%s) -> %s", "ok" if success else "fail", ping_target(url))
    return True


def ping_target(url: str | None) -> str | None:
    """Nur der Host - der Pfad (UUID) ist ein Geheimnis und gehoert weder ins Log noch in die DB."""
    return urlsplit(url).hostname if url else None
