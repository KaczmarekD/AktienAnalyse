"""Speicher der Konten und Sitzungen (D1.1): dieselben Regeln im Prozess und in Postgres.

Die Tests laufen gegen ``MemoryIdentityStore`` (immer) und ``PostgresIdentityStore`` (nur mit
``TEST_DATABASE_URL``, Rolle ``va_identity``). So rechnen die API-Tests ohne Datenbank mit
demselben Verhalten wie der Betrieb. Alle Zeitpunkte kommen vom Aufrufer, nicht von der Datenbank.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from va_web_api.identity.memory import MemoryIdentityStore
from va_web_api.identity.ports import IdentityStore, UserExists

T0 = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)
HASH = "scrypt$1024$8$1$c2FsdA$aGFzaA"


@pytest.fixture(params=["memory", "postgres"])
def store(request) -> IdentityStore:
    if request.param == "memory":
        return MemoryIdentityStore()
    from va_web_api.adapters.postgres.identity_store import PostgresIdentityStore

    return PostgresIdentityStore(request.getfixturevalue("identity_engine"))


def _user(store: IdentityStore, name: str = "dennis", role: str = "user") -> int:
    return store.create_user(
        username=name, role=role, password_hash=HASH, display_name=None, email=None, at=T0
    )


class TestUsers:
    def test_create_and_find(self, store):
        user_id = store.create_user(
            username="dennis",
            role="admin",
            password_hash=HASH,
            display_name="Dennis",
            email="d@example.com",
            at=T0,
        )
        found = store.find_user("dennis")
        assert found is not None
        assert (found.id, found.username, found.role) == (user_id, "dennis", "admin")
        assert (found.display_name, found.email, found.active) == ("Dennis", "d@example.com", True)
        assert found.password_hash == HASH
        assert store.get_user(user_id) == found

    def test_unknown(self, store):
        assert store.find_user("niemand") is None
        assert store.get_user(4711) is None

    def test_names_are_unique(self, store):
        _user(store)
        with pytest.raises(UserExists):
            _user(store)

    def test_the_newest_status_wins(self, store):
        user_id = _user(store)
        store.set_status(user_id, "disabled", reason="test", at=T0 + timedelta(minutes=1))
        found = store.get_user(user_id)
        assert found is not None
        assert not found.active
        store.set_status(user_id, "active", reason=None, at=T0 + timedelta(minutes=2))
        found = store.get_user(user_id)
        assert found is not None
        assert found.active

    def test_created_at_and_must_change(self, store):
        """D1.4: Ein vom Admin angelegtes Konto muss sein Einmal-Passwort ersetzen."""
        user_id = store.create_user(
            username="lena",
            role="user",
            password_hash=HASH,
            display_name=None,
            email=None,
            at=T0,
            must_change=True,
        )
        found = store.get_user(user_id)
        assert found is not None
        assert (found.created_at, found.must_change) == (T0, True)
        assert not store.get_user(_user(store)).must_change  # type: ignore[union-attr]

    def test_list_users_in_order_of_creation(self, store):
        first, second = _user(store, "dennis", "admin"), _user(store, "anna")
        store.set_status(second, "disabled", reason="test", at=T0 + timedelta(minutes=1))
        users = store.list_users()
        assert [(u.id, u.username, u.active) for u in users] == [
            (first, "dennis", True),
            (second, "anna", False),
        ]

    def test_the_newest_password_wins(self, store):
        user_id = _user(store)
        store.set_password(user_id, HASH + "2", must_change=True, at=T0 + timedelta(minutes=1))
        found = store.get_user(user_id)
        assert found is not None
        assert (found.password_hash, found.must_change) == (HASH + "2", True)
        store.set_password(user_id, HASH + "3", must_change=False, at=T0 + timedelta(minutes=2))
        found = store.get_user(user_id)
        assert found is not None
        assert (found.password_hash, found.must_change) == (HASH + "3", False)

    def test_a_new_display_name_keeps_the_mail_address(self, store):
        user_id = store.create_user(
            username="dennis",
            role="user",
            password_hash=HASH,
            display_name="Dennis",
            email="d@example.com",
            at=T0,
        )
        store.set_display_name(user_id, "Dennis K.", at=T0 + timedelta(minutes=1))
        found = store.get_user(user_id)
        assert found is not None
        assert (found.display_name, found.email) == ("Dennis K.", "d@example.com")
        store.set_display_name(user_id, None, at=T0 + timedelta(minutes=2))
        found = store.get_user(user_id)
        assert found is not None
        assert (found.display_name, found.email) == (None, "d@example.com")


class TestFailures:
    def test_counts_per_user_since_the_last_success(self, store):
        for minute, ok in ((1, False), (2, False), (3, True), (4, False)):
            store.record_login(
                username="dennis",
                user_id=None,
                ip="10.0.0.1",
                ok=ok,
                reason="ok" if ok else "wrong_password",
                at=T0 + timedelta(minutes=minute),
            )
        failures = store.count_failures(
            username="dennis", ip="10.0.0.2", since=T0, now=T0 + timedelta(minutes=5)
        )
        assert (failures.by_user, failures.by_ip) == (1, 0)

    def test_counts_per_address_since_the_last_success_there(self, store):
        for minute, name, ok in ((1, "a", False), (2, "b", True), (3, "c", False), (4, "d", False)):
            store.record_login(
                username=name,
                user_id=None,
                ip="10.0.0.1",
                ok=ok,
                reason="ok" if ok else "unknown_user",
                at=T0 + timedelta(minutes=minute),
            )
        failures = store.count_failures(
            username="x", ip="10.0.0.1", since=T0, now=T0 + timedelta(minutes=5)
        )
        assert (failures.by_user, failures.by_ip) == (0, 2)

    def test_the_order_decides_at_equal_times(self, store):
        """Erfolg und Fehlversuche im selben Augenblick: Es zaehlt die Reihenfolge."""
        for ok in (False, False, True, False):
            store.record_login(
                username="dennis",
                user_id=None,
                ip="10.0.0.1",
                ok=ok,
                reason="ok" if ok else "wrong_password",
                at=T0,
            )
        failures = store.count_failures(username="dennis", ip="10.0.0.1", since=T0, now=T0)
        assert (failures.by_user, failures.by_ip) == (1, 1)

    def test_only_inside_the_window(self, store):
        store.record_login(
            username="dennis", user_id=None, ip="10.0.0.1", ok=False, reason="wrong_password", at=T0
        )
        failures = store.count_failures(
            username="dennis",
            ip="10.0.0.1",
            since=T0 + timedelta(seconds=1),
            now=T0 + timedelta(minutes=5),
        )
        assert (failures.by_user, failures.by_ip) == (0, 0)

    def test_rejections_during_a_lock_do_not_count(self, store):
        store.record_login(
            username="dennis", user_id=None, ip="10.0.0.1", ok=False, reason="locked", at=T0
        )
        failures = store.count_failures(
            username="dennis", ip="10.0.0.1", since=T0 - timedelta(minutes=1), now=T0
        )
        assert (failures.by_user, failures.by_ip) == (0, 0)


class TestSessions:
    def test_create_and_find(self, store):
        user_id = _user(store)
        store.create_session(
            id_hash="a" * 64,
            user_id=user_id,
            created_at=T0,
            expires_at=T0 + timedelta(days=30),
            user_agent="pytest",
            ip="10.0.0.1",
        )
        session = store.find_session("a" * 64)
        assert session is not None
        assert (session.user_id, session.created_at, session.expires_at) == (
            user_id,
            T0,
            T0 + timedelta(days=30),
        )
        assert session.last_seen == T0
        assert not session.revoked

    def test_unknown(self, store):
        assert store.find_session("b" * 64) is None

    def test_touch_moves_last_seen(self, store):
        user_id = _user(store)
        store.create_session(
            id_hash="a" * 64,
            user_id=user_id,
            created_at=T0,
            expires_at=T0 + timedelta(days=30),
            user_agent=None,
            ip=None,
        )
        store.touch_session("a" * 64, at=T0 + timedelta(hours=1))
        session = store.find_session("a" * 64)
        assert session is not None
        assert session.last_seen == T0 + timedelta(hours=1)

    def test_revoke_is_final_and_repeatable(self, store):
        user_id = _user(store)
        store.create_session(
            id_hash="a" * 64,
            user_id=user_id,
            created_at=T0,
            expires_at=T0 + timedelta(days=30),
            user_agent=None,
            ip=None,
        )
        store.revoke_session("a" * 64, reason="logout", at=T0 + timedelta(minutes=1))
        store.revoke_session("a" * 64, reason="logout", at=T0 + timedelta(minutes=2))
        session = store.find_session("a" * 64)
        assert session is not None
        assert session.revoked


def _session(store: IdentityStore, id_hash: str, user_id: int, minute: int = 0) -> None:
    store.create_session(
        id_hash=id_hash,
        user_id=user_id,
        created_at=T0 + timedelta(minutes=minute),
        expires_at=T0 + timedelta(days=30),
        user_agent=f"Browser {id_hash[0]}",
        ip=None,
    )


class TestSessionsOfAUser:
    """D1.4: Sitzungen eines Nutzers auflisten und alle auf einmal widerrufen."""

    def test_list_only_the_own(self, store):
        anna, dennis = _user(store, "anna"), _user(store, "dennis")
        _session(store, "a" * 64, anna)
        _session(store, "b" * 64, anna, minute=1)
        _session(store, "c" * 64, dennis)
        sessions = store.list_sessions(anna)
        assert sorted((s.id_hash[0], s.user_agent) for s in sessions) == [
            ("a", "Browser a"),
            ("b", "Browser b"),
        ]

    def test_revoke_all_except_one(self, store):
        anna, dennis = _user(store, "anna"), _user(store, "dennis")
        for id_hash in ("a" * 64, "b" * 64, "c" * 64):
            _session(store, id_hash, anna)
        _session(store, "d" * 64, dennis)
        store.revoke_session("c" * 64, reason="logout", at=T0)
        revoked = store.revoke_sessions(
            anna, reason="password_changed", at=T0 + timedelta(minutes=1), keep="a" * 64
        )
        assert revoked == ["b" * 64]  # c war schon widerrufen, a bleibt
        state = {s.id_hash[0]: s.revoked for s in store.list_sessions(anna)}
        assert state == {"a": False, "b": True, "c": True}
        assert not store.find_session("d" * 64).revoked  # type: ignore[union-attr]

    def test_revoke_all(self, store):
        anna = _user(store, "anna")
        _session(store, "a" * 64, anna)
        _session(store, "b" * 64, anna)
        revoked = store.revoke_sessions(anna, reason="logout", at=T0)
        assert sorted(revoked) == ["a" * 64, "b" * 64]
        assert store.revoke_sessions(anna, reason="logout", at=T0) == []
