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
