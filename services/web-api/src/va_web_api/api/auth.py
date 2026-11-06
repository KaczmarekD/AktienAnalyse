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
from ..models import LoginRequest, Me, SessionState
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
# D1.4: Mit Einmal-Passwort geht nur das eigene Konto (``/me``) und Abmelden
MUST_CHANGE = "Bitte zuerst das Einmal-Passwort durch ein eigenes ersetzen."


def _authenticated(request: Request, identity: IdentityService, settings: WebApiSettings) -> User:
    user = identity.authenticate(request.cookies.get(settings.cookie_name))
    if user is None:
        raise HTTPException(status_code=401, detail="Nicht angemeldet")
    return user


def session_user(request: Request, identity: Identity, settings: Settings) -> User:
    """Der Nutzer einer echten Sitzung, sonst 401; auch im Uebergang und mit Einmal-Passwort
    (``/me``)."""
    return _authenticated(request, identity, settings)


def current_user(request: Request, settings: Settings) -> User:
    """Wer eine Anfrage stellt (D1.2). Ohne Sitzungspflicht ``LAN_USER``, sonst 401 ohne Sitzung
    und 403 mit Einmal-Passwort (D1.4)."""
    if not settings.auth_required:
        return LAN_USER
    user = _authenticated(request, _identity(request), settings)
    if user.must_change_password:
        raise HTTPException(status_code=403, detail=MUST_CHANGE)
    return user


def require_admin(user: Annotated[User, Depends(current_user)]) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Nur fuer Admins")
    return user


def session_admin(user: Annotated[User, Depends(session_user)]) -> User:
    """Ein Admin mit echter Sitzung, auch im Uebergang (Nutzerverwaltung, D1.4).

    Im Uebergang gilt sonst jeder im LAN als Admin und koennte das Passwort des echten Admins
    zuruecksetzen.
    """
    if user.must_change_password:
        raise HTTPException(status_code=403, detail=MUST_CHANGE)
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Nur fuer Admins")
    return user


def disconnect(request: Request, sessions: list[str]) -> None:
    """Trennt die WebSockets dieser Sitzungen (Hashes, D1.3). Die Endpunkte laufen im Threadpool,
    der Hub in der Event-Loop: deshalb ueber den Broadcaster."""
    broadcaster = getattr(request.app.state, "broadcaster", None)
    if broadcaster is not None:
        for session in sessions:
            broadcaster.close_session(session)


def session_hash(request: Request, settings: WebApiSettings) -> str | None:
    """Hash der Sitzung dieser Anfrage, falls ein Cookie da ist."""
    token = request.cookies.get(settings.cookie_name)
    return token_hash(token) if token else None


SessionUser = Annotated[User, Depends(session_user)]
CurrentUser = Annotated[User, Depends(current_user)]
Admin = Annotated[User, Depends(require_admin)]
SessionAdmin = Annotated[User, Depends(session_admin)]


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
    if token:
        disconnect(request, [token_hash(token)])  # D1.3
    response.delete_cookie(
        settings.cookie_name,
        path="/",
        secure=settings.cookie_secure,
        httponly=True,
        samesite="strict",
    )


def me_of(user: User) -> Me:
    return Me(
        id=user.id,
        username=user.username,
        role=user.role,  # type: ignore[arg-type]
        display_name=user.display_name,
        email=user.email,
        must_change_password=user.must_change_password,
    )


@router.get("/me", responses=ME_RESPONSES)
def me(user: SessionUser) -> Me:
    """Das eigene Konto."""
    return me_of(user)


@router.get("/auth/session")
def current_session(request: Request, settings: Settings) -> SessionState:
    """Wer angemeldet ist, ohne 401 (D1.4). Das UI fragt das bei jedem Start; ein 401 stuende
    sonst bei jedem Aufruf der Anmeldeseite als Fehler in der Konsole des Browsers."""
    identity: IdentityService | None = getattr(request.app.state, "identity", None)
    user = (
        None
        if identity is None
        else identity.authenticate(request.cookies.get(settings.cookie_name))
    )
    return SessionState(user=None if user is None else me_of(user))
