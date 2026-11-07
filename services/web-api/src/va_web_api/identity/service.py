"""Anmeldung, Sitzungen und Konten (D1.1): der Anwendungsfall ueber dem Port ``IdentityStore``.

Regeln aus docs/architecture/depot/nutzer.md:
- Falsches Passwort, unbekannter Name und deaktiviertes Konto sehen von aussen gleich aus. Fuer
  einen unbekannten Namen wird trotzdem ein Hash geprueft, damit die Antwortzeit nichts verraet.
- Ab 5 Fehlversuchen je Konto oder IP ist 15 Minuten gesperrt, auch fuer das richtige Passwort.
- Jeder Versuch steht in ``login_event``, ohne Passwort.

Seit D1.4 (NUT-11, Rollen): Passwort und Anzeigename aendern, Sitzungen sehen und widerrufen,
Konten verwalten. Ein falsches bisheriges Passwort zaehlt wie ein Fehlversuch beim Anmelden. Ein
Admin vergibt Einmal-Passwoerter (``must_change``), am eigenen Konto aber nicht.

Seit D1.6 (NUT-10, NUT-12): Eine neue Mail-Adresse gilt erst nach dem Link aus der Mail
(einmalig, 24 h, nur die juengste Anfrage). Das Event fuer die Mail geht mit der Anfrage in
einer Transaktion in die Outbox. Export aller eigenen Zeilen ohne Hashes.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import cached_property
from typing import Any

from va_contracts import Envelope, new_envelope
from va_contracts.events.v1 import (
    EMAIL_CONFIRMATION_REQUESTED,
    EmailConfirmationRequestedV1,
)

from .domain import (
    EMAIL_CONFIRMATION_LIMIT,
    EMAIL_CONFIRMATION_VALIDITY,
    EMAIL_CONFIRMATION_WINDOW,
    ROLES,
    LockoutPolicy,
    PasswordHasher,
    SessionPolicy,
    new_session_token,
    normalize_username,
    password_problems,
    token_hash,
    valid_email,
)
from .ports import IdentityStore, UserRecord

SOURCE = "va/web-api"


class LoginFailed(Exception):
    """Name, Passwort oder Konto passen nicht; bewusst ohne Angabe, was davon."""


class LoginLocked(Exception):
    """Zu viele Fehlversuche fuer das Konto oder die IP-Adresse."""

    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__(retry_after_seconds)
        self.retry_after_seconds = retry_after_seconds


class WeakPassword(ValueError):
    def __init__(self, problems: list[str]) -> None:
        super().__init__("Passwort: " + "; ".join(problems))
        self.problems = problems


class WrongPassword(Exception):
    """Das bisherige Passwort stimmt nicht (Passwort aendern, D1.4)."""


class UnknownUser(LookupError):
    """Kein Konto mit dieser ID."""


class InvalidEmail(ValueError):
    """Keine gueltige Mail-Adresse (D1.6)."""


class NoLinkBase(Exception):
    """Die Adresse des UI ist unbekannt, der Link fuer die Mail laesst sich nicht bauen."""


class TooManyConfirmations(Exception):
    """Zu viele Bestaetigungsmails in kurzer Zeit (D1.6)."""

    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__(retry_after_seconds)
        self.retry_after_seconds = retry_after_seconds


class InvalidConfirmation(Exception):
    """Link unbekannt, schon benutzt, abgeloest oder abgelaufen; bewusst ohne Angabe, was
    davon (D1.6)."""


class OwnAccount(Exception):
    """Ein Admin deaktiviert oder setzt sein eigenes Konto nicht zurueck: Es bliebe sonst
    womoeglich kein Admin uebrig, der sich anmelden kann."""


@dataclass(frozen=True)
class User:
    id: int
    username: str
    role: str
    display_name: str | None
    email: str | None
    must_change_password: bool = False  # D1.4: Einmal-Passwort, vor allem anderen zu ersetzen

    @classmethod
    def of(cls, record: UserRecord) -> User:
        return cls(
            record.id,
            record.username,
            record.role,
            record.display_name,
            record.email,
            must_change_password=record.must_change,
        )


@dataclass(frozen=True)
class Account:
    """Ein Konto, wie es ein Admin sieht (D1.4), ohne Passwort-Hash."""

    id: int
    username: str
    role: str
    display_name: str | None
    email: str | None
    active: bool
    must_change_password: bool
    created_at: datetime | None

    @classmethod
    def of(cls, record: UserRecord) -> Account:
        return cls(
            record.id,
            record.username,
            record.role,
            record.display_name,
            record.email,
            record.active,
            record.must_change,
            record.created_at,
        )


@dataclass(frozen=True)
class ActiveSession:
    """Eine gueltige Sitzung des eigenen Kontos (D1.4), ohne ihre ID."""

    created_at: datetime
    last_seen: datetime
    expires_at: datetime
    user_agent: str | None
    current: bool


# D1.2, Uebergang bis D1.4/D1.5 (WEB_API_AUTH_REQUIRED=false): wie unter ADR-0007 darf jeder im
# LAN alles, als waere ein Admin angemeldet. ID 0 gehoert keinem echten Konto.
LAN_USER = User(id=0, username="lan", role="admin", display_name=None, email=None)


@dataclass(frozen=True)
class LoginResult:
    token: str  # nur fuer das Cookie, gespeichert wird sein Hash
    user: User
    expires_at: datetime


HASH_SLOTS = 2


def _utcnow() -> datetime:
    return datetime.now(UTC)


class IdentityService:
    def __init__(
        self,
        store: IdentityStore,
        *,
        hasher: PasswordHasher | None = None,
        sessions: SessionPolicy | None = None,
        lockout: LockoutPolicy | None = None,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._store = store
        self._hasher = hasher or PasswordHasher()
        self.sessions = sessions or SessionPolicy()
        self.lockout = lockout or LockoutPolicy()
        self._clock = clock
        # Ein scrypt-Hash belegt 128 MiB: hoechstens zwei zugleich, egal wie viele Anfragen kommen
        self._hash_slots = threading.BoundedSemaphore(HASH_SLOTS)

    def now(self) -> datetime:
        return self._clock()

    @cached_property
    def _dummy_hash(self) -> str:
        """Hash fuer unbekannte Namen: dieselbe Rechenzeit wie bei einem echten Konto."""
        return self._hash(new_session_token())

    def _hash(self, password: str) -> str:
        with self._hash_slots:
            return self._hasher.hash(password)

    def _verify(self, password: str, encoded: str) -> bool:
        with self._hash_slots:
            return self._hasher.verify(password, encoded)

    def create_user(
        self,
        username: str,
        password: str,
        *,
        role: str = "user",
        display_name: str | None = None,
        email: str | None = None,
        must_change: bool = False,
    ) -> User:
        """Wirft ``InvalidUsername``, ``WeakPassword``, ``UserExists`` oder ``ValueError``.

        ``must_change``: ein Einmal-Passwort, das der Nutzer vor allem anderen ersetzt (D1.4).
        """
        name = normalize_username(username)
        if role not in ROLES:
            msg = f"Rolle {role!r} gibt es nicht ({', '.join(ROLES)})"
            raise ValueError(msg)
        problems = password_problems(password, username=name)
        if problems:
            raise WeakPassword(problems)
        email = email.strip() if email else None
        display = display_name.strip() if display_name else None
        if email is not None and not valid_email(email):
            msg = f"Keine gueltige Mail-Adresse: {email!r}"
            raise ValueError(msg)
        user_id = self._store.create_user(
            username=name,
            role=role,
            password_hash=self._hash(password),
            display_name=display,
            email=email,
            at=self.now(),
            must_change=must_change,
        )
        return User(user_id, name, role, display, email, must_change_password=must_change)

    def _ensure_not_locked(self, name: str, ip: str | None, now: datetime) -> None:
        failures = self._store.count_failures(
            username=name, ip=ip, since=self.lockout.since(now), now=now
        )
        if self.lockout.is_locked(failures):
            self._log(name, None, ip, "locked", now)
            raise LoginLocked(int(self.lockout.window.total_seconds()))

    def login(
        self, username: str, password: str, *, ip: str | None, user_agent: str | None = None
    ) -> LoginResult:
        now = self.now()
        name = username.strip().lower()
        self._ensure_not_locked(name, ip, now)
        record = self._store.find_user(name)
        if record is None or record.password_hash is None:
            self._verify(password, self._dummy_hash)
            self._log(name, None, ip, "unknown_user", now)
            raise LoginFailed
        if not self._verify(password, record.password_hash):
            self._log(name, record.id, ip, "wrong_password", now)
            raise LoginFailed
        if not record.active:
            self._log(name, record.id, ip, "disabled", now)
            raise LoginFailed
        token = new_session_token()
        expires_at = self.sessions.expires_at(now)
        self._store.create_session(
            id_hash=token_hash(token),
            user_id=record.id,
            created_at=now,
            expires_at=expires_at,
            user_agent=(user_agent or "")[:300] or None,
            ip=ip,
        )
        self._log(name, record.id, ip, "ok", now)
        return LoginResult(token=token, user=User.of(record), expires_at=expires_at)

    def authenticate(self, token: str | None, *, touch: bool = True) -> User | None:
        """Der Nutzer einer gueltigen Sitzung, sonst ``None``.

        Mit ``touch`` (Anfragen) verlaengert sie die Inaktivitaetsfrist. Die Pruefung offener
        WebSockets (D1.3) laeuft ohne: Ein offener Tab ist keine Aktivitaet.
        """
        if not token:
            return None
        now = self.now()
        id_hash = token_hash(token)
        session = self._store.find_session(id_hash)
        if session is None or not self.sessions.is_active(
            expires_at=session.expires_at,
            last_seen=session.last_seen,
            revoked=session.revoked,
            now=now,
        ):
            return None
        record = self._store.get_user(session.user_id)
        if record is None or not record.active:
            return None
        if touch and self.sessions.needs_touch(session.last_seen, now):
            self._store.touch_session(id_hash, at=now)
        return User.of(record)

    def logout(self, token: str | None) -> None:
        if not token:
            return
        id_hash = token_hash(token)
        if self._store.find_session(id_hash) is not None:
            self._store.revoke_session(id_hash, reason="logout", at=self.now())

    # --- eigenes Konto (D1.4, NUT-11) ---

    def change_password(
        self, user: User, current: str, new: str, *, session: str | None
    ) -> list[str]:
        """Ersetzt das Passwort und widerruft alle anderen Sitzungen; gibt deren Hashes zurueck.

        Wirft ``LoginLocked``, ``WrongPassword`` (zaehlt als Fehlversuch) oder ``WeakPassword``.
        ``session`` ist der Hash der Sitzung, die bleibt.

        Fehlversuche zaehlen nur fuer das Konto, nicht fuer die IP-Adresse: Hinter nginx teilen
        sich bis D1.5 alle eine Adresse, die Vertipper eines Angemeldeten sperrten sonst jede
        Anmeldung. Wer die Sitzung hat, kann ohnehin nur dieses Konto angreifen.
        """
        now = self.now()
        self._ensure_not_locked(user.username, None, now)
        record = self._store.get_user(user.id)
        if (
            record is None
            or record.password_hash is None
            or not self._verify(current, record.password_hash)
        ):
            self._log(user.username, user.id, None, "wrong_password", now)
            raise WrongPassword
        problems = password_problems(new, username=user.username)
        if new == current:
            problems.append("Das neue Passwort muss sich vom bisherigen unterscheiden")
        if problems:
            raise WeakPassword(problems)
        self._store.set_password(user.id, self._hash(new), must_change=False, at=now)
        return self._store.revoke_sessions(user.id, reason="password_changed", at=now, keep=session)

    def set_display_name(self, user: User, display_name: str | None) -> User:
        name = display_name.strip() if display_name else None
        self._store.set_display_name(user.id, name or None, at=self.now())
        record = self._store.get_user(user.id)
        if record is None:
            raise UnknownUser(user.id)
        return User.of(record)

    # --- Mail-Adresse und Export (D1.6, NUT-10, NUT-12) ---

    def change_email(self, user: User, email: str, *, link_base: str | None) -> bool:
        """Fordert die Bestaetigung einer neuen Adresse an; ``False``, wenn es schon die
        bisherige ist. Die neue gilt erst nach ``confirm_email``.

        ``link_base`` ist die Adresse des UI (``https://va.example``), der Link zeigt auf
        ``/confirm-email`` dort. Wirft ``InvalidEmail``, ``NoLinkBase`` oder
        ``TooManyConfirmations`` (hoechstens ``EMAIL_CONFIRMATION_LIMIT`` je Stunde).
        """
        address = email.strip()
        if not valid_email(address):
            raise InvalidEmail(address)
        if user.email is not None and address.lower() == user.email.lower():
            return False
        if not link_base:
            raise NoLinkBase
        now = self.now()
        recent = self._store.count_email_confirmations(
            user.id, since=now - EMAIL_CONFIRMATION_WINDOW
        )
        if recent >= EMAIL_CONFIRMATION_LIMIT:
            raise TooManyConfirmations(int(EMAIL_CONFIRMATION_WINDOW.total_seconds()))
        token = new_session_token()
        expires_at = now + EMAIL_CONFIRMATION_VALIDITY
        envelope: Envelope[Any] = new_envelope(
            EMAIL_CONFIRMATION_REQUESTED,
            EmailConfirmationRequestedV1(
                user_id=user.id,
                email=address,
                link=f"{link_base.rstrip('/')}/confirm-email?token={token}",
                expires_at=expires_at,
            ),
            source=SOURCE,
        )
        self._store.add_email_confirmation(
            user.id,
            email=address,
            token_hash=token_hash(token),
            expires_at=expires_at,
            at=now,
            envelope=envelope,
        )
        return True

    def confirm_email(self, token: str) -> None:
        """Die neue Adresse gilt ab jetzt. Wirft ``InvalidConfirmation``."""
        now = self.now()
        id_hash = token_hash(token)
        found = self._store.find_email_confirmation(id_hash)
        if found is None or found.used or not found.latest or now >= found.expires_at:
            raise InvalidConfirmation
        record = self._store.get_user(found.user_id)
        if record is None or not record.active:
            raise InvalidConfirmation
        if not self._store.confirm_email(id_hash, at=now):
            raise InvalidConfirmation  # gleichzeitig schon benutzt

    def pending_email(self, user: User) -> str | None:
        """Die Adresse, die auf ihre Bestaetigung wartet."""
        if user.id == LAN_USER.id:
            return None
        return self._store.pending_email(user.id, now=self.now())

    def export(self, user: User) -> dict[str, list[dict[str, Any]]]:
        """Alle eigenen Zeilen in ``identity``, ohne Hashes (NUT-12)."""
        return self._store.export(user.id)

    def publish_pending(self, publish: Callable[[Envelope[Any]], None]) -> int:
        """Sendet die offenen Events der Outbox; gibt die Anzahl zurueck."""
        return self._store.publish_pending(publish)

    def active_sessions(self, user: User, *, current: str | None) -> list[ActiveSession]:
        """Die gueltigen Sitzungen, zuletzt aktive zuerst. ``current``: Hash dieser Sitzung."""
        now = self.now()
        active = [
            s
            for s in self._store.list_sessions(user.id)
            if self.sessions.is_active(
                expires_at=s.expires_at, last_seen=s.last_seen, revoked=s.revoked, now=now
            )
        ]
        active.sort(key=lambda s: (s.last_seen, s.created_at), reverse=True)
        return [
            ActiveSession(
                s.created_at, s.last_seen, s.expires_at, s.user_agent, s.id_hash == current
            )
            for s in active
        ]

    def revoke_all(self, user: User) -> list[str]:
        """Ueberall abmelden, auch diese Sitzung; gibt die widerrufenen Hashes zurueck."""
        return self._store.revoke_sessions(user.id, reason="logout", at=self.now())

    # --- Konten verwalten (D1.4, nur Admins) ---

    def accounts(self) -> list[Account]:
        return [Account.of(record) for record in self._store.list_users()]

    def create_account(
        self,
        username: str,
        one_time_password: str,
        *,
        role: str = "user",
        display_name: str | None = None,
        email: str | None = None,
    ) -> Account:
        """Legt ein Konto mit Einmal-Passwort an; Fehler wie ``create_user``."""
        user = self.create_user(
            username,
            one_time_password,
            role=role,
            display_name=display_name,
            email=email,
            must_change=True,
        )
        return self._account(user.id)

    def reset_password(self, admin: User, user_id: int, one_time_password: str) -> list[str]:
        """Setzt ein Einmal-Passwort und widerruft alle Sitzungen des Kontos.

        Wirft ``UnknownUser``, ``OwnAccount`` oder ``WeakPassword``.
        """
        record = self._other(admin, user_id)
        problems = password_problems(one_time_password, username=record.username)
        if problems:
            raise WeakPassword(problems)
        now = self.now()
        self._store.set_password(user_id, self._hash(one_time_password), must_change=True, at=now)
        return self._store.revoke_sessions(user_id, reason="admin", at=now)

    def set_active(self, admin: User, user_id: int, *, active: bool) -> list[str]:
        """Aktiviert oder deaktiviert; Deaktivieren widerruft alle Sitzungen des Kontos.

        Wirft ``UnknownUser`` oder ``OwnAccount``.
        """
        if active:
            if self._store.get_user(user_id) is None:
                raise UnknownUser(user_id)
            self._store.set_status(user_id, "active", reason=None, at=self.now())
            return []
        self._other(admin, user_id)
        now = self.now()
        self._store.set_status(user_id, "disabled", reason="admin", at=now)
        return self._store.revoke_sessions(user_id, reason="disabled", at=now)

    def _other(self, admin: User, user_id: int) -> UserRecord:
        record = self._store.get_user(user_id)
        if record is None:
            raise UnknownUser(user_id)
        if record.id == admin.id:
            raise OwnAccount
        return record

    def _account(self, user_id: int) -> Account:
        record = self._store.get_user(user_id)
        if record is None:
            raise UnknownUser(user_id)
        return Account.of(record)

    def _log(
        self, name: str, user_id: int | None, ip: str | None, reason: str, at: datetime
    ) -> None:
        self._store.record_login(
            username=name[:64], user_id=user_id, ip=ip, ok=reason == "ok", reason=reason, at=at
        )
