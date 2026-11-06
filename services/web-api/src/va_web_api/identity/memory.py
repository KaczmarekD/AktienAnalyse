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
    statuses: list[str] = field(default_factory=lambda: ["active"])
    hashes: list[str] = field(default_factory=list)


@dataclass
class _Session:
    user_id: int
    created_at: datetime
    expires_at: datetime
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
        at: datetime,  # noqa: ARG002 - wie der Postgres-Speicher
    ) -> int:
        if any(u.username == username for u in self._users.values()):
            raise UserExists(username)
        user_id = next(self._ids)
        self._users[user_id] = _User(
            user_id, username, role, display_name, email, hashes=[password_hash]
        )
        return user_id

    def _record(self, user: _User) -> UserRecord:
        return UserRecord(
            id=user.id,
            username=user.username,
            role=user.role,
            display_name=user.display_name,
            email=user.email,
            active=user.statuses[-1] == "active",
            password_hash=user.hashes[-1] if user.hashes else None,
        )

    def find_user(self, username: str) -> UserRecord | None:
        for user in self._users.values():
            if user.username == username:
                return self._record(user)
        return None

    def get_user(self, user_id: int) -> UserRecord | None:
        user = self._users.get(user_id)
        return None if user is None else self._record(user)

    def set_status(
        self,
        user_id: int,
        status: str,
        *,
        reason: str | None,  # noqa: ARG002 - wie der Postgres-Speicher
        at: datetime,  # noqa: ARG002
    ) -> None:
        self._users[user_id].statuses.append(status)

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
        user_agent: str | None,  # noqa: ARG002 - wie der Postgres-Speicher
        ip: str | None,  # noqa: ARG002
    ) -> None:
        self._sessions[id_hash] = _Session(user_id, created_at, expires_at)

    def find_session(self, id_hash: str) -> SessionRecord | None:
        session = self._sessions.get(id_hash)
        if session is None:
            return None
        return SessionRecord(
            id_hash=id_hash,
            user_id=session.user_id,
            created_at=session.created_at,
            expires_at=session.expires_at,
            last_seen=max([session.created_at, *session.seen]),
            revoked=session.revoked,
        )

    def touch_session(self, id_hash: str, *, at: datetime) -> None:
        self._sessions[id_hash].seen.append(at)

    def revoke_session(self, id_hash: str, *, reason: str, at: datetime) -> None:  # noqa: ARG002
        session = self._sessions.get(id_hash)
        if session is not None:
            session.revoked = True
