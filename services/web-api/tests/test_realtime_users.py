"""WebSocket je Nutzer (D1.3, NUT-08): eigene Topics, Trennen beim Ende der Sitzung.

- ``user:<id>`` abonniert nur dieser Nutzer; sonst ``error`` mit Code ``forbidden``.
- Die globalen Topics (``runs``, ``ranking``, ``profiles``) bekommt jeder Angemeldete.
- Abmelden trennt die Verbindungen dieser Sitzung (Code 4401), andere Sitzungen bleiben.
- Endet die Sitzung anders (Konto deaktiviert, abgelaufen), trennt die Pruefung im Takt. Die
  Pruefung verlaengert die Sitzung nicht.

Kein Test wartet blind: Nach jeder Aktion folgt ein ``ping``. Kommt ``pong`` statt der erwarteten
Meldung oder Trennung, schlaegt der Test fehl, statt zu haengen.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from starlette.websockets import WebSocketDisconnect

from va_web_api.events import EventMessage
from va_web_api.identity.domain import PasswordHasher
from va_web_api.identity.memory import MemoryIdentityStore
from va_web_api.identity.service import IdentityService
from va_web_api.main import create_app
from va_web_api.realtime import endpoint
from va_web_api.realtime.protocol import ProtocolError, parse_client_message
from va_web_api.settings import WebApiSettings

if TYPE_CHECKING:
    from starlette.testclient import WebSocketTestSession

SETTINGS = WebApiSettings(database_url=SecretStr("postgresql+psycopg://x:x@127.0.0.1:1/none"))
PASSWORD = "Kiefer-Wolke-Rhein-42"
COOKIE = "__Host-va_session"
ORIGIN = "https://testserver"
CLOSE_SESSION_ENDED = 4401


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def store() -> MemoryIdentityStore:
    return MemoryIdentityStore()


@pytest.fixture
def identity(store, clock) -> IdentityService:
    service = IdentityService(store, hasher=PasswordHasher(n=2**10), clock=clock)
    service.create_user("dennis", PASSWORD, role="admin")  # id 1
    service.create_user("anna", PASSWORD)  # id 2
    return service


@pytest.fixture
def make_client(identity):
    clients: list[TestClient] = []

    def make(settings: WebApiSettings = SETTINGS) -> TestClient:
        client = TestClient(create_app(settings), base_url="https://testserver")
        client.__enter__()
        client.app.state.identity = identity  # type: ignore[attr-defined]
        clients.append(client)
        return client

    yield make
    for client in clients:
        client.__exit__(None, None, None)


def _login(client: TestClient, username: str) -> str:
    response = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": PASSWORD},
        headers={"Origin": ORIGIN},
    )
    assert response.status_code == 204
    return client.cookies[COOKIE]


def _connect(client: TestClient, token: str | None):
    # Der Testclient haengt Cookies nicht an den Handshake; der Browser tut es
    headers = {"origin": ORIGIN}
    if token is not None:
        headers["cookie"] = f"{COOKIE}={token}"
    return client.websocket_connect("/ws", subprotocols=["va.v1"], headers=headers)


def _publish(client: TestClient, topic: str) -> None:
    message = EventMessage(topic=topic, type="test.event", seq=None, data={"x": 1})
    client.app.state.broadcaster.publish(message)  # type: ignore[attr-defined]


def _until_pong(ws: WebSocketTestSession, rounds: int = 2) -> list[dict[str, Any]]:
    """Alle Meldungen bis zum ``rounds``-ten ``pong``. Haengt nie: Jedes ``ping`` wird beantwortet.

    Zwei Runden, weil ein Event aus einem anderen Thread erst nach dem ersten ``pong`` ankommen kann.
    """
    seen: list[dict[str, Any]] = []
    for _ in range(rounds):
        ws.send_json({"op": "ping"})
        while (message := ws.receive_json())["op"] != "pong":
            seen.append(message)
    return seen


def _closed_code(ws: WebSocketTestSession) -> int:
    """Code der Trennung; kommt stattdessen ``pong``, ist die Verbindung offen: Fehlschlag."""
    ws.send_json({"op": "ping"})
    with pytest.raises(WebSocketDisconnect) as closed:
        _skip_until_pong(ws)
    return closed.value.code


def _skip_until_pong(ws: WebSocketTestSession) -> None:
    while ws.receive_json()["op"] != "pong":
        pass


class TestTopics:
    def test_the_pattern_knows_user_topics(self):
        message = parse_client_message('{"op": "subscribe", "topics": ["user:12", "runs"]}')
        assert message.topics == ["user:12", "runs"]  # type: ignore[union-attr]

    @pytest.mark.parametrize("topic", ["user:0", "user:abc", "user:", "user:-1", "user:1x"])
    def test_invalid_user_topics(self, topic):
        with pytest.raises(ProtocolError):
            parse_client_message(f'{{"op": "subscribe", "topics": ["{topic}"]}}')

    def test_own_topic_gets_its_events(self, make_client):
        client = make_client()
        token = _login(client, "anna")
        with _connect(client, token) as ws:
            assert ws.receive_json()["op"] == "hello"
            ws.send_json({"op": "subscribe", "topics": ["user:2"]})
            assert _until_pong(ws, rounds=1) == []  # Abo verarbeitet, kein Fehler
            _publish(client, "user:2")
            events = _until_pong(ws)
            assert [(e["op"], e["topic"]) for e in events] == [("event", "user:2")]

    def test_a_foreign_user_topic_is_forbidden(self, make_client):
        client = make_client()
        token = _login(client, "anna")
        with _connect(client, token) as ws:
            ws.receive_json()
            ws.send_json({"op": "subscribe", "topics": ["runs", "user:1"]})
            [error] = _until_pong(ws, rounds=1)
            assert (error["op"], error["code"]) == ("error", "forbidden")
            # Keins der Topics aus der Nachricht ist abonniert
            _publish(client, "user:1")
            _publish(client, "runs")
            assert _until_pong(ws) == []

    def test_global_topics_for_every_user(self, make_client):
        client = make_client()
        token = _login(client, "anna")
        with _connect(client, token) as ws:
            ws.receive_json()
            ws.send_json({"op": "subscribe", "topics": ["runs", "ranking", "profiles"]})
            assert _until_pong(ws, rounds=1) == []
            _publish(client, "ranking")
            assert [e["topic"] for e in _until_pong(ws)] == ["ranking"]

    def test_lan_transition_gets_no_user_topic(self, make_client):
        client = make_client(SETTINGS.model_copy(update={"auth_required": False}))
        with _connect(client, None) as ws:
            ws.receive_json()
            ws.send_json({"op": "subscribe", "topics": ["user:1"]})
            [error] = _until_pong(ws, rounds=1)
            assert error["code"] == "forbidden"


class TestSessionEnd:
    def test_logout_closes_the_sockets_of_this_session(self, make_client):
        client = make_client()
        token = _login(client, "anna")
        with _connect(client, token) as ws:
            ws.receive_json()
            response = client.post("/api/v1/auth/logout", json={}, headers={"Origin": ORIGIN})
            assert response.status_code == 204
            time.sleep(0.1)  # die Trennung kommt aus dem Threadpool ueber die Event-Loop
            assert _closed_code(ws) == CLOSE_SESSION_ENDED

    def test_other_sessions_stay_connected(self, make_client):
        first, second = make_client(), make_client()
        token_a = _login(first, "anna")
        token_b = _login(second, "anna")
        with _connect(first, token_a) as ws_a, _connect(second, token_b) as ws_b:
            ws_a.receive_json()
            ws_b.receive_json()
            first.post("/api/v1/auth/logout", json={}, headers={"Origin": ORIGIN})
            time.sleep(0.1)
            assert _closed_code(ws_a) == CLOSE_SESSION_ENDED
            assert _until_pong(ws_b, rounds=1) == []

    def test_a_disabled_account_is_disconnected(self, make_client, store, identity, monkeypatch):
        monkeypatch.setattr(endpoint, "SESSION_CHECK_SECONDS", 0.05)
        client = make_client()
        token = _login(client, "anna")
        with _connect(client, token) as ws:
            ws.receive_json()
            user = store.find_user("anna")
            assert user is not None
            store.set_status(user.id, "disabled", reason="test", at=identity.now())
            time.sleep(0.3)
            assert _closed_code(ws) == CLOSE_SESSION_ENDED

    def test_the_check_does_not_extend_the_session(self, make_client, clock, monkeypatch):
        """Ein offener Tab haelt die Sitzung nicht am Leben: Die Pruefung verlaengert nichts.

        Verlaengerte sie, waere die Sitzung nach 12 h 1 min noch gueltig (zuletzt gesehen bei 11 h).
        """
        monkeypatch.setattr(endpoint, "SESSION_CHECK_SECONDS", 0.05)
        client = make_client()
        token = _login(client, "anna")
        with _connect(client, token) as ws:
            ws.receive_json()
            clock.now += timedelta(hours=11)
            time.sleep(0.3)  # mehrere Pruefungen bei 11 h
            clock.now += timedelta(hours=1, minutes=1)
            time.sleep(0.3)
            assert _closed_code(ws) == CLOSE_SESSION_ENDED
