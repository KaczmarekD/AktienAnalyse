"""Port fuer Konten und Sitzungen (D1.1): was ``IdentityService`` vom Speicher braucht.

Umgesetzt von ``MemoryIdentityStore`` (Tests) und ``PostgresIdentityStore`` (Schema ``identity``,
Rolle ``va_identity``). Alle Zeitpunkte kommen vom Aufrufer, damit beide Speicher mit derselben
Uhr rechnen. Es gibt bewusst kein Loeschen: Konten werden deaktiviert, Sitzungen widerrufen.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from datetime import datetime

    from .domain import Failures


class UserExists(Exception):
    """Den Benutzernamen gibt es schon."""


@dataclass(frozen=True)
class UserRecord:
    id: int
    username: str
    role: str
    display_name: str | None
    email: str | None
    active: bool
    password_hash: str | None  # juengster Hash; None nur, wenn nie einer gesetzt wurde


@dataclass(frozen=True)
class SessionRecord:
    id_hash: str
    user_id: int
    created_at: datetime
    expires_at: datetime
    last_seen: datetime  # juengster Eintrag in session_seen, sonst created_at
    revoked: bool


class IdentityStore(Protocol):
    def create_user(
        self,
        *,
        username: str,
        role: str,
        password_hash: str,
        display_name: str | None,
        email: str | None,
        at: datetime,
    ) -> int:
        """Legt Konto, Profil, Status ``active`` und Passwort an; wirft ``UserExists``."""
        ...

    def find_user(self, username: str) -> UserRecord | None: ...

    def get_user(self, user_id: int) -> UserRecord | None: ...

    def set_status(self, user_id: int, status: str, *, reason: str | None, at: datetime) -> None:
        """Neuer Status als neue Zeile; gueltig ist die juengste."""
        ...

    def record_login(
        self,
        *,
        username: str,
        user_id: int | None,
        ip: str | None,
        ok: bool,
        reason: str,
        at: datetime,
    ) -> None: ...

    def count_failures(
        self, *, username: str, ip: str | None, since: datetime, now: datetime
    ) -> Failures:
        """Fehlversuche (``FAILURE_REASONS``) zwischen ``since`` und ``now``: je Konto seit
        seinem letzten Erfolg, je IP seit dem letzten Erfolg von dort."""
        ...

    def create_session(
        self,
        *,
        id_hash: str,
        user_id: int,
        created_at: datetime,
        expires_at: datetime,
        user_agent: str | None,
        ip: str | None,
    ) -> None: ...

    def find_session(self, id_hash: str) -> SessionRecord | None: ...

    def touch_session(self, id_hash: str, *, at: datetime) -> None: ...

    def revoke_session(self, id_hash: str, *, reason: str, at: datetime) -> None:
        """Widerruft eine Sitzung; ein zweiter Widerruf aendert nichts."""
        ...
