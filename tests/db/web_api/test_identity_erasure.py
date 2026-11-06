"""Loeschkommando fuer das Schema ``identity`` (D1.6, ADR-0012, nutzer.md).

Konten werden sonst nie geloescht, nur deaktiviert. Auf ausdruecklichen Wunsch einer Person loescht
ein Admin-Kommando alle ihre Zeilen in ``identity``, Outbox eingeschlossen. Es laeuft mit der Rolle
des Besitzers und schaltet den Schutz nur fuer diese Transaktion ab. Das Protokoll
``erasure_log`` haelt fest, dass geloescht wurde, aber nicht wen oder was: nur den Hash der
Nutzer-ID, den Admin und die Zeilenzahlen.
"""

from __future__ import annotations

import hashlib
import io
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError

from va_contracts import new_envelope
from va_contracts.events.v1 import EMAIL_CONFIRMATION_REQUESTED, EmailConfirmationRequestedV1
from va_web_api.adapters.postgres.identity_erasure import UnknownAccount, erase_user
from va_web_api.adapters.postgres.identity_store import PostgresIdentityStore

T0 = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)
HASH = "scrypt$1024$8$1$c2FsdA$aGFzaA"

# Jede Tabelle mit Bezug zu einem Konto und wie man seine Zeilen findet
PER_USER = {
    "user_account": "id = :id",
    "user_profile_version": "user_id = :id",
    "user_status": "user_id = :id",
    "password_credential": "user_id = :id",
    "session": "user_id = :id",
    "session_seen": "id_hash IN (SELECT id_hash FROM identity.session WHERE user_id = :id)",
    "session_revocation": "id_hash IN (SELECT id_hash FROM identity.session WHERE user_id = :id)",
    "login_event": "user_id = :id OR username = :name",
    "email_confirmation": "user_id = :id",
    "email_confirmation_used": (
        "token_hash IN (SELECT token_hash FROM identity.email_confirmation WHERE user_id = :id)"
    ),
    "outbox": "(payload -> 'data' ->> 'user_id')::bigint = :id",
}


def _count(engine: Engine, table: str, user_id: int, name: str) -> int:
    with engine.connect() as conn:
        return int(
            conn.execute(
                text(f"SELECT count(*) FROM identity.{table} WHERE {PER_USER[table]}"),
                {"id": user_id, "name": name},
            ).scalar_one()
        )


def _account(store: PostgresIdentityStore, name: str, n: int) -> int:
    user_id = store.create_user(
        username=name,
        role="user",
        password_hash=HASH,
        display_name=name.title(),
        email=f"{name}@example.com",
        at=T0,
    )
    session = f"{n}" * 64
    store.create_session(
        id_hash=session,
        user_id=user_id,
        created_at=T0,
        expires_at=T0 + timedelta(days=30),
        user_agent="Firefox",
        ip="10.0.0.1",
    )
    store.touch_session(session, at=T0 + timedelta(minutes=20))
    store.revoke_session(session, reason="logout", at=T0 + timedelta(hours=1))
    store.record_login(username=name, user_id=user_id, ip="10.0.0.1", ok=True, reason="ok", at=T0)
    store.record_login(
        username=name, user_id=None, ip="10.0.0.1", ok=False, reason="unknown_user", at=T0
    )
    store.set_status(user_id, "disabled", reason="test", at=T0 + timedelta(minutes=1))
    store.set_password(user_id, HASH + "2", must_change=True, at=T0 + timedelta(minutes=2))
    token = f"t{n}" * 32
    data = EmailConfirmationRequestedV1(
        user_id=user_id,
        email=f"neu-{name}@example.com",
        link=f"https://va.example/confirm-email?token={n}",
        expires_at=T0 + timedelta(hours=24),
    )
    store.add_email_confirmation(
        user_id,
        email=f"neu-{name}@example.com",
        token_hash=token,
        expires_at=T0 + timedelta(hours=24),
        at=T0,
        envelope=new_envelope(EMAIL_CONFIRMATION_REQUESTED, data, source="va/web-api"),
    )
    store.confirm_email(token, at=T0 + timedelta(hours=2))
    return user_id


