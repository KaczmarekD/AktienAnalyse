"""``/auth`` und ``/me``: Anmelden, Abmelden, eigenes Konto (D1.1, ADR-0012).

Das Cookie enthaelt nur eine zufaellige Sitzungs-ID (``HttpOnly``, ``SameSite=Strict``, mit HTTPS
``Secure`` und Name ``__Host-va_session``). Die Datenbank kennt nur ihren SHA-256. Ohne
``WEB_API_IDENTITY_DATABASE_URL`` antworten die Endpunkte mit 503.

Seit D1.2 verlangen die uebrigen Router eine Sitzung (``current_user``, eingebunden in
``main.create_app``), Run-Start und Profil-Befehle zusaetzlich die Rolle Admin (``Admin``).
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from ..identity.domain import token_hash
from ..identity.service import LAN_USER, IdentityService, LoginFailed, LoginLocked, User
from ..models import LoginRequest, Me
from ..settings import WebApiSettings

router = APIRouter(tags=["auth"])

UNAVAILABLE: dict[int | str, dict[str, Any]] = {
    503: {"description": "Anmeldung nicht eingerichtet (ohne Identitaets-Datenbank)"}
}
LOGIN_RESPONSES: dict[int | str, dict[str, Any]] = {
    401: {"description": "Benutzername oder Passwort falsch"},
    429: {"description": "Zu viele Fehlversuche, voruebergehend gesperrt"},
    **UNAVAILABLE,
}
ME_RESPONSES: dict[int | str, dict[str, Any]] = {
    401: {"description": "Nicht angemeldet"},
    **UNAVAILABLE,
}


def _identity(request: Request) -> IdentityService:
    service = getattr(request.app.state, "identity", None)
    if service is None:
        raise HTTPException(status_code=503, detail="Anmeldung ist nicht eingerichtet")
    return service


def _settings(request: Request) -> WebApiSettings:
    return request.app.state.settings


Identity = Annotated[IdentityService, Depends(_identity)]
Settings = Annotated[WebApiSettings, Depends(_settings)]


UNAUTHORIZED: dict[int | str, dict[str, Any]] = {401: {"description": "Nicht angemeldet"}}
FORBIDDEN: dict[int | str, dict[str, Any]] = {403: {"description": "Nur fuer Admins"}}


def _authenticated(request: Request, identity: IdentityService, settings: WebApiSettings) -> User:
    user = identity.authenticate(request.cookies.get(settings.cookie_name))
    if user is None:
        raise HTTPException(status_code=401, detail="Nicht angemeldet")
    return user


def session_user(request: Request, identity: Identity, settings: Settings) -> User:
    """Der Nutzer einer echten Sitzung, sonst 401; auch im Uebergang (``/me``)."""
    return _authenticated(request, identity, settings)


def current_user(request: Request, settings: Settings) -> User:
    """Wer eine Anfrage stellt (D1.2). Ohne Sitzungspflicht ``LAN_USER``, sonst 401 ohne Sitzung."""
    if not settings.auth_required:
        return LAN_USER
    return _authenticated(request, _identity(request), settings)


def require_admin(user: Annotated[User, Depends(current_user)]) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Nur fuer Admins")
    return user


SessionUser = Annotated[User, Depends(session_user)]
CurrentUser = Annotated[User, Depends(current_user)]
Admin = Annotated[User, Depends(require_admin)]


@router.post("/auth/login", status_code=204, responses=LOGIN_RESPONSES)
def login(
    body: LoginRequest, request: Request, response: Response, identity: Identity, settings: Settings
) -> None:
    """Meldet an und setzt das Sitzungs-Cookie."""
    client = request.client.host if request.client else None
    try:
        result = identity.login(
            body.username,
            body.password,
            ip=client,
            user_agent=request.headers.get("user-agent"),
        )
    except LoginLocked as e:
        raise HTTPException(
            status_code=429,
            detail="Zu viele Fehlversuche. Bitte in 15 Minuten erneut versuchen.",
            headers={"Retry-After": str(e.retry_after_seconds)},
        ) from e
    except LoginFailed as e:
        raise HTTPException(status_code=401, detail="Benutzername oder Passwort falsch") from e
    response.set_cookie(
        settings.cookie_name,
        result.token,
        max_age=int(identity.sessions.absolute.total_seconds()),
        path="/",
        secure=settings.cookie_secure,
        httponly=True,
        samesite="strict",
    )


@router.post("/auth/logout", status_code=204, responses=UNAVAILABLE)
def logout(request: Request, response: Response, identity: Identity, settings: Settings) -> None:
    """Beendet die Sitzung auf dem Server, trennt ihre WebSockets und loescht das Cookie."""
    token = request.cookies.get(settings.cookie_name)
    identity.logout(token)
    broadcaster = getattr(request.app.state, "broadcaster", None)
    if token and broadcaster is not None:
        # D1.3: Der Logout laeuft im Threadpool, der Hub in der Event-Loop
        broadcaster.close_session(token_hash(token))
    response.delete_cookie(
        settings.cookie_name,
        path="/",
        secure=settings.cookie_secure,
        httponly=True,
        samesite="strict",
    )


@router.get("/me", responses=ME_RESPONSES)
def me(user: SessionUser) -> Me:
    """Das eigene Konto."""
    return Me(
        id=user.id,
        username=user.username,
        role=user.role,  # type: ignore[arg-type]
        display_name=user.display_name,
        email=user.email,
    )
