"""``IdentityStore`` in Postgres (D1.1): Schema ``identity``, Rolle ``va_identity``.

Nur ``INSERT`` und ``SELECT``: Name, Mail, Status und Passwort aendern sich als neue Zeile, gueltig
ist die juengste (nach Einfuegereihenfolge). Ein Widerruf ist eine Zeile in
``session_revocation``, ein zweiter aendert nichts (``ON CONFLICT DO NOTHING``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import insert, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as OrmSession

from va_contracts import parse_envelope
from va_platform.messaging import Outbox, drain_outbox

from ...identity.domain import FAILURE_REASONS, Failures
from ...identity.ports import EmailConfirmationRecord, SessionRecord, UserExists, UserRecord
from .identity_models import (
    EmailConfirmation,
    IdentityOutbox,
    LoginEvent,
    PasswordCredential,
    Session,
    SessionSeen,
    UserAccount,
    UserProfileVersion,
    UserStatus,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime

    from sqlalchemy import Engine, Row

    from va_contracts import Envelope

_USER = """
SELECT a.id, a.username, a.role, a.created_at,
       p.display_name, p.email,
       COALESCE(s.status, 'active') = 'active' AS active,
       c.hash AS password_hash, COALESCE(c.must_change, false) AS must_change
FROM identity.user_account a
LEFT JOIN LATERAL (
    SELECT display_name, email FROM identity.user_profile_version
    WHERE user_id = a.id ORDER BY id DESC LIMIT 1
) p ON true
LEFT JOIN LATERAL (
    SELECT status FROM identity.user_status WHERE user_id = a.id ORDER BY id DESC LIMIT 1
) s ON true
LEFT JOIN LATERAL (
    SELECT hash, must_change FROM identity.password_credential
    WHERE user_id = a.id ORDER BY id DESC LIMIT 1
) c ON true
"""

# D1.4: neue Profil-Version mit neuem Namen, Mail-Adresse und Bestaetigung aus der juengsten
_DISPLAY_NAME = """
INSERT INTO identity.user_profile_version (user_id, display_name, email, email_confirmed_at,
                                           created_at)
SELECT :user_id, :display_name, p.email, p.email_confirmed_at, :at
FROM (SELECT 1) one
LEFT JOIN LATERAL (
    SELECT email, email_confirmed_at FROM identity.user_profile_version
    WHERE user_id = :user_id ORDER BY id DESC LIMIT 1
) p ON true
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

_SESSIONS = """
SELECT s.id_hash, s.user_id, s.created_at, s.expires_at, s.user_agent,
       GREATEST(s.created_at, (SELECT max(seen_at) FROM identity.session_seen v
                               WHERE v.id_hash = s.id_hash)) AS last_seen,
       EXISTS (SELECT 1 FROM identity.session_revocation r WHERE r.id_hash = s.id_hash) AS revoked
FROM identity.session s
"""

_REVOKE = """
INSERT INTO identity.session_revocation (id_hash, reason, at)
SELECT :id_hash, :reason, :at
WHERE EXISTS (SELECT 1 FROM identity.session WHERE id_hash = :id_hash)
ON CONFLICT (id_hash) DO NOTHING
"""

# D1.4: alle offenen Sitzungen eines Nutzers ausser einer; RETURNING nennt die widerrufenen
_REVOKE_ALL = """
INSERT INTO identity.session_revocation (id_hash, reason, at)
SELECT s.id_hash, :reason, :at FROM identity.session s
WHERE s.user_id = :user_id AND s.id_hash IS DISTINCT FROM CAST(:keep AS text)
ON CONFLICT (id_hash) DO NOTHING
RETURNING id_hash
"""

# D1.6: Mail-Adresse bestaetigen. "Juengste Anfrage" nach Einfuegereihenfolge (id)
_CONFIRMATION = """
SELECT c.user_id, c.email, c.expires_at, c.created_at,
       EXISTS (SELECT 1 FROM identity.email_confirmation_used u
               WHERE u.token_hash = c.token_hash) AS used,
       c.id = (SELECT max(id) FROM identity.email_confirmation
               WHERE user_id = c.user_id) AS latest
FROM identity.email_confirmation c
WHERE c.token_hash = :token_hash
"""

