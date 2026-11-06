"""Anmeldung ueber die API (D1.1): Login, Sitzung, Sperre, Abmelden, ``/me``.

Ohne Datenbank: Der Dienst laeuft mit dem Speicher im Prozess (``MemoryIdentityStore``) und einer
steuerbaren Uhr. Dass der Postgres-Speicher dieselben Regeln erfuellt, pruefen
``tests/db/web_api/test_identity_store.py``. Bestehende Endpunkte bleiben bis D1.2 offen.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from va_web_api.identity.domain import PasswordHasher, token_hash
from va_web_api.identity.memory import MemoryIdentityStore
from va_web_api.identity.service import IdentityService
from va_web_api.main import create_app
from va_web_api.settings import WebApiSettings

SETTINGS = WebApiSettings(database_url=SecretStr("postgresql+psycopg://x:x@127.0.0.1:1/none"))
PASSWORD = "Kiefer-Wolke-Rhein-42"
COOKIE = "__Host-va_session"


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def store(clock: Clock) -> MemoryIdentityStore:
    return MemoryIdentityStore()


@pytest.fixture
def identity(store: MemoryIdentityStore, clock: Clock) -> IdentityService:
    service = IdentityService(store, hasher=PasswordHasher(n=2**10), clock=clock)
    service.create_user("dennis", PASSWORD, role="admin", email="dennis@example.com")
    service.create_user("anna", PASSWORD)
    return service


def _client(identity: IdentityService | None, settings: WebApiSettings = SETTINGS):
    client = TestClient(create_app(settings), base_url="https://testserver")
    client.__enter__()
    client.app.state.identity = identity  # type: ignore[attr-defined]
    return client


@pytest.fixture
def client(identity: IdentityService):
    c = _client(identity)
    yield c
    c.__exit__(None, None, None)


def _login(client: TestClient, username: str = "dennis", password: str = PASSWORD):
    return client.post("/api/v1/auth/login", json={"username": username, "password": password})


class TestLogin:
    def test_sets_the_session_cookie(self, client):
        response = _login(client)
        assert response.status_code == 204
        cookie = response.headers["set-cookie"]
        assert cookie.startswith(f"{COOKIE}=")
        attributes = {part.strip().lower() for part in cookie.split(";")}
        assert {"httponly", "secure", "samesite=strict", "path=/"} <= attributes

    def test_username_is_case_insensitive(self, client):
        assert _login(client, username=" Dennis ").status_code == 204

    def test_the_cookie_holds_only_the_id_and_the_store_only_its_hash(self, client, store):
        _login(client)
        token = client.cookies[COOKIE]
        assert token_hash(token) in store.session_ids()
        assert token not in store.session_ids()

    def test_wrong_password_and_unknown_user_look_the_same(self, client):
        wrong = _login(client, password="Falsch-Falsch-Falsch-1")
        unknown = _login(client, username="niemand")
        assert wrong.status_code == unknown.status_code == 401
        assert wrong.json() == unknown.json()
        assert "set-cookie" not in wrong.headers

    def test_a_disabled_account_cannot_log_in(self, client, identity, store):
        user = store.find_user("anna")
        assert user is not None
        store.set_status(user.id, "disabled", reason="test", at=identity.now())
        assert _login(client, username="anna").status_code == 401

    def test_every_attempt_is_logged(self, client, store):
        _login(client, password="Falsch-Falsch-Falsch-1")
        _login(client)
        assert [(e.username, e.ok, e.reason) for e in store.login_events()] == [
            ("dennis", False, "wrong_password"),
            ("dennis", True, "ok"),
        ]

    def test_unknown_fields_are_rejected(self, client):
        body = {"username": "dennis", "password": PASSWORD, "remember": True}
        assert client.post("/api/v1/auth/login", json=body).status_code == 422

    def test_a_rejected_body_does_not_echo_the_password(self, client):
        secret = "Geheim-" + "x" * 1100  # laenger als erlaubt
        response = client.post(
            "/api/v1/auth/login", json={"username": "dennis", "password": secret}
        )
        assert response.status_code == 422
        assert "Geheim-" not in response.text

    def test_only_json(self, client):
        response = client.post(
            "/api/v1/auth/login",
            content=b"username=dennis",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        assert response.status_code == 415


class TestLockout:
    def test_five_failures_lock_the_account(self, client):
        for _ in range(5):
            assert _login(client, password="Falsch-Falsch-Falsch-1").status_code == 401
        response = _login(client)  # richtiges Passwort, trotzdem gesperrt
        assert response.status_code == 429
        assert response.headers["retry-after"] == "900"

    def test_the_lock_ends_after_fifteen_minutes(self, client, clock):
        for _ in range(5):
            _login(client, password="Falsch-Falsch-Falsch-1")
        clock.now += timedelta(minutes=15, seconds=1)
        assert _login(client).status_code == 204

    def test_a_success_resets_the_account_counter(self, client):
        for _ in range(4):
            _login(client, password="Falsch-Falsch-Falsch-1")
        assert _login(client).status_code == 204
        assert _login(client, password="Falsch-Falsch-Falsch-1").status_code == 401
        assert _login(client).status_code == 204

    def test_five_failures_from_one_address_lock_every_account(self, client):
        for name in ("a1x", "a2x", "a3x", "a4x", "a5x"):
            _login(client, username=name)
        assert _login(client, username="anna").status_code == 429


class TestSession:
    def test_me_after_login(self, client):
        _login(client)
        response = client.get("/api/v1/me")
        assert response.status_code == 200
        assert response.json() == {
            "id": 1,
            "username": "dennis",
            "role": "admin",
            "display_name": None,
            "email": "dennis@example.com",
        }

    def test_me_without_session(self, client):
        assert client.get("/api/v1/me").status_code == 401

    def test_me_with_an_unknown_cookie(self, client):
        client.cookies.set(COOKIE, "erfunden", domain="testserver")
        assert client.get("/api/v1/me").status_code == 401

    def test_idle_too_long(self, client, clock):
        _login(client)
        clock.now += timedelta(hours=12, minutes=1)
        assert client.get("/api/v1/me").status_code == 401

    def test_activity_extends_the_idle_time(self, client, clock):
        _login(client)
        for _ in range(3):
            clock.now += timedelta(hours=11)
            assert client.get("/api/v1/me").status_code == 200

    def test_absolute_end_after_thirty_days(self, client, clock):
        _login(client)
        for _ in range(70):  # je knapp 12 h: nach gut 61 Schritten sind 30 Tage um
            clock.now += timedelta(hours=12) - timedelta(minutes=1)
            if client.get("/api/v1/me").status_code != 200:
                break
        assert clock.now - datetime(2026, 11, 6, 12, 0, tzinfo=UTC) >= timedelta(days=30)
        assert client.get("/api/v1/me").status_code == 401

    def test_a_disabled_account_loses_its_session(self, client, identity, store):
        _login(client, username="anna")
        user = store.find_user("anna")
        assert user is not None
        store.set_status(user.id, "disabled", reason="test", at=identity.now())
        assert client.get("/api/v1/me").status_code == 401


class TestLogout:
    def test_ends_the_session_on_the_server(self, client):
        _login(client)
        token = client.cookies[COOKIE]
        response = client.post("/api/v1/auth/logout", json={})
        assert response.status_code == 204
        assert (
            f'{COOKIE}=""' in response.headers["set-cookie"]
            or "Max-Age=0" in (response.headers["set-cookie"])
        )
        # Auch wer das alte Cookie noch hat, ist abgemeldet
        client.cookies.set(COOKIE, token, domain="testserver")
        assert client.get("/api/v1/me").status_code == 401

    def test_without_session_is_harmless(self, client):
        assert client.post("/api/v1/auth/logout", json={}).status_code == 204


class TestWithoutIdentityDatabase:
    def test_login_answers_503(self):
        c = _client(None)
        try:
            assert _login(c).status_code == 503
            assert c.get("/api/v1/me").status_code == 503
        finally:
            c.__exit__(None, None, None)


class TestLocalCookie:
    def test_without_https_the_cookie_is_not_secure(self, identity):
        settings = SETTINGS.model_copy(update={"cookie_secure": False})
        c = _client(identity, settings)
        try:
            response = _login(c)
            cookie = response.headers["set-cookie"]
            assert cookie.startswith("va_session=")
            assert "secure" not in {part.strip().lower() for part in cookie.split(";")}
        finally:
            c.__exit__(None, None, None)


def test_create_user_returns_what_it_stored(store, clock):
    service = IdentityService(store, hasher=PasswordHasher(n=2**10), clock=clock)
    user = service.create_user("lena", PASSWORD, display_name="  Lena  ")
    stored = store.get_user(user.id)
    assert stored is not None
    assert user.display_name == stored.display_name == "Lena"


def test_existing_endpoints_stay_open_until_d1_2(client):
    """D1.1 schuetzt nur die neuen Endpunkte; die Sitzungspflicht fuer alle kommt mit D1.2."""
    assert client.get("/api/v1/health").status_code == 200