@pytest.fixture
def two(identity_engine: Engine) -> dict[str, int]:
    store = PostgresIdentityStore(identity_engine)
    return {"anna": _account(store, "anna", 1), "ben": _account(store, "ben", 2)}


def test_every_row_of_the_account_is_gone(engine, two):
    for table in PER_USER:
        assert _count(engine, table, two["anna"], "anna") > 0, table
    report = erase_user(engine, "anna", by="dennis", at=T0 + timedelta(days=1))
    for table in PER_USER:
        assert _count(engine, table, two["anna"], "anna") == 0, table
    assert report.rows["user_account"] == 1
    assert report.rows["login_event"] == 2


def test_other_accounts_stay(engine, two):
    before = {table: _count(engine, table, two["ben"], "ben") for table in PER_USER}
    erase_user(engine, "anna", by="dennis", at=T0 + timedelta(days=1))
    after = {table: _count(engine, table, two["ben"], "ben") for table in PER_USER}
    assert after == before


def test_the_log_says_that_but_not_whom(engine, two):
    erase_user(engine, "anna", by="dennis", at=T0 + timedelta(days=1))
    with engine.connect() as conn:
        [row] = conn.execute(text("SELECT * FROM identity.erasure_log")).mappings().all()
    assert row["user_key"] == hashlib.sha256(str(two["anna"]).encode()).hexdigest()
    assert row["by_admin"] == "dennis"
    assert row["rows"]["user_account"] == 1
    assert "anna" not in repr(dict(row))


def test_the_protection_is_back_afterwards(engine, two):
    erase_user(engine, "anna", by="dennis", at=T0 + timedelta(days=1))
    with pytest.raises(DBAPIError), engine.begin() as conn:
        conn.execute(text("DELETE FROM identity.user_account WHERE id = :id"), {"id": two["ben"]})
    with pytest.raises(DBAPIError), engine.begin() as conn:
        conn.execute(text("DELETE FROM identity.erasure_log"))


def test_unknown_account(engine):
    with pytest.raises(UnknownAccount):
        erase_user(engine, "niemand", by="dennis", at=T0)


def test_the_identity_role_cannot_erase(identity_engine, two):
    """Nur der Besitzer schaltet die Trigger ab; va_identity darf das nicht."""
    with pytest.raises(DBAPIError):
        erase_user(identity_engine, "anna", by="dennis", at=T0)


class TestCommand:
    """``python -m va_web_api.admin erase-user <name> --by <admin> --yes`` mit DATABASE_OWNER_URL."""

    def _main(self, monkeypatch, db_url: str, *argv: str) -> tuple[int, str]:
        from va_web_api import admin

        monkeypatch.setenv("DATABASE_OWNER_URL", db_url)
        out = io.StringIO()
        monkeypatch.setattr("sys.stdout", out)
        return admin.main(list(argv), stdin=io.StringIO("")), out.getvalue()

    def test_erases_with_confirmation(self, monkeypatch, db_url, engine, two):
        code, out = self._main(monkeypatch, db_url, "erase-user", "anna", "--by", "dennis", "--yes")
        assert code == 0
        assert "user_account: 1" in out
        assert _count(engine, "user_account", two["anna"], "anna") == 0

    def test_refuses_without_yes(self, monkeypatch, db_url, engine, two):
        code, _ = self._main(monkeypatch, db_url, "erase-user", "anna", "--by", "dennis")
        assert code == 2
        assert _count(engine, "user_account", two["anna"], "anna") == 1

    def test_needs_the_owner_url(self, monkeypatch, db_url, two):
        from va_web_api import admin

        monkeypatch.delenv("DATABASE_OWNER_URL", raising=False)
        code = admin.main(["erase-user", "anna", "--by", "dennis", "--yes"], stdin=io.StringIO(""))
        assert code == 2