# Einmalig: die Zeile in email_confirmation_used entscheidet (ON CONFLICT), erst dann entsteht die
# Profil-Version mit der Adresse; Anzeigename aus der juengsten Version
_CONFIRM = """
WITH used AS (
    INSERT INTO identity.email_confirmation_used (token_hash, at)
    SELECT token_hash, :at FROM identity.email_confirmation WHERE token_hash = :token_hash
    ON CONFLICT (token_hash) DO NOTHING
    RETURNING token_hash
)
INSERT INTO identity.user_profile_version (user_id, display_name, email, email_confirmed_at,
                                           created_at)
SELECT c.user_id, p.display_name, c.email, :at, :at
FROM used
JOIN identity.email_confirmation c ON c.token_hash = used.token_hash
LEFT JOIN LATERAL (
    SELECT display_name FROM identity.user_profile_version
    WHERE user_id = c.user_id ORDER BY id DESC LIMIT 1
) p ON true
RETURNING id
"""

_PENDING = """
SELECT c.email
FROM (SELECT token_hash, email, expires_at FROM identity.email_confirmation
      WHERE user_id = :user_id ORDER BY id DESC LIMIT 1) c
WHERE c.expires_at > :now
  AND NOT EXISTS (SELECT 1 FROM identity.email_confirmation_used u
                  WHERE u.token_hash = c.token_hash)
"""

# NUT-12: alle Zeilen eines Nutzers in identity, ohne Hashes (Passwort, Sitzung, Token)
_EXPORT = {
    "account": """
        SELECT id, username, role, created_at FROM identity.user_account WHERE id = :id
    """,
    "profiles": """
        SELECT display_name, email, email_confirmed_at, created_at
        FROM identity.user_profile_version WHERE user_id = :id ORDER BY id
    """,
    "statuses": """
        SELECT status, reason, at FROM identity.user_status WHERE user_id = :id ORDER BY id
    """,
    "credentials": """
        SELECT must_change, created_at FROM identity.password_credential
        WHERE user_id = :id ORDER BY id
    """,
    "sessions": """
        SELECT s.created_at, s.expires_at, s.user_agent, s.ip,
               (SELECT max(seen_at) FROM identity.session_seen v
                WHERE v.id_hash = s.id_hash) AS last_seen,
               r.reason AS revoked_reason, r.at AS revoked_at
        FROM identity.session s
        LEFT JOIN identity.session_revocation r ON r.id_hash = s.id_hash
        WHERE s.user_id = :id ORDER BY s.created_at
    """,
    "logins": """
        SELECT username, ip, ok, reason, at FROM identity.login_event
        WHERE user_id = :id OR username = :name ORDER BY id
    """,
    "email_confirmations": """
        SELECT c.email, c.created_at, c.expires_at, u.at AS confirmed_at
        FROM identity.email_confirmation c
        LEFT JOIN identity.email_confirmation_used u ON u.token_hash = c.token_hash
        WHERE c.user_id = :id ORDER BY c.id
    """,
}


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
        must_change=bool(row.must_change),
        created_at=row.created_at,
    )


def _session(row: Row) -> SessionRecord:
    return SessionRecord(
        id_hash=row.id_hash,
        user_id=row.user_id,
        created_at=row.created_at,
        expires_at=row.expires_at,
        last_seen=row.last_seen,
        revoked=bool(row.revoked),
        user_agent=row.user_agent,
    )


