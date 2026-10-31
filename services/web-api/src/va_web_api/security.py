"""Schutzregeln des web-api im LAN ohne Login (P3.4, ADR-0007).

Schreibende Anfragen (POST, PUT, PATCH, DELETE) nimmt das web-api nur als
``application/json`` an, auch ohne Body. Fuer JSON prueft der Browser bei fremden Seiten vorab
(Preflight). CORS bleibt aus, deshalb scheitert diese Vorabpruefung. Formulare, ``text/plain``
und ein ``fetch`` ohne Body kaemen sonst ohne Vorabpruefung durch. Das eigene Frontend schickt
deshalb auch Befehle ohne Inhalt als JSON (``{}``).

Der Origin-Check fuer WebSockets (Regel 2) kommt mit dem Hub in P4.5, der Hostnamen-Filter
(Regel 3) steht in nginx (P3.6).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from starlette.datastructures import Headers
from starlette.responses import JSONResponse

if TYPE_CHECKING:
    from starlette.types import ASGIApp, Receive, Scope, Send

MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
JSON = "application/json"


class JsonOnlyMiddleware:
    """415 fuer jede schreibende Anfrage, die nicht ``application/json`` ist."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["method"] in MUTATING_METHODS:
            content_type = Headers(scope=scope).get("content-type", "")
            if content_type.split(";", 1)[0].strip().lower() != JSON:
                response = JSONResponse(
                    {"detail": f"Schreibende Anfragen nur als {JSON}"}, status_code=415
                )
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)
