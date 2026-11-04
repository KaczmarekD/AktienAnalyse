"""WebSocket-Hub und Protokoll v1 (P4.5, docs/architecture/web-api-realtime.md) 🔒.

Der Endpunkt ``/ws`` laeuft mit dem TestClient von Starlette, ohne Datenbank und ohne NATS.
Events kommen ueber den ``HubBroadcaster`` der App, wie spaeter aus den Threads des
Eventmanagers. Das Nachspielen (``resumeFrom``) uebernimmt ein Fake-Replayer.
"""

from __future__ import annotations

import asyncio
import json
import threading
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from starlette.websockets import WebSocketDisconnect

from va_web_api.events import EventMessage
from va_web_api.main import create_app
from va_web_api.realtime.hub import HubBroadcaster, WebSocketHub
from va_web_api.realtime.protocol import PROTOCOL, event_payload
from va_web_api.settings import WebApiSettings

SETTINGS = WebApiSettings(database_url=SecretStr("postgresql+psycopg://va_read:x@127.0.0.1:1/none"))
ORIGIN = "http://testserver"  # Host des TestClient: dieselbe Herkunft


def _connect(
    client: TestClient, *, origin: str | None = ORIGIN, protocols: list[str] | None = None
):
    headers = {} if origin is None else {"origin": origin}
    return client.websocket_connect(
        "/ws", subprotocols=[PROTOCOL] if protocols is None else protocols, headers=headers
    )


def _event(topic: str, seq: int | None, type_: str = "screening.run.requested", **data: Any):
    return EventMessage(topic=topic, type=type_, seq=seq, data=data or {"run_id": 1})


class FakeReplayer:
    def __init__(self, events: list[EventMessage] | None, last: int | None = 10) -> None:
        self.events = events
        self.last = last
        self.asked: list[tuple[tuple[str, ...], int]] = []
        self.release = threading.Event()
        self.release.set()

    async def last_seq(self) -> int | None:
        return self.last

    async def replay(self, topics: tuple[str, ...], after: int) -> list[EventMessage] | None:
        self.asked.append((topics, after))
        while not self.release.is_set():
            await asyncio.sleep(0.01)
        return self.events


@pytest.fixture
def client():
    with TestClient(create_app(SETTINGS)) as c:
        yield c


def _publish(client: TestClient, message: EventMessage) -> None:
    client.app.state.broadcaster.publish(message)  # type: ignore[attr-defined]


class TestHandshake:
    def test_needs_the_subprotocol(self, client):
        with pytest.raises(WebSocketDisconnect), _connect(client, protocols=[]) as ws:
            ws.receive_json()

    def test_rejects_a_foreign_origin(self, client):
        with (
            pytest.raises(WebSocketDisconnect),
            _connect(client, origin="http://evil.example") as ws,
        ):
            ws.receive_json()

    def test_rejects_a_missing_origin(self, client):
        with pytest.raises(WebSocketDisconnect), _connect(client, origin=None) as ws:
            ws.receive_json()

    def test_same_origin_gets_hello(self, client):
        with _connect(client) as ws:
            hello = ws.receive_json()
        assert hello["op"] == "hello"
        assert "serverTime" in hello
        assert hello["lastSeq"] is None  # ohne NATS

    def test_configured_origins_are_allowed(self):
        settings = SETTINGS.model_copy(
            update={"allowed_origins": "http://nas:8080, http://nas.fritz.box:8080"}
        )
        with TestClient(create_app(settings)) as c:
            with _connect(c, origin="http://nas.fritz.box:8080") as ws:
                assert ws.receive_json()["op"] == "hello"
            with pytest.raises(WebSocketDisconnect), _connect(c, origin=ORIGIN) as ws:
                ws.receive_json()  # mit Liste gilt nur die Liste


class TestSubscriptions:
    def test_events_reach_only_subscribers_of_their_topic(self, client):
        with _connect(client) as ws:
            ws.receive_json()  # hello
            ws.send_json({"op": "subscribe", "topics": ["ranking"]})
            ws.send_json({"op": "ping"})
            assert ws.receive_json() == {"op": "pong"}  # Abo ist eingetragen
            _publish(client, _event("runs", 1))
            _publish(client, _event("ranking", 2, "scoring.run.completed", run_id=1))
            message = ws.receive_json()
        assert (message["op"], message["topic"], message["seq"]) == ("event", "ranking", 2)

    def test_unsubscribe_stops_the_events(self, client):
        with _connect(client) as ws:
            ws.receive_json()
            ws.send_json({"op": "subscribe", "topics": ["runs", "profiles"]})
            ws.send_json({"op": "unsubscribe", "topics": ["runs"]})
            ws.send_json({"op": "ping"})
            assert ws.receive_json() == {"op": "pong"}
            _publish(client, _event("runs", 1))
            _publish(
                client, _event("profiles", 2, "scoring.profile.saved", profile_id=1, version=2)
            )
            message = ws.receive_json()
        assert message["topic"] == "profiles"
        assert message["data"] == {"profileId": 1, "version": 2}  # camelCase

    @pytest.mark.parametrize(
        "raw",
        [
            "kein json",
            json.dumps([1, 2]),
            json.dumps({"op": "fliegen"}),
            json.dumps({"op": "subscribe", "topics": "runs"}),
            json.dumps({"op": "subscribe", "topics": ["geheim"]}),
            json.dumps({"op": "subscribe", "topics": [f"instrument:A{i}" for i in range(21)]}),
            json.dumps({"op": "subscribe", "topics": ["runs"], "resumeFrom": "gestern"}),
        ],
    )
    def test_bad_input_gets_an_error_and_the_connection_stays(self, client, raw):
        with _connect(client) as ws:
            ws.receive_json()
            ws.send_text(raw)
            error = ws.receive_json()
            ws.send_json({"op": "ping"})
            pong = ws.receive_json()
        assert error["op"] == "error"
        assert error["code"] == "bad_request"
        assert pong == {"op": "pong"}

    def test_binary_frames_get_an_error(self, client):
        with _connect(client) as ws:
            ws.receive_json()
            ws.send_bytes(b"\x00\x01")
            assert ws.receive_json()["op"] == "error"

    def test_oversized_message_closes_with_1009(self, client):
        with _connect(client) as ws:
            ws.receive_json()
            ws.send_text(json.dumps({"op": "ping", "pad": "x" * 5000}))
            with pytest.raises(WebSocketDisconnect) as closed:
                ws.receive_json()
        assert closed.value.code == 1009

    def test_instrument_topics_follow_the_pattern(self, client):
        with _connect(client) as ws:
            ws.receive_json()
            ws.send_json({"op": "subscribe", "topics": ["instrument:SAP.DE"]})
            ws.send_json({"op": "ping"})
            assert ws.receive_json() == {"op": "pong"}


