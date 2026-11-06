"""Anmeldung, Sitzungen und Konten (D1.1): der Anwendungsfall ueber dem Port ``IdentityStore``.

Regeln aus docs/architecture/depot/nutzer.md:
- Falsches Passwort, unbekannter Name und deaktiviertes Konto sehen von aussen gleich aus. Fuer
  einen unbekannten Namen wird trotzdem ein Hash geprueft, damit die Antwortzeit nichts verraet.
- Ab 5 Fehlversuchen je Konto oder IP ist 15 Minuten gesperrt, auch fuer das richtige Passwort.
- Jeder Versuch steht in ``login_event``, ohne Passwort.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import cached_property

from .domain import (
    ROLES,
    LockoutPolicy,
    PasswordHasher,
    SessionPolicy,
    new_session_token,
    normalize_username,
    password_problems,
    token_hash,
)
from .ports import IdentityStore, UserRecord


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


@dataclass(frozen=True)
class User:
    id: int
    username: str
    role: str
    display_name: str | None
    email: str | None

    @classmethod
    def of(cls, record: UserRecord) -> User:
        return cls(record.id, record.username, record.role, record.display_name, record.email)


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
    ) -> User:
        """Wirft ``InvalidUsername``, ``WeakPassword``, ``UserExists`` oder ``ValueError``."""
        name = normalize_username(username)
        if role not in ROLES:
            msg = f"Rolle {role!r} gibt es nicht ({', '.join(ROLES)})"
            raise ValueError(msg)
        problems = password_problems(password, username=name)
        if problems:
            raise WeakPassword(problems)
        email = email.strip() if email else None
        display = display_name.strip() if display_name else None
        if email is not None and ("@" not in email or any(c.isspace() for c in email)):
            msg = f"Keine gueltige Mail-Adresse: {email!r}"
            raise ValueError(msg)
        user_id = self._store.create_user(
            username=name,
            role=role,
            password_hash=self._hash(password),
            display_name=display,
            email=email,
            at=self.now(),
        )
        return User(user_id, name, role, display, email)

    def login(
        self, username: str, password: str, *, ip: str | None, user_agent: str | None = None
    ) -> LoginResult:
        now = self.now()
        name = username.strip().lower()
        failures = self._store.count_failures(
            username=name, ip=ip, since=self.lockout.since(now), now=now
        )
        if self.lockout.is_locked(failures):
            self._log(name, None, ip, "locked", now)
            raise LoginLocked(int(self.lockout.window.total_seconds()))
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

    def authenticate(self, token: str | None) -> User | None:
        """Der Nutzer einer gueltigen Sitzung, sonst ``None``. Verlaengert die Inaktivitaetsfrist."""
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
        if self.sessions.needs_touch(session.last_seen, now):
            self._store.touch_session(id_hash, at=now)
        return User.of(record)

    def logout(self, token: str | None) -> None:
        if not token:
            return
        id_hash = token_hash(token)
        if self._store.find_session(id_hash) is not None:
            self._store.revoke_session(id_hash, reason="logout", at=self.now())

    def _log(
        self, name: str, user_id: int | None, ip: str | None, reason: str, at: datetime
    ) -> None:
        self._store.record_login(
            username=name[:64], user_id=user_id, ip=ip, ok=reason == "ok", reason=reason, at=at
        )
