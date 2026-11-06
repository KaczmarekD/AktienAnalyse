"""``IdentityStore`` in Postgres (D1.1): Schema ``identity``, Rolle ``va_identity``.

Nur ``INSERT`` und ``SELECT``: Name, Mail, Status und Passwort aendern sich als neue Zeile, gueltig
ist die juengste (nach Einfuegereihenfolge). Ein Widerruf ist eine Zeile in
``session_revocation``, ein zweiter aendert nichts (``ON CONFLICT DO NOTHING``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import insert, text
from sqlalchemy.exc import IntegrityError

from ...identity.domain import FAILURE_REASONS, Failures
from ...identity.ports import SessionRecord, UserExists, UserRecord
from .identity_models import (
    LoginEvent,
    PasswordCredential,
    Session,
    SessionSeen,
    UserAccount,
    UserProfileVersion,
    UserStatus,
)

if TYPE_CHECKING:
    from datetime import datetime

    from sqlalchemy import Engine, Row

_USER = """
SELECT a.id, a.username, a.role,
       p.display_name, p.email,
       COALESCE(s.status, 'active') = 'active' AS active,
       c.hash AS password_hash
FROM identity.user_account a
LEFT JOIN LATERAL (
    SELECT display_name, email FROM identity.user_profile_version
    WHERE user_id = a.id ORDER BY id DESC LIMIT 1
) p ON true
LEFT JOIN LATERAL (
    SELECT status FROM identity.user_status WHERE user_id = a.id ORDER BY id DESC LIMIT 1
) s ON true
LEFT JOIN LATERAL (
    SELECT hash FROM identity.password_credential WHERE user_id = a.id ORDER BY id DESC LIMIT 1
) c ON true
"""

# "Seit dem letzten Erfolg" nach Einfuegereihenfolge (id), nicht nach Zeit: gleiche Zeitstempel
_FAILURES = """
WITH last_user_ok AS (
    SELECT COALESCE(max(id), 0) AS id FROM identity.login_event
    WHERE username = :username AND ok AND at <= :now
), last_ip_ok AS (
    SELECT COALESCE(max(id), 0) AS id FROM identity.login_event
    WHERE ip = CAST(:ip AS text) AND ok AND at <= :now
)
SELECT
    (SELECT count(*) FROM identity.login_event e, last_user_ok l
     WHERE e.username = :username AND NOT e.ok AND e.reason = ANY(:reasons)
       AND e.id > l.id AND e.at >= :since AND e.at <= :now) AS by_user,
    (SELECT count(*) FROM identity.login_event e, last_ip_ok l
     WHERE CAST(:ip AS text) IS NOT NULL AND e.ip = CAST(:ip AS text) AND NOT e.ok
       AND e.reason = ANY(:reasons)
       AND e.id > l.id AND e.at >= :since AND e.at <= :now) AS by_ip
"""

_SESSION = """
SELECT s.id_hash, s.user_id, s.created_at, s.expires_at,
       GREATEST(s.created_at, (SELECT max(seen_at) FROM identity.session_seen v
                               WHERE v.id_hash = s.id_hash)) AS last_seen,
       EXISTS (SELECT 1 FROM identity.session_revocation r WHERE r.id_hash = s.id_hash) AS revoked
FROM identity.session s
WHERE s.id_hash = :id_hash
"""

_REVOKE = """
INSERT INTO identity.session_revocation (id_hash, reason, at)
SELECT :id_hash, :reason, :at
WHERE EXISTS (SELECT 1 FROM identity.session WHERE id_hash = :id_hash)
ON CONFLICT (id_hash) DO NOTHING
"""


def _user(row: Row | None) -> UserRecord | None:
    if row is None:
        return None
    return UserRecord(
        id=row.id,
        username=row.username,
        role=row.role,
        display_name=row.display_name,
        email=row.email,
        active=bool(row.active),
        password_hash=row.password_hash,
    )


class PostgresIdentityStore:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

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
        try:
            with self._engine.begin() as conn:
                user_id = conn.execute(
                    insert(UserAccount)
                    .values(username=username, role=role, created_at=at)
                    .returning(UserAccount.id)
                ).scalar_one()
                conn.execute(
                    insert(UserProfileVersion).values(
                        user_id=user_id, display_name=display_name, email=email, created_at=at
                    )
                )
                conn.execute(insert(UserStatus).values(user_id=user_id, status="active", at=at))
                conn.execute(
                    insert(PasswordCredential).values(
                        user_id=user_id, hash=password_hash, created_at=at
                    )
                )
        except IntegrityError as e:
            if "uq_user_account_username" in str(e.orig):
                raise UserExists(username) from e
            raise
        return int(user_id)

    def find_user(self, username: str) -> UserRecord | None:
        with self._engine.connect() as conn:
            row = conn.execute(text(_USER + " WHERE a.username = :u"), {"u": username}).first()
        return _user(row)

    def get_user(self, user_id: int) -> UserRecord | None:
        with self._engine.connect() as conn:
            row = conn.execute(text(_USER + " WHERE a.id = :id"), {"id": user_id}).first()
        return _user(row)

    def set_status(self, user_id: int, status: str, *, reason: str | None, at: datetime) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                insert(UserStatus).values(user_id=user_id, status=status, reason=reason, at=at)
            )

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
        with self._engine.begin() as conn:
            conn.execute(
                insert(LoginEvent).values(
                    username=username, user_id=user_id, ip=ip, ok=ok, reason=reason, at=at
                )
            )

    def count_failures(
        self, *, username: str, ip: str | None, since: datetime, now: datetime
    ) -> Failures:
        with self._engine.connect() as conn:
            row = conn.execute(
                text(_FAILURES),
                {
                    "username": username,
                    "ip": ip,
                    "since": since,
                    "now": now,
                    "reasons": list(FAILURE_REASONS),
                },
            ).one()
        return Failures(by_user=int(row.by_user), by_ip=int(row.by_ip))

    def create_session(
        self,
        *,
        id_hash: str,
        user_id: int,
        created_at: datetime,
        expires_at: datetime,
        user_agent: str | None,
        ip: str | None,
    ) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                insert(Session).values(
                    id_hash=id_hash,
                    user_id=user_id,
                    created_at=created_at,
                    expires_at=expires_at,
                    user_agent=user_agent,
                    ip=ip,
                )
            )

    def find_session(self, id_hash: str) -> SessionRecord | None:
        with self._engine.connect() as conn:
            row = conn.execute(text(_SESSION), {"id_hash": id_hash}).first()
        if row is None:
            return None
        return SessionRecord(
            id_hash=row.id_hash,
            user_id=row.user_id,
            created_at=row.created_at,
            expires_at=row.expires_at,
            last_seen=row.last_seen,
            revoked=bool(row.revoked),
        )

    def touch_session(self, id_hash: str, *, at: datetime) -> None:
        with self._engine.begin() as conn:
            conn.execute(insert(SessionSeen).values(id_hash=id_hash, seen_at=at))

    def revoke_session(self, id_hash: str, *, reason: str, at: datetime) -> None:
        with self._engine.begin() as conn:
            conn.execute(text(_REVOKE), {"id_hash": id_hash, "reason": reason, "at": at})
