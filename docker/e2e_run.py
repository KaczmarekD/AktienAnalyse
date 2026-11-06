"""Startet im E2E-Stack einen Lauf ueber die API und wartet auf sein Ende (P5.2).

Aufruf: ``python docker/e2e_run.py http://127.0.0.1:18080`` (aus ``docker/e2e.sh``). Ueber nginx
wie das UI: Erst wenn scoring antwortet (Request/Reply steht), startet ``POST /api/v1/runs`` den
Lauf. Das web-api schliesst ``batch.run`` mit ``notification.report.sent`` ab; bis dahin fragt das
Skript ``GET /api/v1/runs/{id}``. Exit 0 bei ``success`` oder ``partial``, sonst 1. Nur
Standardbibliothek, damit es ohne Abhaengigkeiten laeuft.

Seit D1.4 laeuft der Stack mit Sitzungspflicht: Das Skript meldet sich vorher mit
``E2E_USERNAME`` und ``E2E_PASSWORD`` an (``docker/e2e.env``), das Cookie bleibt im Opener.
"""

from __future__ import annotations

import http.cookiejar
import json
import os
import sys
import time
import urllib.error
import urllib.request
from typing import Any

READY_SECONDS = 180  # bis scoring ueber NATS antwortet (Start der Container)
RUN_SECONDS = 600  # Abruf aus der Fixture, Bewertung und Mail

# Haelt das Sitzungs-Cookie wie ein Browser
_OPENER = urllib.request.build_opener(
    urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
)


def _call(base: str, method: str, path: str, body: Any = None) -> tuple[int, Any]:
    data = None if body is None else json.dumps(body).encode()
    headers = {} if body is None else {"Content-Type": "application/json"}
    request = urllib.request.Request(base + path, data=data, method=method, headers=headers)
    try:
        with _OPENER.open(request, timeout=30) as response:
            return response.status, json.loads(response.read() or b"null")
    except urllib.error.HTTPError as e:
        return e.code, None
    except OSError:
        return 0, None


def _wait(what: str, seconds: float, check: Any) -> Any:
    deadline = time.monotonic() + seconds
    while True:
        result = check()
        if result is not None:
            return result
        if time.monotonic() > deadline:
            sys.stderr.write(f"E2E: {what} nach {seconds:.0f} s nicht erreicht\n")
            sys.exit(1)
        time.sleep(2)


def _login(base: str) -> bool:
    username, password = os.environ.get("E2E_USERNAME"), os.environ.get("E2E_PASSWORD")
    if not username or not password:
        return True  # Stack ohne Sitzungspflicht
    status, _ = _call(
        base, "POST", "/api/v1/auth/login", {"username": username, "password": password}
    )
    if status != 204:
        sys.stderr.write(f"E2E: Anmeldung als {username} antwortet mit {status}\n")
        return False
    return True


def main(base: str) -> int:
    if not _login(base):
        return 1
    _wait(
        "scoring antwortet",
        READY_SECONDS,
        lambda: True if _call(base, "GET", "/api/v1/scoring/factors")[0] == 200 else None,
    )
    status, body = _call(base, "POST", "/api/v1/runs", {})
    if status != 202:
        sys.stderr.write(f"E2E: POST /api/v1/runs antwortet mit {status}\n")
        return 1
    run_id = body["id"]
    print(f"E2E: Lauf #{run_id} gestartet")

    def finished() -> dict[str, Any] | None:
        status, run = _call(base, "GET", f"/api/v1/runs/{run_id}")
        return run if status == 200 and run["finished_at"] is not None else None

    run = _wait(f"Ende von Lauf #{run_id}", RUN_SECONDS, finished)
    print(f"E2E: Lauf #{run_id} beendet mit {run['status']} (Exit {run['exit_code']})")
    return 0 if run["status"] in ("success", "partial") else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1].rstrip("/")))
