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

import requests

log = logging.getLogger(__name__)


def ping(url: str | None, success: bool, message: str | None = None) -> None:
    if not url:
        return
    target = url if success else f"{url.rstrip('/')}/fail"
    try:
        requests.post(target, data=(message or "").encode("utf-8"), timeout=10)
        log.info("Healthcheck-Ping (%s) -> %s", "ok" if success else "fail", target)
    except requests.RequestException as e:
        log.warning("Healthcheck-Ping fehlgeschlagen: %s", e)
