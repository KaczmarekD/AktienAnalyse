"""Speicher fuer Konten und Sitzungen im Prozess (D1.1), fuer Tests.

Er erfuellt dieselben Regeln wie ``PostgresIdentityStore``; das pruefen gemeinsame Tests
(``tests/db/web_api/test_identity_store.py``). Nicht fuer den Betrieb: Nach einem Neustart waeren
alle Konten weg.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from itertools import count

from .domain import FAILURE_REASONS, Failures
from .ports import SessionRecord, UserExists, UserRecord


@dataclass(frozen=True)
class LoginEvent:
    username: str
    user_id: int | None
    ip: str | None
    ok: bool
    reason: str
    at: datetime


@dataclass
class _User:
    id: int
    username: str
    role: str
    display_name: str | None
    email: str | None
    created_at: datetime
    statuses: list[str] = field(default_factory=lambda: ["active"])
    # (Hash, must_change); gueltig ist der juengste Eintrag
    passwords: list[tuple[str, bool]] = field(default_factory=list)


@dataclass
class _Session:
    user_id: int
    created_at: datetime
    expires_at: datetime
    user_agent: str | None
    seen: list[datetime] = field(default_factory=list)
    revoked: bool = False


class MemoryIdentityStore:
    def __init__(self) -> None:
        self._ids = count(1)
        self._users: dict[int, _User] = {}
        self._sessions: dict[str, _Session] = {}
        self._events: list[LoginEvent] = []

    # Nur fuer Tests: was gespeichert ist
    def session_ids(self) -> set[str]:
        return set(self._sessions)

    def login_events(self) -> list[LoginEvent]:
        return list(self._events)

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
        if any(u.username == username for u in self._users.values()):
            raise UserExists(username)
        user_id = next(self._ids)
        self._users[user_id] = _User(
            user_id,
            username,
            role,
            display_name,
            email,
            created_at=at,
            passwords=[(password_hash, must_change)],
        )
        return user_id

    def _record(self, user: _User) -> UserRecord:
        password_hash, must_change = user.passwords[-1] if user.passwords else (None, False)
        return UserRecord(
            id=user.id,
            username=user.username,
            role=user.role,
            display_name=user.display_name,
            email=user.email,
            active=user.statuses[-1] == "active",
            password_hash=password_hash,
            must_change=must_change,
            created_at=user.created_at,
        )

    def find_user(self, username: str) -> UserRecord | None:
        for user in self._users.values():
            if user.username == username:
                return self._record(user)
        return None

    def get_user(self, user_id: int) -> UserRecord | None:
        user = self._users.get(user_id)
        return None if user is None else self._record(user)

    def list_users(self) -> list[UserRecord]:
        return [self._record(user) for _, user in sorted(self._users.items())]

    def set_status(
        self,
        user_id: int,
        status: str,
        *,
        reason: str | None,  # noqa: ARG002 - wie der Postgres-Speicher
        at: datetime,  # noqa: ARG002
    ) -> None:
        self._users[user_id].statuses.append(status)

    def set_password(
        self,
        user_id: int,
        password_hash: str,
        *,
        must_change: bool,
        at: datetime,  # noqa: ARG002 - wie der Postgres-Speicher
    ) -> None:
        self._users[user_id].passwords.append((password_hash, must_change))

    def set_display_name(
        self,
        user_id: int,
        display_name: str | None,
        *,
        at: datetime,  # noqa: ARG002 - wie der Postgres-Speicher
    ) -> None:
        self._users[user_id].display_name = display_name

    def record_login(
        self,
        *,
        username: str,
        user_id: int | None,
        ip: str | None,
        ok: bool,
        reason: str,
        at: datetime,
    ) -> None:
        self._events.append(LoginEvent(username, user_id, ip, ok, reason, at))

    def count_failures(
        self, *, username: str, ip: str | None, since: datetime, now: datetime
    ) -> Failures:
        def failures_after_last_success(events: list[LoginEvent]) -> int:
            # "Seit dem letzten Erfolg" nach Reihenfolge, nicht nach Zeit: gleiche Zeitstempel
            last_ok = max((i for i, e in enumerate(events) if e.ok), default=-1)
            return sum(
                1
                for e in events[last_ok + 1 :]
                if not e.ok and e.reason in FAILURE_REASONS and since <= e.at <= now
            )

        events = [e for e in self._events if e.at <= now]
        by_user = failures_after_last_success([e for e in events if e.username == username])
        by_ip = 0 if ip is None else failures_after_last_success([e for e in events if e.ip == ip])
        return Failures(by_user=by_user, by_ip=by_ip)

    def create_session(
        self,
        *,
        id_hash: str,
        user_id: int,
        created_at: datetime,
        expires_at: datetime,
        user_agent: str | None,
        ip: str | None,  # noqa: ARG002 - wie der Postgres-Speicher
    ) -> None:
        self._sessions[id_hash] = _Session(user_id, created_at, expires_at, user_agent)

    def _session(self, id_hash: str, session: _Session) -> SessionRecord:
        return SessionRecord(
            id_hash=id_hash,
            user_id=session.user_id,
            created_at=session.created_at,
            expires_at=session.expires_at,
            last_seen=max([session.created_at, *session.seen]),
            revoked=session.revoked,
            user_agent=session.user_agent,
        )

    def find_session(self, id_hash: str) -> SessionRecord | None:
        session = self._sessions.get(id_hash)
        return None if session is None else self._session(id_hash, session)

    def touch_session(self, id_hash: str, *, at: datetime) -> None:
        self._sessions[id_hash].seen.append(at)

    def revoke_session(self, id_hash: str, *, reason: str, at: datetime) -> None:  # noqa: ARG002
        session = self._sessions.get(id_hash)
        if session is not None:
            session.revoked = True

    def list_sessions(self, user_id: int) -> list[SessionRecord]:
        return [
            self._session(id_hash, session)
            for id_hash, session in self._sessions.items()
            if session.user_id == user_id
        ]

    def revoke_sessions(
        self,
        user_id: int,
        *,
        reason: str,  # noqa: ARG002 - wie der Postgres-Speicher
        at: datetime,  # noqa: ARG002
        keep: str | None = None,
    ) -> list[str]:
        revoked = []
        for id_hash, session in self._sessions.items():
            if session.user_id == user_id and not session.revoked and id_hash != keep:
                session.revoked = True
                revoked.append(id_hash)
        return revoked
