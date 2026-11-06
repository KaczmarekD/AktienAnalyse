"""``/auth`` und ``/me``: Anmelden, Abmelden, eigenes Konto (D1.1, ADR-0012).

Das Cookie enthaelt nur eine zufaellige Sitzungs-ID (``HttpOnly``, ``SameSite=Strict``, mit HTTPS
``Secure`` und Name ``__Host-va_session``). Die Datenbank kennt nur ihren SHA-256. Ohne
``WEB_API_IDENTITY_DATABASE_URL`` antworten die Endpunkte mit 503. Die Sitzungspflicht fuer die
uebrigen Endpunkte kommt mit D1.2; ``CurrentUser`` ist die Abhaengigkeit dafuer.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from ..identity.service import IdentityService, LoginFailed, LoginLocked, User
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


def current_user(request: Request, identity: Identity, settings: Settings) -> User:
    """Der angemeldete Nutzer, sonst 401."""
    user = identity.authenticate(request.cookies.get(settings.cookie_name))
    if user is None:
        raise HTTPException(status_code=401, detail="Nicht angemeldet")
    return user


CurrentUser = Annotated[User, Depends(current_user)]


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
    """Beendet die Sitzung auf dem Server und loescht das Cookie im Browser."""
    identity.logout(request.cookies.get(settings.cookie_name))
    response.delete_cookie(
        settings.cookie_name,
        path="/",
        secure=settings.cookie_secure,
        httponly=True,
        samesite="strict",
    )


@router.get("/me", responses=ME_RESPONSES)
def me(user: CurrentUser) -> Me:
    """Das eigene Konto."""
    return Me(
        id=user.id,
        username=user.username,
        role=user.role,  # type: ignore[arg-type]
        display_name=user.display_name,
        email=user.email,
    )