class PostgresIdentityStore:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._outbox = Outbox(IdentityOutbox)

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
                        user_id=user_id, hash=password_hash, must_change=must_change, created_at=at
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

    def list_users(self) -> list[UserRecord]:
        with self._engine.connect() as conn:
            rows = conn.execute(text(_USER + " ORDER BY a.id")).all()
        return [user for row in rows if (user := _user(row)) is not None]

    def set_status(self, user_id: int, status: str, *, reason: str | None, at: datetime) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                insert(UserStatus).values(user_id=user_id, status=status, reason=reason, at=at)
            )

    def set_password(
        self, user_id: int, password_hash: str, *, must_change: bool, at: datetime
    ) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                insert(PasswordCredential).values(
                    user_id=user_id, hash=password_hash, must_change=must_change, created_at=at
                )
            )

    def set_display_name(self, user_id: int, display_name: str | None, *, at: datetime) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                text(_DISPLAY_NAME), {"user_id": user_id, "display_name": display_name, "at": at}
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
            row = conn.execute(
                text(_SESSIONS + " WHERE s.id_hash = :id_hash"), {"id_hash": id_hash}
            ).first()
        return None if row is None else _session(row)

    def list_sessions(self, user_id: int) -> list[SessionRecord]:
        with self._engine.connect() as conn:
            rows = conn.execute(
                text(_SESSIONS + " WHERE s.user_id = :user_id ORDER BY s.created_at"),
                {"user_id": user_id},
            ).all()
        return [_session(row) for row in rows]

    def revoke_sessions(
        self, user_id: int, *, reason: str, at: datetime, keep: str | None = None
    ) -> list[str]:
        with self._engine.begin() as conn:
            rows = conn.execute(
                text(_REVOKE_ALL), {"user_id": user_id, "reason": reason, "at": at, "keep": keep}
            ).all()
        return [row.id_hash for row in rows]

    def touch_session(self, id_hash: str, *, at: datetime) -> None:
        with self._engine.begin() as conn:
            conn.execute(insert(SessionSeen).values(id_hash=id_hash, seen_at=at))

    def revoke_session(self, id_hash: str, *, reason: str, at: datetime) -> None:
        with self._engine.begin() as conn:
            conn.execute(text(_REVOKE), {"id_hash": id_hash, "reason": reason, "at": at})

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
        with OrmSession(self._engine) as session, session.begin():
            session.execute(
                insert(EmailConfirmation).values(
                    user_id=user_id,
                    email=email,
                    token_hash=token_hash,
                    expires_at=expires_at,
                    created_at=at,
                )
            )
            if envelope is not None:
                self._outbox.add(session, envelope)

    def find_email_confirmation(self, token_hash: str) -> EmailConfirmationRecord | None:
        with self._engine.connect() as conn:
            row = conn.execute(text(_CONFIRMATION), {"token_hash": token_hash}).first()
        if row is None:
            return None
        return EmailConfirmationRecord(
            user_id=row.user_id,
            email=row.email,
            expires_at=row.expires_at,
            created_at=row.created_at,
            used=bool(row.used),
            latest=bool(row.latest),
        )

    def count_email_confirmations(self, user_id: int, *, since: datetime) -> int:
        with self._engine.connect() as conn:
            return int(
                conn.execute(
                    text(
                        "SELECT count(*) FROM identity.email_confirmation"
                        " WHERE user_id = :user_id AND created_at >= :since"
                    ),
                    {"user_id": user_id, "since": since},
                ).scalar_one()
            )

    def confirm_email(self, token_hash: str, *, at: datetime) -> bool:
        with self._engine.begin() as conn:
            row = conn.execute(text(_CONFIRM), {"token_hash": token_hash, "at": at}).first()
        return row is not None

    def pending_email(self, user_id: int, *, now: datetime) -> str | None:
        with self._engine.connect() as conn:
            return conn.execute(text(_PENDING), {"user_id": user_id, "now": now}).scalar()

    def export(self, user_id: int) -> dict[str, list[dict[str, Any]]]:
        with self._engine.connect() as conn:
            name = conn.execute(
                text("SELECT username FROM identity.user_account WHERE id = :id"), {"id": user_id}
            ).scalar()
            return {
                section: [
                    dict(row)
                    for row in conn.execute(text(query), {"id": user_id, "name": name}).mappings()
                ]
                for section, query in _EXPORT.items()
            }

    def publish_pending(self, publish: Callable[[Envelope[Any]], None]) -> int:
        """Sendet die offenen Events der Outbox (Bestaetigungsmails); gibt die Anzahl zurueck."""
        return drain_outbox(
            self._engine, self._outbox, lambda message: publish(parse_envelope(message.payload))
        )
