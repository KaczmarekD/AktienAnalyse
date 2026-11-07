"""Loeschkommando fuer das Schema ``identity`` (D1.6, ADR-0012, docs/architecture/depot/nutzer.md).

Konten werden sonst nie geloescht, nur deaktiviert. Auf ausdruecklichen Wunsch einer Person
loescht ``erase_user`` alle ihre Zeilen in ``identity``, die Outbox eingeschlossen. Die Inbox
enthaelt nur Event-IDs und bleibt.

Es laeuft mit der Rolle des Besitzers (``DATABASE_OWNER_URL``): Nur sie darf die Trigger gegen
DELETE abschalten. Das geschieht in derselben Transaktion wie das Loeschen, am Ende sind sie wieder
an. Scheitert etwas, rollt Postgres alles zurueck, auch das Abschalten. ``ALTER TABLE`` sperrt die
Tabellen bis zum Ende; deshalb zuerst alle, dann loeschen, damit keine Anmeldung dazwischen neue
Zeilen schreibt.

``erasure_log`` haelt fest, dass geloescht wurde, aber nicht wen oder was: nur den SHA-256 der
Nutzer-ID, den Admin und die Zeilenzahlen je Tabelle.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import insert, text

from .identity_models import SCHEMA, ErasureLog

if TYPE_CHECKING:
    from datetime import datetime

    from sqlalchemy import Engine

TRIGGER = "va_no_delete"  # aus va_platform.db.ddl.protect_table

# Jede Tabelle mit Bezug zu einem Konto, abhaengige vor denen, auf die sie verweisen
PER_USER: tuple[tuple[str, str], ...] = (
    ("session_seen", "id_hash IN (SELECT id_hash FROM identity.session WHERE user_id = :id)"),
    ("session_revocation", "id_hash IN (SELECT id_hash FROM identity.session WHERE user_id = :id)"),
    ("session", "user_id = :id"),
    (
        "email_confirmation_used",
        "token_hash IN (SELECT token_hash FROM identity.email_confirmation WHERE user_id = :id)",
    ),
    ("email_confirmation", "user_id = :id"),
    ("user_profile_version", "user_id = :id"),
    ("user_status", "user_id = :id"),
    ("password_credential", "user_id = :id"),
    # Auch Fehlversuche unter dem Namen, bevor das Konto bekannt war
    ("login_event", "user_id = :id OR username = :name"),
    # Events fuer die Bestaetigungsmail tragen die Nutzer-ID
    ("outbox", "payload -> 'data' ->> 'user_id' = CAST(:id AS text)"),
    ("user_account", "id = :id"),
)


class UnknownAccount(LookupError):
    """Kein Konto mit diesem Namen."""


@dataclass(frozen=True)
class ErasureReport:
    user_key: str  # SHA-256 der Nutzer-ID, wie in erasure_log
    rows: dict[str, int]  # geloeschte Zeilen je Tabelle


def user_key(user_id: int) -> str:
    return hashlib.sha256(str(user_id).encode("ascii")).hexdigest()


def erase_user(engine: Engine, username: str, *, by: str, at: datetime) -> ErasureReport:
    """Loescht alle Zeilen des Kontos ``username`` in ``identity``; wirft ``UnknownAccount``.

    ``engine`` verbindet sich als Besitzer der Tabellen, mit einer anderen Rolle scheitert schon
    das Abschalten der Trigger.
    """
    name = username.strip().lower()
    with engine.begin() as conn:
        user_id = conn.execute(
            text("SELECT id FROM identity.user_account WHERE username = :name"), {"name": name}
        ).scalar()
        if user_id is None:
            raise UnknownAccount(name)
        tables = [table for table, _ in PER_USER]
        for table in tables:
            conn.execute(text(f"ALTER TABLE {SCHEMA}.{table} DISABLE TRIGGER {TRIGGER}"))
        rows: dict[str, int] = {}
        for table, where in PER_USER:
            result = conn.execute(
                text(f"DELETE FROM {SCHEMA}.{table} WHERE {where}"), {"id": user_id, "name": name}
            )
            rows[table] = result.rowcount
        for table in tables:
            conn.execute(text(f"ALTER TABLE {SCHEMA}.{table} ENABLE TRIGGER {TRIGGER}"))
        key = user_key(user_id)
        conn.execute(insert(ErasureLog).values(user_key=key, by_admin=by, rows=rows, at=at))
    return ErasureReport(user_key=key, rows=rows)
