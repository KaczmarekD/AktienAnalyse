"""``/me/*``: das eigene Konto (D1.4, NUT-11).

Passwort und Anzeigename aendern, Sitzungen sehen und ueberall abmelden. Immer mit echter Sitzung,
auch im Uebergang ohne Sitzungspflicht und mit Einmal-Passwort (``session_user``): Hier ersetzt
ein Nutzer sein Einmal-Passwort.

Seit D1.6: neue Mail-Adresse mit Bestaetigung per Link (NUT-10) und Export aller eigenen Daten
(NUT-12).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

from fastapi import APIRouter, BackgroundTasks, FastAPI, HTTPException, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from ..identity.service import (
    InvalidEmail,
    LoginLocked,
    NoLinkBase,
    TooManyConfirmations,
    WeakPassword,
    WrongPassword,
)
from ..models import DataExport, Me, PasswordChange, ProfileUpdate, SessionInfo
from .auth import (
    ME_RESPONSES,
    Identity,
    SessionUser,
    Settings,
    disconnect,
    me_of,
    session_hash,
)

if TYPE_CHECKING:
    from ..settings import WebApiSettings

router = APIRouter(tags=["account"])
log = logging.getLogger(__name__)

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


PROFILE_RESPONSES: dict[int | str, dict[str, Any]] = {
    400: {"description": "Keine gueltige Mail-Adresse oder Adresse des UI unbekannt"},
    429: {"description": "Zu viele Bestaetigungsmails, spaeter erneut versuchen"},
    **ME_RESPONSES,
}


def _link_base(request: Request, settings: WebApiSettings) -> str | None:
    """Wo das UI liegt, fuer den Link in der Mail (D1.6): die Herkunft dieser Anfrage, die
    ``OriginCheckMiddleware`` schon geprueft hat, sonst ``WEB_API_ALLOWED_ORIGINS``, wenn es dort
    genau eine gibt. Bei mehreren waere unklar, welche der Nutzer erreicht."""
    origin = request.headers.get("origin")
    if not origin:
        return next(iter(settings.origins)) if len(settings.origins) == 1 else None
    # Nur aus den Bestandteilen, nie den Header unveraendert (er landet in der Mail)
    parts = urlsplit(origin.strip().lower())
    return f"{parts.scheme}://{parts.netloc}"


@router.put("/me/profile", responses=PROFILE_RESPONSES)
def update_profile(
    body: ProfileUpdate,
    request: Request,
    background: BackgroundTasks,
    user: SessionUser,
    identity: Identity,
    settings: Settings,
) -> Me:
    """Aendert den Anzeigenamen (leer entfernt ihn) und fordert fuer eine neue Mail-Adresse
    die Bestaetigung an. Bis zum Link aus der Mail gilt die bisherige (``pending_email``)."""
    if body.email is not None:
        try:
            identity.change_email(user, body.email, link_base=_link_base(request, settings))
        except InvalidEmail as e:
            raise HTTPException(status_code=400, detail="Keine gueltige Mail-Adresse.") from e
        except NoLinkBase as e:
            raise HTTPException(
                status_code=400,
                detail="Die Adresse des UI ist unbekannt, der Link fuer die Mail fehlt.",
            ) from e
        except TooManyConfirmations as e:
            raise HTTPException(
                status_code=429,
                detail="Zu viele Bestaetigungsmails. Bitte in einer Stunde erneut versuchen.",
                headers={"Retry-After": str(e.retry_after_seconds)},
            ) from e
        # Erst nach der Antwort: Ist NATS langsam, wartet die Anfrage nicht darauf
        background.add_task(publish_confirmations, request.app)
    return me_of(identity.set_display_name(user, body.display_name), identity)


def publish_confirmations(app: FastAPI) -> None:
    """Schickt die Bestaetigungsmail gleich los, sobald der Event-Bus laeuft; sonst holt
    der Takt des web-api sie aus der Outbox (``main._keep_identity_outbox``)."""
    events = getattr(app.state, "events", None)
    identity = getattr(app.state, "identity", None)
    if events is None or identity is None:
        return
    try:
        identity.publish_pending(events.publish)
    except Exception:
        log.warning("Outbox von identity nicht geleert, der Takt versucht es erneut", exc_info=True)


@router.get(
    "/me/export",
    response_model=DataExport,
    responses={
        200: {"description": "JSON-Datei zum Herunterladen"},
        **ME_RESPONSES,
    },
)
def export_data(user: SessionUser, identity: Identity) -> JSONResponse:
    """Alle eigenen Daten als JSON-Datei (NUT-12), ohne Hashes und Tokens."""
    now = identity.now()
    data = DataExport(exported_at=now, **identity.export(user))
    filename = f"va-daten-{user.username}-{now:%Y-%m-%d}.json"
    return JSONResponse(
        jsonable_encoder(data),
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


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
