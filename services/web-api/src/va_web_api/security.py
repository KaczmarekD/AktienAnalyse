"""Schutzregeln des web-api im LAN ohne Login (P3.4, ADR-0007).

Schreibende Anfragen (POST, PUT, PATCH, DELETE) nimmt das web-api nur als
``application/json`` an, auch ohne Body. Fuer JSON prueft der Browser bei fremden Seiten vorab
(Preflight). CORS bleibt aus, deshalb scheitert diese Vorabpruefung. Formulare, ``text/plain``
und ein ``fetch`` ohne Body kaemen sonst ohne Vorabpruefung durch. Das eigene Frontend schickt
deshalb auch Befehle ohne Inhalt als JSON (``{}``).

Der Origin-Check fuer WebSockets (Regel 2) kommt mit dem Hub in P4.5, der Hostnamen-Filter
(Regel 3) steht in nginx (P3.6). Seit D1.2 gilt der Origin-Check auch fuer jede schreibende
Anfrage (``OriginCheckMiddleware``), weil das Sitzungs-Cookie CSRF wieder moeglich macht.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from starlette.datastructures import Headers
from starlette.responses import JSONResponse

if TYPE_CHECKING:
    from starlette.types import ASGIApp, Receive, Scope, Send

MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
JSON = "application/json"


def origin_allowed(origin: str | None, host: str | None, allowed: frozenset[str]) -> bool:
    """Herkunft erlaubt: genau die Liste ``WEB_API_ALLOWED_ORIGINS``, ohne Liste dieselbe wie der
    ``Host``. Gilt am WebSocket (P4.5) und seit D1.2 fuer jede schreibende Anfrage."""
    if not origin:
        return False
    origin = origin.strip().rstrip("/").lower()
    if allowed:
        return origin in allowed
    parts = urlsplit(origin)
    return parts.scheme in ("http", "https") and bool(host) and parts.netloc == host.lower()


class OriginCheckMiddleware:
    """403 fuer jede schreibende Anfrage mit fremdem ``Origin`` (D1.2, Sicherheitsregel 6).

    Mit dem Sitzungs-Cookie reicht der Preflight allein nicht mehr gegen CSRF. Ohne ``Origin``
    (kein Browser: curl, Skripte) gibt es diesen Angriffsweg nicht, die Anfrage geht durch.
    """

    def __init__(self, app: ASGIApp, allowed: frozenset[str] = frozenset()) -> None:
        self.app = app
        self.allowed = allowed

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["method"] in MUTATING_METHODS:
            headers = Headers(scope=scope)
            origin = headers.get("origin")
            if origin is not None and not origin_allowed(origin, headers.get("host"), self.allowed):
                response = JSONResponse({"detail": "Fremde Herkunft (Origin)"}, status_code=403)
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)


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
