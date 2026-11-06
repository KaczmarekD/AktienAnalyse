"""Eigenes Konto und Nutzerverwaltung ueber die API (D1.4, NUT-11, Rollen).

- ``/me/*``: Passwort und Anzeigename aendern, Sitzungen sehen und ueberall abmelden.
- ``/admin/users``: Nutzer anlegen, deaktivieren, aktivieren, Einmal-Passwort setzen.
- Beides nur mit echter Sitzung, auch im Uebergang ohne Sitzungspflicht (``auth_required=false``):
  Dort gilt sonst jeder im LAN als Admin und koennte das Passwort des echten Admins zuruecksetzen.
- Ein Einmal-Passwort muss vor allem anderen ersetzt werden (``must_change``).

Ohne Datenbank, mit dem Speicher im Prozess und einer steuerbaren Uhr wie in
``test_identity_api.py``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import ClassVar

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from va_web_api.identity.domain import PasswordHasher
from va_web_api.identity.memory import MemoryIdentityStore
from va_web_api.identity.service import IdentityService
from va_web_api.main import create_app
from va_web_api.settings import WebApiSettings

SETTINGS = WebApiSettings(database_url=SecretStr("postgresql+psycopg://x:x@127.0.0.1:1/none"))
LAN = SETTINGS.model_copy(update={"auth_required": False})
PASSWORD = "Kiefer-Wolke-Rhein-42"
NEW_PASSWORD = "Ahorn-Nebel-Mosel-17"
ONE_TIME = "Birke-Regen-Elbe-2026"
COOKIE = "__Host-va_session"


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now


class Closed:
    """Was der Broadcaster trennen sollte (WebSockets der widerrufenen Sitzungen)."""

    def __init__(self) -> None:
        self.sessions: list[str] = []

    def publish(self, message) -> None:
        return

    def close_session(self, session: str) -> None:
        self.sessions.append(session)


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def store() -> MemoryIdentityStore:
    return MemoryIdentityStore()


@pytest.fixture
def identity(store: MemoryIdentityStore, clock: Clock) -> IdentityService:
    service = IdentityService(store, hasher=PasswordHasher(n=2**10), clock=clock)
    service.create_user("dennis", PASSWORD, role="admin", email="dennis@example.com")
    service.create_user("anna", PASSWORD, display_name="Anna")
    return service


@pytest.fixture
def closed() -> Closed:
    return Closed()


def _client(identity, closed, settings: WebApiSettings = SETTINGS, user_agent: str = "Browser A"):
    client = TestClient(
        create_app(settings), base_url="https://testserver", headers={"User-Agent": user_agent}
    )
    client.__enter__()
    client.app.state.identity = identity  # type: ignore[attr-defined]
    client.app.state.broadcaster = closed  # type: ignore[attr-defined]
    return client


@pytest.fixture
def client(identity, closed):
    c = _client(identity, closed)
    yield c
    c.__exit__(None, None, None)


@pytest.fixture
def second(identity, closed):
    """Ein zweiter Browser desselben Nutzers."""
    c = _client(identity, closed, user_agent="Browser B")
    yield c
    c.__exit__(None, None, None)


def _login(client: TestClient, username: str = "anna", password: str = PASSWORD) -> int:
    return client.post(
        "/api/v1/auth/login", json={"username": username, "password": password}
    ).status_code


def _change(client: TestClient, current: str = PASSWORD, new: str = NEW_PASSWORD):
    return client.put(
        "/api/v1/me/password", json={"current_password": current, "new_password": new}
    )


def _id(store: MemoryIdentityStore, name: str) -> int:
    user = store.find_user(name)
    assert user is not None
    return user.id


class TestChangePassword:
    def test_the_new_password_works_and_the_old_one_not(self, client, second):
        assert _login(client) == 204
        assert _change(client).status_code == 204
        assert _login(second, password=PASSWORD) == 401
        assert _login(second, password=NEW_PASSWORD) == 204

    def test_this_session_stays_and_the_others_end(self, client, second, closed):
        _login(client)
        _login(second)
        other = second.cookies[COOKIE]
        assert _change(client).status_code == 204
        assert client.get("/api/v1/me").status_code == 200
        assert second.get("/api/v1/me").status_code == 401
        # Die WebSockets der anderen Sitzung trennt der Hub
        from va_web_api.identity.domain import token_hash

        assert closed.sessions == [token_hash(other)]

    def test_the_current_password_is_needed(self, client):
        _login(client)
        response = _change(client, current="Falsch-Falsch-Falsch-1")
        assert response.status_code == 400
        assert "bisherige" in response.json()["detail"]
        assert _login(client, password=PASSWORD) == 204

    def test_wrong_current_passwords_lock_like_failed_logins(self, client, store):
        """Sonst liesse sich mit einer gestohlenen Sitzung das Passwort durchprobieren."""
        _login(client)
        for _ in range(5):
            assert _change(client, current="Falsch-Falsch-Falsch-1").status_code == 400
        response = _change(client)  # richtig, aber gesperrt
        assert response.status_code == 429
        assert "retry-after" in response.headers
        assert [e.reason for e in store.login_events()][-6:] == ["wrong_password"] * 5 + ["locked"]

    def test_wrong_current_passwords_lock_only_this_account(self, client, second):
        """Hinter nginx teilen sich alle eine Adresse: Andere duerfen sich weiter anmelden."""
        _login(client)
        for _ in range(5):
            _change(client, current="Falsch-Falsch-Falsch-1")
        assert _login(second, username="dennis") == 204
        assert _login(second) == 429  # anna selbst bleibt gesperrt

    def test_the_rules_for_new_passwords_apply(self, client):
        _login(client)
        response = _change(client, new="zu-kurz")
        assert response.status_code == 400
        assert "12 Zeichen" in response.json()["detail"]

    def test_the_new_password_must_differ(self, client):
        _login(client)
        assert _change(client, new=PASSWORD).status_code == 400

    def test_a_rejected_body_does_not_echo_the_passwords(self, client):
        _login(client)
        response = client.put(
            "/api/v1/me/password",
            json={"current_password": "Geheim-alt", "new_password": "Geheim-" + "x" * 1100},
        )
        assert response.status_code == 422
        assert "Geheim-" not in response.text


class TestProfile:
    def test_change_the_display_name(self, client):
        _login(client)
        response = client.put("/api/v1/me/profile", json={"display_name": "  Anna B.  "})
        assert response.status_code == 200
        assert response.json()["display_name"] == "Anna B."
        assert client.get("/api/v1/me").json()["display_name"] == "Anna B."

    def test_an_empty_name_removes_it(self, client):
        _login(client)
        assert client.put("/api/v1/me/profile", json={"display_name": " "}).status_code == 200
        assert client.get("/api/v1/me").json()["display_name"] is None

    def test_the_mail_address_stays(self, client):
        _login(client, username="dennis")
        client.put("/api/v1/me/profile", json={"display_name": "Dennis"})
        assert client.get("/api/v1/me").json()["email"] == "dennis@example.com"


class TestEmailChange:
    """D1.6 (NUT-10): Eine neue Adresse gilt erst nach Bestaetigung per Link (24 h, einmalig).
    Der Link geht ueber das private Event an notification, nie in einer Antwort zurueck."""

    ORIGIN: ClassVar[dict[str, str]] = {"Origin": "https://testserver"}

    def _change(self, client: TestClient, email: str = "neu@example.com"):
        return client.put(
            "/api/v1/me/profile",
            json={"display_name": "Anna", "email": email},
            headers=self.ORIGIN,
        )

    def _token(self, store: MemoryIdentityStore) -> str:
        from urllib.parse import parse_qs, urlsplit

        envelope = store.outbox()[-1]
        assert envelope.type == "identity.email_confirmation.requested"
        return parse_qs(urlsplit(envelope.data.link).query)["token"][0]

    def test_the_new_address_waits_for_confirmation(self, client, store):
        _login(client, username="dennis")
        response = self._change(client)
        assert response.status_code == 200
        me = response.json()
        assert (me["email"], me["pending_email"]) == ("dennis@example.com", "neu@example.com")
        [envelope] = store.outbox()
        assert envelope.data.email == "neu@example.com"
        assert envelope.data.link.startswith("https://testserver/confirm-email?token=")
        assert "token" not in response.text  # der Link steht nur in der Mail

    def test_confirming_without_session_sets_the_address(self, client, second, store):
        _login(client, username="dennis")
        self._change(client)
        token = self._token(store)
        # Der Link kann in einem anderen Browser ohne Sitzung geoeffnet werden
        response = second.post("/api/v1/auth/confirm-email", json={"token": token})
        assert response.status_code == 204
        me = client.get("/api/v1/me").json()
        assert (me["email"], me["pending_email"]) == ("neu@example.com", None)

    def test_a_link_works_once(self, client, second, store):
        _login(client, username="dennis")
        self._change(client)
        token = self._token(store)
        assert second.post("/api/v1/auth/confirm-email", json={"token": token}).status_code == 204
        again = second.post("/api/v1/auth/confirm-email", json={"token": token})
        assert again.status_code == 400

    def test_a_link_expires_after_a_day(self, client, second, store, clock):
        _login(client, username="dennis")
        self._change(client)
        token = self._token(store)
        clock.now += timedelta(hours=24, minutes=1)
        response = second.post("/api/v1/auth/confirm-email", json={"token": token})
        assert response.status_code == 400
        assert "abgelaufen" in response.json()["detail"]

    def test_only_the_newest_link_counts(self, client, second, store):
        _login(client, username="dennis")
        self._change(client, "eins@example.com")
        first = self._token(store)
        self._change(client, "zwei@example.com")
        assert second.post("/api/v1/auth/confirm-email", json={"token": first}).status_code == 400
        assert client.get("/api/v1/me").json()["pending_email"] == "zwei@example.com"

    def test_an_unknown_link(self, second):
        response = second.post("/api/v1/auth/confirm-email", json={"token": "erfunden"})
        assert response.status_code == 400

    def test_the_same_address_needs_no_confirmation(self, client, store):
        _login(client, username="dennis")
        response = self._change(client, "dennis@example.com")
        assert response.status_code == 200
        assert response.json()["pending_email"] is None
        assert store.outbox() == []

    def test_an_invalid_address_is_rejected(self, client):
        _login(client)
        assert self._change(client, "keine-adresse").status_code == 400

    def test_without_origin_no_link_can_be_built(self, client):
        """Ohne Browser-Herkunft und ohne WEB_API_ALLOWED_ORIGINS kennt das web-api die
        Adresse des UI nicht und kann keinen Link bauen."""
        _login(client)
        response = client.put(
            "/api/v1/me/profile", json={"display_name": "Anna", "email": "neu@example.com"}
        )
        assert response.status_code == 400


class TestExport:
    """D1.6 (NUT-12): alle eigenen Daten als JSON-Datei, ohne Hashes und Tokens."""

    def test_downloads_the_own_data(self, client, store):
        _login(client)
        response = client.get("/api/v1/me/export")
        assert response.status_code == 200
        assert "attachment" in response.headers["content-disposition"]
        assert response.headers["content-disposition"].endswith('.json"')
        data = response.json()
        assert data["account"][0]["username"] == "anna"
        assert "scrypt$" not in response.text
        assert "dennis" not in response.text  # nichts von anderen Konten

    def test_needs_a_session(self, client):
        assert client.get("/api/v1/me/export").status_code == 401


class TestSessions:
    def test_lists_the_own_valid_sessions(self, client, second, clock):
        _login(client)
        clock.now += timedelta(minutes=5)
        _login(second)
        sessions = client.get("/api/v1/me/sessions").json()
        assert [(s["user_agent"], s["current"]) for s in sessions] == [
            ("Browser B", False),
            ("Browser A", True),
        ]
        assert set(sessions[0]) == {
            "created_at",
            "last_seen",
            "expires_at",
            "user_agent",
            "current",
        }

    def test_ended_and_foreign_sessions_are_not_listed(self, client, second, identity):
        _login(client)
        _login(second, username="dennis")
        _login(second)  # neue Sitzung im zweiten Browser, die von dennis bleibt bestehen
        second.post("/api/v1/auth/logout", json={})
        assert [s["current"] for s in client.get("/api/v1/me/sessions").json()] == [True]

    def test_log_out_everywhere(self, client, second, closed):
        _login(client)
        _login(second)
        response = client.post("/api/v1/me/sessions/revoke-all", json={})
        assert response.status_code == 204
        assert client.get("/api/v1/me").status_code == 401
        assert second.get("/api/v1/me").status_code == 401
        assert len(closed.sessions) == 2


class TestAdmin:
    def _admin(self, client: TestClient) -> None:
        assert _login(client, username="dennis") == 204

    def test_list_users(self, client):
        self._admin(client)
        users = client.get("/api/v1/admin/users").json()
        assert [(u["username"], u["role"], u["active"]) for u in users] == [
            ("dennis", "admin", True),
            ("anna", "user", True),
        ]
        assert set(users[0]) == {
            "id",
            "username",
            "role",
            "display_name",
            "email",
            "active",
            "must_change_password",
            "created_at",
        }

    def test_create_a_user_with_a_one_time_password(self, client, second):
        self._admin(client)
        response = client.post(
            "/api/v1/admin/users",
            json={
                "username": "Lena",
                "role": "user",
                "display_name": "Lena",
                "email": "lena@example.com",
                "one_time_password": ONE_TIME,
            },
        )
        assert response.status_code == 201
        created = response.json()
        assert (created["username"], created["must_change_password"]) == ("lena", True)
        assert "one_time_password" not in created
        assert _login(second, username="lena", password=ONE_TIME) == 204
        assert second.get("/api/v1/me").json()["must_change_password"] is True

    def test_an_existing_name_is_a_conflict(self, client):
        self._admin(client)
        response = client.post(
            "/api/v1/admin/users", json={"username": "anna", "one_time_password": ONE_TIME}
        )
        assert response.status_code == 409

    @pytest.mark.parametrize(
        "body",
        [
            {"username": "x", "one_time_password": ONE_TIME},  # zu kurzer Name
            {"username": "lena", "one_time_password": "kurz"},  # schwaches Passwort
            {"username": "lena", "one_time_password": ONE_TIME, "email": "keine-adresse"},
        ],
    )
    def test_invalid_input_is_rejected(self, client, body):
        self._admin(client)
        assert client.post("/api/v1/admin/users", json=body).status_code == 400

    def test_disable_ends_the_sessions_and_enable_needs_a_new_login(
        self, client, second, store, closed
    ):
        self._admin(client)
        _login(second)
        anna = _id(store, "anna")
        assert client.post(f"/api/v1/admin/users/{anna}/disable", json={}).status_code == 204
        assert second.get("/api/v1/me").status_code == 401
        assert len(closed.sessions) == 1
        assert _login(second) == 401
        assert client.post(f"/api/v1/admin/users/{anna}/enable", json={}).status_code == 204
        # Die alte Sitzung bleibt widerrufen, eine neue Anmeldung geht
        assert second.get("/api/v1/me").status_code == 401
        assert _login(second) == 204

    def test_reset_password(self, client, second, store):
        self._admin(client)
        _login(second)
        anna = _id(store, "anna")
        response = client.post(
            f"/api/v1/admin/users/{anna}/reset-password", json={"one_time_password": ONE_TIME}
        )
        assert response.status_code == 204
        assert second.get("/api/v1/me").status_code == 401
        assert _login(second, password=PASSWORD) == 401
        assert _login(second, password=ONE_TIME) == 204
        assert second.get("/api/v1/me").json()["must_change_password"] is True

    @pytest.mark.parametrize("action", ["disable", "reset-password"])
    def test_not_on_the_own_account(self, client, store, action):
        """So bleibt immer ein Admin uebrig, der sich anmelden kann."""
        self._admin(client)
        dennis = _id(store, "dennis")
        response = client.post(
            f"/api/v1/admin/users/{dennis}/{action}", json={"one_time_password": ONE_TIME}
        )
        assert response.status_code == 409

    @pytest.mark.parametrize("action", ["disable", "enable", "reset-password"])
    def test_unknown_user(self, client, action):
        self._admin(client)
        response = client.post(
            f"/api/v1/admin/users/4711/{action}", json={"one_time_password": ONE_TIME}
        )
        assert response.status_code == 404

    def test_a_user_is_not_an_admin(self, client):
        _login(client)
        assert client.get("/api/v1/admin/users").status_code == 403

    @pytest.mark.parametrize(
        "path", ["/api/v1/admin/users", "/api/v1/admin/users/2/reset-password"]
    )
    def test_a_rejected_body_does_not_echo_the_password(self, client, path):
        self._admin(client)
        secret = "Geheim-" + "x" * 1100  # laenger als erlaubt
        response = client.post(path, json={"username": "lena", "one_time_password": secret})
        assert response.status_code == 422
        assert "Geheim-" not in response.text


class TestOneTimePassword:
    """Mit ``must_change`` geht nichts ausser dem eigenen Konto, bis das Passwort neu ist."""

    @pytest.fixture
    def lena(self, client, identity, store):
        # Wie vom Admin angelegt
        identity.create_user("lena", ONE_TIME, must_change=True)
        assert _login(client, username="lena", password=ONE_TIME) == 204
        return client

    def test_other_endpoints_answer_403(self, lena):
        response = lena.get("/api/v1/runs")
        assert response.status_code == 403
        assert "Passwort" in response.json()["detail"]

    def test_the_own_account_and_logout_stay_open(self, lena):
        assert lena.get("/api/v1/me").status_code == 200
        assert lena.get("/api/v1/me/sessions").status_code == 200

    def test_after_the_change_everything_opens(self, lena):
        assert _change(lena, current=ONE_TIME).status_code == 204
        assert lena.get("/api/v1/me").json()["must_change_password"] is False
        assert lena.get("/api/v1/runs").status_code not in (401, 403)

    def test_an_admin_with_a_one_time_password_cannot_manage_users(self, client, identity):
        identity.create_user("chef", ONE_TIME, role="admin", must_change=True)
        _login(client, username="chef", password=ONE_TIME)
        assert client.get("/api/v1/admin/users").status_code == 403


class TestTransition:
    """Ohne Sitzungspflicht (NAS bis D1.5) gilt jeder im LAN als Admin, aber nicht hier."""

    @pytest.fixture
    def lan(self, identity, closed):
        c = _client(identity, closed, LAN)
        yield c
        c.__exit__(None, None, None)

    @pytest.mark.parametrize(
        ("method", "path"),
        [
            ("GET", "/api/v1/admin/users"),
            ("POST", "/api/v1/admin/users"),
            ("POST", "/api/v1/admin/users/1/reset-password"),
            ("POST", "/api/v1/admin/users/2/disable"),
            ("PUT", "/api/v1/me/password"),
            ("GET", "/api/v1/me/sessions"),
        ],
    )
    def test_needs_a_real_session(self, lan, method, path):
        body = None if method == "GET" else {"one_time_password": ONE_TIME}
        assert lan.request(method, path, json=body).status_code == 401

    def test_with_a_real_admin_session_it_works(self, lan):
        assert _login(lan, username="dennis") == 204
        assert lan.get("/api/v1/admin/users").status_code == 200
