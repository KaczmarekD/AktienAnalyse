"""``/admin/users``: Nutzerverwaltung (D1.4, Rollen in docs/architecture/depot/nutzer.md).

Nur mit echter Admin-Sitzung, auch im Uebergang ohne Sitzungspflicht (``session_admin``). Ein Admin
vergibt Einmal-Passwoerter, der Nutzer ersetzt sie bei der ersten Anmeldung. Der Server schickt
nie ein Passwort zurueck. Am eigenen Konto deaktiviert und setzt ein Admin hier nichts zurueck.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from ..identity.domain import InvalidUsername
from ..identity.ports import UserExists
from ..identity.service import Account as AccountRecord
from ..identity.service import OwnAccount, UnknownUser
from ..models import Account, NewAccount, PasswordReset
from .auth import FORBIDDEN, ME_RESPONSES, Identity, SessionAdmin, disconnect, session_admin

router = APIRouter(
    prefix="/admin/users",
    tags=["admin"],
    dependencies=[Depends(session_admin)],
    responses={**ME_RESPONSES, **FORBIDDEN},
)

CHANGE_RESPONSES: dict[int | str, dict[str, Any]] = {
    404: {"description": "Konto unbekannt"},
    409: {"description": "Nicht am eigenen Konto"},
}


def _account(record: AccountRecord) -> Account:
    return Account(
        id=record.id,
        username=record.username,
        role=record.role,  # type: ignore[arg-type]
        display_name=record.display_name,
        email=record.email,
        active=record.active,
        must_change_password=record.must_change_password,
        created_at=record.created_at,
    )


@router.get("")
def list_users(identity: Identity) -> list[Account]:
    """Alle Konten in der Reihenfolge, in der sie angelegt wurden."""
    return [_account(record) for record in identity.accounts()]


@router.post(
    "",
    status_code=201,
    responses={
        400: {"description": "Name, Mail-Adresse oder Einmal-Passwort ungueltig"},
        409: {"description": "Den Benutzernamen gibt es schon"},
    },
)
def create_user(body: NewAccount, identity: Identity) -> Account:
    """Legt ein Konto mit Einmal-Passwort an."""
    try:
        record = identity.create_account(
            body.username,
            body.one_time_password,
            role=body.role,
            display_name=body.display_name,
            email=body.email,
        )
    except UserExists as e:
        raise HTTPException(status_code=409, detail="Den Benutzernamen gibt es schon.") from e
    except (InvalidUsername, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return _account(record)


def _change(request: Request, action: Any) -> None:
    try:
        revoked = action()
    except UnknownUser as e:
        raise HTTPException(status_code=404, detail="Konto unbekannt") from e
    except OwnAccount as e:
        raise HTTPException(
            status_code=409, detail="Das eigene Konto geht hier nicht, nur unter „Konto“."
        ) from e
    except ValueError as e:  # schwaches Einmal-Passwort
        raise HTTPException(status_code=400, detail=str(e)) from e
    disconnect(request, revoked)


@router.post("/{user_id}/disable", status_code=204, responses=CHANGE_RESPONSES)
def disable_user(user_id: int, request: Request, admin: SessionAdmin, identity: Identity) -> None:
    """Deaktiviert ein Konto; alle seine Sitzungen enden."""
    _change(request, lambda: identity.set_active(admin, user_id, active=False))


@router.post("/{user_id}/enable", status_code=204, responses=CHANGE_RESPONSES)
def enable_user(user_id: int, request: Request, admin: SessionAdmin, identity: Identity) -> None:
    """Aktiviert ein Konto wieder; es braucht eine neue Anmeldung."""
    _change(request, lambda: identity.set_active(admin, user_id, active=True))


@router.post(
    "/{user_id}/reset-password",
    status_code=204,
    responses={**CHANGE_RESPONSES, 400: {"description": "Einmal-Passwort zu schwach"}},
)
def reset_password(
    user_id: int, body: PasswordReset, request: Request, admin: SessionAdmin, identity: Identity
) -> None:
    """Setzt ein Einmal-Passwort; alle Sitzungen des Kontos enden."""
    _change(request, lambda: identity.reset_password(admin, user_id, body.one_time_password))