class TestResume:
    def test_replayed_events_come_first_without_duplicates(self, client):
        replayer = FakeReplayer([_event("runs", 5), _event("runs", 6)])
        replayer.release.clear()  # Nachspielen haengt, bis ein Live-Event da ist
        client.app.state.replayer = replayer  # type: ignore[attr-defined]
        with _connect(client) as ws:
            assert ws.receive_json()["lastSeq"] == 10
            ws.send_json({"op": "subscribe", "topics": ["runs"], "resumeFrom": 4})
            while not replayer.asked:
                threading.Event().wait(0.01)
            _publish(client, _event("runs", 6))  # schon im Nachspielen enthalten
            _publish(client, _event("runs", 7))
            replayer.release.set()
            seqs = [ws.receive_json()["seq"] for _ in range(3)]
        assert seqs == [5, 6, 7]
        assert replayer.asked == [(("runs",), 4)]

    def test_too_large_a_gap_means_resync(self, client):
        client.app.state.replayer = FakeReplayer(None)  # type: ignore[attr-defined]
        with _connect(client) as ws:
            ws.receive_json()
            ws.send_json({"op": "subscribe", "topics": ["runs", "ranking"], "resumeFrom": 1})
            messages = [ws.receive_json(), ws.receive_json()]
        assert sorted((m["op"], m["topic"]) for m in messages) == [
            ("resync", "ranking"),
            ("resync", "runs"),
        ]

    def test_without_nats_resume_means_resync(self, client):
        with _connect(client) as ws:
            ws.receive_json()
            ws.send_json({"op": "subscribe", "topics": ["runs"], "resumeFrom": 3})
            assert ws.receive_json() == {"op": "resync", "topic": "runs"}


class TestPayload:
    def test_scoring_completed_comes_without_the_ranking(self):
        data = {
            "run_id": 1,
            "scoring_run_id": 20,
            "ranking": [{"rank_overall": 1}, {"rank_overall": 2}],
            "universe": {"source": "iShares", "as_of": "2026-10-16"},
        }
        payload = event_payload("scoring.run.completed", data)
        assert "ranking" not in payload
        assert payload["rankingSize"] == 2
        assert payload["scoringRunId"] == 20
        assert payload["universe"] == {"source": "iShares", "asOf": "2026-10-16"}


class _BlockingSender:
    """Ein Client, der nie fertig wird: Seine Warteschlange laeuft voll."""

    def __init__(self) -> None:
        self.closed: int | None = None
        self.sent: list[str] = []
        self.block = asyncio.Event()

    async def send_text(self, data: str) -> None:
        await self.block.wait()
        self.sent.append(data)

    async def close(self, code: int = 1000) -> None:
        self.closed = code


class _Sender(_BlockingSender):
    async def send_text(self, data: str) -> None:
        self.sent.append(data)


class TestHub:
    def test_full_queue_closes_with_1013_and_others_keep_receiving(self):
        async def scenario() -> tuple[_BlockingSender, _Sender]:
            hub = WebSocketHub(queue_size=2)
            slow, fast = _BlockingSender(), _Sender()
            slow_client, fast_client = hub.connect(slow), hub.connect(fast)
            hub.subscribe(slow_client, ("runs",))
            hub.subscribe(fast_client, ("runs",))
            for seq in range(1, 6):
                hub.publish(_event("runs", seq))
                await asyncio.sleep(0)
            await asyncio.sleep(0.05)
            await hub.disconnect(slow_client)
            await hub.disconnect(fast_client)
            return slow, fast

        slow, fast = asyncio.run(scenario())
        assert slow.closed == 1013
        assert [json.loads(t)["seq"] for t in fast.sent] == [1, 2, 3, 4, 5]

    def test_broadcaster_from_another_thread(self):
        async def scenario() -> _Sender:
            hub = WebSocketHub()
            sender = _Sender()
            client = hub.connect(sender)
            hub.subscribe(client, ("ranking",))
            broadcaster = HubBroadcaster(hub, asyncio.get_running_loop())
            thread = threading.Thread(
                target=broadcaster.publish, args=(_event("ranking", 9, run_id=1),)
            )
            thread.start()
            thread.join()
            for _ in range(100):
                if sender.sent:
                    break
                await asyncio.sleep(0.01)
            await hub.disconnect(client)
            return sender

        sender = asyncio.run(scenario())
        assert [json.loads(t)["seq"] for t in sender.sent] == [9]
