"""Sitzungspflicht und Rollen fuer alle Endpunkte (D1.2, NUT-02, NUT-03, NUT-09).

- Mit ``auth_required`` (Standard) braucht jeder Endpunkt eine Sitzung, ausser Health, Login,
  Logout und der API-Beschreibung. Eine Tabelle aller Routen stellt sicher, dass kein neuer
  Endpunkt ohne Schutz entsteht.
- Run starten, Profil speichern und aktivieren duerfen nur Admins.
- Schreibende Anfragen mit fremdem ``Origin`` ergeben 403, auch mit gueltigem Cookie.
- Uebergang bis D1.4/D1.5: Mit ``auth_required=false`` verhaelt sich alles wie vor D1.2 (ADR-0007).
  Ausnahme seit D1.4: das eigene Konto (``/me``) und die Nutzerverwaltung (``/admin``) nur mit
  echter Sitzung.
- Mit Einmal-Passwort (``must_change``, D1.4) nur das eigene Konto und Abmelden, sonst 403.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from va_contracts.events.v1 import RunOptionsV1
from va_web_api.identity.domain import PasswordHasher
from va_web_api.identity.memory import MemoryIdentityStore
from va_web_api.identity.service import IdentityService
from va_web_api.main import create_app
from va_web_api.settings import WebApiSettings

NO_DB = "postgresql+psycopg://x:x@127.0.0.1:1/none"
SETTINGS = WebApiSettings(database_url=SecretStr(NO_DB))
LAN = SETTINGS.model_copy(update={"auth_required": False})
PASSWORD = "Kiefer-Wolke-Rhein-42"
COOKIE = "__Host-va_session"
ORIGIN = "https://testserver"

# Ohne Sitzung erreichbar (NUT-09): kein Zugriff auf Daten
OPEN = {
    ("GET", "/api/v1/health"),
    ("POST", "/api/v1/auth/login"),
    ("POST", "/api/v1/auth/logout"),
    ("GET", "/api/v1/auth/session"),  # D1.4: wer angemeldet ist, ohne 401
    ("POST", "/api/v1/auth/confirm-email"),  # D1.6: das Token im Link ist der Nachweis
}
ADMIN_ONLY = {
    ("POST", "/api/v1/runs"),
    ("PUT", "/api/v1/scoring/profiles/{profile_id}"),
    ("POST", "/api/v1/scoring/profiles/{profile_id}/activate"),
    # D1.4: Nutzerverwaltung
    ("GET", "/api/v1/admin/users"),
    ("POST", "/api/v1/admin/users"),
    ("POST", "/api/v1/admin/users/{user_id}/disable"),
    ("POST", "/api/v1/admin/users/{user_id}/enable"),
    ("POST", "/api/v1/admin/users/{user_id}/reset-password"),
}
# D1.4: auch im Uebergang nur mit echter Sitzung; mit Einmal-Passwort erlaubt (ausser /admin)
OWN_ACCOUNT = "/api/v1/me"
ADMIN = "/api/v1/admin"
PATH_VALUES = {
    "{run_id}": "1",
    "{scoring_run_id}": "1",
    "{symbol}": "SAP.DE",
    "{report_id}": "1",
    "{profile_id}": "1",
    "{user_id}": "2",
}


@dataclass
class FakeRuns:
    calls: list[RunOptionsV1] = field(default_factory=list)

    def start(self, options: RunOptionsV1) -> int:
        self.calls.append(options)
        return 7


def _routes() -> list[tuple[str, str]]:
    """Alle Endpunkte aus der API-Beschreibung (``app.routes`` bindet Router verzoegert ein)."""
    paths = create_app(SETTINGS).openapi()["paths"]
    routes = sorted(
        (method.upper(), path)
        for path, operations in paths.items()
        if path.startswith("/api/v1")
        for method in operations
    )
    assert routes, "keine Endpunkte gefunden"
    return routes


def _concrete(path: str) -> str:
    for placeholder, value in PATH_VALUES.items():
        path = path.replace(placeholder, value)
    return path


@pytest.fixture
def identity() -> IdentityService:
    service = IdentityService(MemoryIdentityStore(), hasher=PasswordHasher(n=2**10))
    service.create_user("dennis", PASSWORD, role="admin")
    service.create_user("anna", PASSWORD)
    return service


def _client(settings: WebApiSettings, identity: IdentityService | None, runs: FakeRuns):
    client = TestClient(create_app(settings), base_url="https://testserver")
    client.__enter__()
    client.app.state.identity = identity  # type: ignore[attr-defined]
    client.app.state.runs = runs  # type: ignore[attr-defined]
    return client


@pytest.fixture
def runs() -> FakeRuns:
    return FakeRuns()


@pytest.fixture
def client(identity, runs):
    c = _client(SETTINGS, identity, runs)
    yield c
    c.__exit__(None, None, None)


def _login(client: TestClient, username: str) -> None:
    response = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": PASSWORD},
        headers={"Origin": ORIGIN},
    )
    assert response.status_code == 204


def test_the_route_table_is_complete():
    """Ein neuer Endpunkt faellt hier auf und braucht eine Entscheidung: offen oder geschuetzt."""
    routes = set(_routes())
    assert routes >= OPEN
    assert routes >= ADMIN_ONLY


@pytest.mark.parametrize(("method", "path"), _routes())
def test_without_session_only_the_open_routes_answer(client, method, path):
    response = client.request(method, _concrete(path), json={} if method != "GET" else None)
    if (method, path) in OPEN:
        assert response.status_code != 401, (method, path)
    else:
        assert response.status_code == 401, (method, path)


@pytest.mark.parametrize(("method", "path"), sorted(ADMIN_ONLY))
def test_a_user_may_not_change_the_system(client, method, path):
    _login(client, "anna")
    response = client.request(method, _concrete(path), json={}, headers={"Origin": ORIGIN})
    assert response.status_code == 403


def test_an_admin_may_start_a_run(client, runs):
    _login(client, "dennis")
    response = client.post("/api/v1/runs", json={}, headers={"Origin": ORIGIN})
    assert response.status_code == 202
    assert len(runs.calls) == 1


def test_a_user_may_read(client):
    _login(client, "anna")
    # Ohne Datenbank antwortet das Lesemodell mit 503, aber nicht mit 401 oder 403
    assert client.get("/api/v1/runs").status_code not in (401, 403)


def test_a_user_may_preview(client):
    _login(client, "anna")
    response = client.post("/api/v1/scoring/preview", json={}, headers={"Origin": ORIGIN})
    assert response.status_code not in (401, 403)


class TestOrigin:
    def test_a_foreign_origin_cannot_write_even_when_logged_in(self, client, runs):
        _login(client, "dennis")
        response = client.post("/api/v1/runs", json={}, headers={"Origin": "http://boese.example"})
        assert response.status_code == 403
        assert runs.calls == []

    def test_a_foreign_origin_cannot_log_in(self, client):
        response = client.post(
            "/api/v1/auth/login",
            json={"username": "dennis", "password": PASSWORD},
            headers={"Origin": "http://boese.example"},
        )
        assert response.status_code == 403

    def test_without_origin_writing_is_allowed(self, client, runs):
        """Kein Browser (curl, Skripte): Ohne Origin gibt es keinen CSRF-Angriffsweg."""
        _login(client, "dennis")
        assert client.post("/api/v1/runs", json={}).status_code == 202

    def test_reading_ignores_the_origin(self, client):
        assert (
            client.get("/api/v1/health", headers={"Origin": "http://boese.example"}).status_code
            == 200
        )


class TestWebSocket:
    """D1.2: Mit Sitzungspflicht auch der WebSocket nur mit Sitzung (Topics je Nutzer: D1.3)."""

    def _connect(self, client: TestClient):
        # Der Testclient haengt Cookies nicht an den Handshake; der Browser tut es
        headers = {"origin": ORIGIN}
        if COOKIE in client.cookies:
            headers["cookie"] = f"{COOKIE}={client.cookies[COOKIE]}"
        return client.websocket_connect("/ws", subprotocols=["va.v1"], headers=headers)

    def test_without_session_no_handshake(self, client):
        from starlette.websockets import WebSocketDisconnect

        with pytest.raises(WebSocketDisconnect), self._connect(client) as ws:
            ws.receive_json()

    def test_with_session_hello(self, client):
        _login(client, "anna")
        with self._connect(client) as ws:
            assert ws.receive_json()["op"] == "hello"


class TestLanTransition:
    """Bis D1.4 (lokal) und D1.5 (NAS) setzen die Compose-Dateien ``auth_required=false``."""

    @pytest.fixture
    def lan(self, runs):
        c = _client(LAN, None, runs)
        yield c
        c.__exit__(None, None, None)

    def test_everything_answers_without_session(self, lan, runs):
        assert lan.post("/api/v1/runs", json={}).status_code == 202
        assert len(runs.calls) == 1

    def test_me_still_needs_a_real_session(self, lan):
        assert lan.get("/api/v1/me").status_code == 503  # ohne Identitaets-Datenbank

    def test_the_origin_check_applies_anyway(self, lan, runs):
        response = lan.post("/api/v1/runs", json={}, headers={"Origin": "http://boese.example"})
        assert response.status_code == 403
        assert runs.calls == []

    @pytest.mark.parametrize(
        ("method", "path"),
        [r for r in _routes() if r[1].startswith((OWN_ACCOUNT, ADMIN))],
    )
    def test_own_account_and_user_management_need_a_real_session(
        self, identity, runs, method, path
    ):
        """D1.4: Sonst koennte im LAN jeder als ``LAN_USER`` Konten anlegen und Passwoerter
        zuruecksetzen, auch das des echten Admins."""
        c = _client(LAN, identity, runs)
        try:
            response = c.request(method, _concrete(path), json={} if method != "GET" else None)
            assert response.status_code == 401, (method, path)
        finally:
            c.__exit__(None, None, None)


class TestOneTimePassword:
    """D1.4: Bis das Einmal-Passwort ersetzt ist, nur das eigene Konto und Abmelden."""

    @pytest.fixture
    def lena(self, client, identity):
        identity.create_user("lena", PASSWORD, role="admin", must_change=True)
        _login(client, "lena")
        return client

    @pytest.mark.parametrize(("method", "path"), _routes())
    def test_everything_else_answers_403(self, lena, method, path):
        response = lena.request(
            method,
            _concrete(path),
            json={} if method != "GET" else None,
            headers={"Origin": ORIGIN},
        )
        if (method, path) in OPEN or path.startswith(OWN_ACCOUNT):
            assert response.status_code not in (401, 403), (method, path)
        else:
            assert response.status_code == 403, (method, path)

    def test_no_websocket(self, lena):
        from starlette.websockets import WebSocketDisconnect

        headers = {"origin": ORIGIN, "cookie": f"{COOKIE}={lena.cookies[COOKIE]}"}
        with (
            pytest.raises(WebSocketDisconnect),
            lena.websocket_connect("/ws", subprotocols=["va.v1"], headers=headers) as ws,
        ):
            ws.receive_json()


def test_the_default_requires_a_session():
    assert SETTINGS.auth_required is True
