"""``/me/*``: das eigene Konto (D1.4, NUT-11).

Passwort und Anzeigename aendern, Sitzungen sehen und ueberall abmelden. Immer mit echter Sitzung,
auch im Uebergang ohne Sitzungspflicht und mit Einmal-Passwort (``session_user``): Hier ersetzt
ein Nutzer sein Einmal-Passwort.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response

from ..identity.service import LoginLocked, WeakPassword, WrongPassword
from ..models import Me, PasswordChange, ProfileUpdate, SessionInfo
from .auth import (
    ME_RESPONSES,
    Identity,
    SessionUser,
    Settings,
    disconnect,
    me_of,
    session_hash,
)

router = APIRouter(tags=["account"])

PASSWORD_RESPONSES: dict[int | str, dict[str, Any]] = {
    400: {"description": "Bisheriges Passwort falsch oder neues zu schwach"},
    429: {"description": "Zu viele Fehlversuche, voruebergehend gesperrt"},
    **ME_RESPONSES,
}


@router.put("/me/password", status_code=204, responses=PASSWORD_RESPONSES)
def change_password(
    body: PasswordChange,
    request: Request,
    user: SessionUser,
    identity: Identity,
    settings: Settings,
) -> None:
    """Ersetzt das eigene Passwort. Alle anderen Sitzungen enden, diese bleibt."""
    try:
        revoked = identity.change_password(
            user,
            body.current_password,
            body.new_password,
            session=session_hash(request, settings),
        )
    except LoginLocked as e:
        raise HTTPException(
            status_code=429,
            detail="Zu viele Fehlversuche. Bitte in 15 Minuten erneut versuchen.",
            headers={"Retry-After": str(e.retry_after_seconds)},
        ) from e
    except WrongPassword as e:
        raise HTTPException(status_code=400, detail="Das bisherige Passwort stimmt nicht.") from e
    except WeakPassword as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    disconnect(request, revoked)


@router.put("/me/profile", responses=ME_RESPONSES)
def update_profile(body: ProfileUpdate, user: SessionUser, identity: Identity) -> Me:
    """Aendert den Anzeigenamen; leer entfernt ihn."""
    return me_of(identity.set_display_name(user, body.display_name))


@router.get("/me/sessions", responses=ME_RESPONSES)
def list_sessions(
    request: Request, user: SessionUser, identity: Identity, settings: Settings
) -> list[SessionInfo]:
    """Die gueltigen eigenen Sitzungen, zuletzt aktive zuerst."""
    return [
        SessionInfo(
            created_at=s.created_at,
            last_seen=s.last_seen,
            expires_at=s.expires_at,
            user_agent=s.user_agent,
            current=s.current,
        )
        for s in identity.active_sessions(user, current=session_hash(request, settings))
    ]


@router.post("/me/sessions/revoke-all", status_code=204, responses=ME_RESPONSES)
def revoke_all_sessions(
    request: Request, response: Response, user: SessionUser, identity: Identity, settings: Settings
) -> None:
    """Ueberall abmelden, auch hier; trennt die WebSockets aller Sitzungen."""
    disconnect(request, identity.revoke_all(user))
    response.delete_cookie(
        settings.cookie_name,
        path="/",
        secure=settings.cookie_secure,
        httponly=True,
        samesite="strict",
    )
