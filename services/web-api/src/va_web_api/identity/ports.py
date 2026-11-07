"""Port fuer Konten und Sitzungen (D1.1): was ``IdentityService`` vom Speicher braucht.

Umgesetzt von ``MemoryIdentityStore`` (Tests) und ``PostgresIdentityStore`` (Schema ``identity``,
Rolle ``va_identity``). Alle Zeitpunkte kommen vom Aufrufer, damit beide Speicher mit derselben
Uhr rechnen. Es gibt bewusst kein Loeschen: Konten werden deaktiviert, Sitzungen widerrufen.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime

    from va_contracts import Envelope

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
    must_change: bool = False  # D1.4: Einmal-Passwort, vor allem anderen zu ersetzen
    created_at: datetime | None = None


@dataclass(frozen=True)
class SessionRecord:
    id_hash: str
    user_id: int
    created_at: datetime
    expires_at: datetime
    last_seen: datetime  # juengster Eintrag in session_seen, sonst created_at
    revoked: bool
    user_agent: str | None = None


@dataclass(frozen=True)
class EmailConfirmationRecord:
    """Eine Anfrage, eine neue Mail-Adresse zu bestaetigen (D1.6)."""

    user_id: int
    email: str
    expires_at: datetime
    created_at: datetime
    used: bool  # schon bestaetigt: einmalig
    latest: bool  # die juengste Anfrage dieses Nutzers; aeltere Links gelten nicht mehr


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
        must_change: bool = False,
    ) -> int:
        """Legt Konto, Profil, Status ``active`` und Passwort an; wirft ``UserExists``."""
        ...

    def find_user(self, username: str) -> UserRecord | None: ...

    def get_user(self, user_id: int) -> UserRecord | None: ...

    def list_users(self) -> list[UserRecord]:
        """Alle Konten in der Reihenfolge, in der sie angelegt wurden (D1.4)."""
        ...

    def set_status(self, user_id: int, status: str, *, reason: str | None, at: datetime) -> None:
        """Neuer Status als neue Zeile; gueltig ist die juengste."""
        ...

    def set_password(
        self, user_id: int, password_hash: str, *, must_change: bool, at: datetime
    ) -> None:
        """Neues Passwort als neue Zeile; gueltig ist die juengste (D1.4)."""
        ...

    def set_display_name(self, user_id: int, display_name: str | None, *, at: datetime) -> None:
        """Neue Profil-Version mit diesem Namen; Mail-Adresse und Bestaetigung bleiben (D1.4)."""
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

    def list_sessions(self, user_id: int) -> list[SessionRecord]:
        """Alle Sitzungen eines Nutzers, auch abgelaufene und widerrufene (D1.4)."""
        ...

    def revoke_sessions(
        self, user_id: int, *, reason: str, at: datetime, keep: str | None = None
    ) -> list[str]:
        """Widerruft alle offenen Sitzungen eines Nutzers ausser ``keep``; gibt ihre Hashes
        zurueck (D1.4), damit der Hub ihre WebSockets trennen kann."""
        ...

    # --- D1.6: Mail-Adresse bestaetigen, Export ---

    def add_email_confirmation(
        self,
        user_id: int,
        *,
        email: str,
        token_hash: str,
        expires_at: datetime,
        at: datetime,
        envelope: Envelope[Any] | None,
    ) -> None:
        """Legt die Anfrage an und, in derselben Transaktion, das Event fuer die Mail in die
        Outbox (``envelope``)."""
        ...

    def find_email_confirmation(self, token_hash: str) -> EmailConfirmationRecord | None: ...

    def count_email_confirmations(self, user_id: int, *, since: datetime) -> int:
        """Wie viele Anfragen der Nutzer seit ``since`` gestellt hat (Begrenzung)."""
        ...

    def confirm_email(self, token_hash: str, *, at: datetime) -> bool:
        """Bestaetigt einmalig: neue Profil-Version mit der Adresse und ``email_confirmed_at``.
        ``False``, wenn der Link schon benutzt wurde."""
        ...

    def pending_email(self, user_id: int, *, now: datetime) -> str | None:
        """Die Adresse der juengsten offenen, noch gueltigen Anfrage."""
        ...

    def export(self, user_id: int) -> dict[str, list[dict[str, Any]]]:
        """Alle Zeilen des Nutzers in ``identity``, ohne Hashes (NUT-12)."""
        ...

    def publish_pending(self, publish: Callable[[Envelope[Any]], None]) -> int:
        """Gibt die offenen Events der Outbox an ``publish``, in Reihenfolge; jedes gilt
        danach als gesendet. Wirft ``publish``, bleibt es mit allen spaeteren offen."""
        ...
