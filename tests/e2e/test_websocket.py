"""WebSocket ueber nginx (P4.5): Handshake wie im Browser, mit Origin und Subprotokoll.

Der Stack laeuft wie auf der NAS ohne NATS: ``hello`` hat keine ``lastSeq``.
"""

from __future__ import annotations

import json

import pytest
from websockets.exceptions import InvalidStatus
from websockets.sync.client import connect
from websockets.typing import Origin, Subprotocol

PROTOCOL = Subprotocol("va.v1")


def _ws_url(base_url: str) -> str:
    return base_url.replace("http://", "ws://", 1).replace("https://", "wss://", 1) + "/ws"


def test_own_origin_gets_hello(base_url):
    with connect(
        _ws_url(base_url), origin=Origin(base_url), subprotocols=[PROTOCOL], open_timeout=10
    ) as ws:
        assert ws.subprotocol == "va.v1"
        hello = json.loads(ws.recv(timeout=10))
        ws.send(json.dumps({"op": "ping"}))
        pong = json.loads(ws.recv(timeout=10))
    assert hello["op"] == "hello"
    assert pong == {"op": "pong"}


def test_foreign_origin_is_rejected(base_url):
    with pytest.raises(InvalidStatus) as rejected:
        connect(
            _ws_url(base_url),
            origin=Origin("http://evil.example"),
            subprotocols=[PROTOCOL],
            open_timeout=10,
        )
    assert rejected.value.response.status_code == 403
