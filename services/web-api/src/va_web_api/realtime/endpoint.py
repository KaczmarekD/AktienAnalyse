"""Endpunkt ``/ws`` (P4.5) 🔒: Handshake pruefen, dann Protokoll v1.

Fuer WebSockets gibt es keinen Preflight. Eine fremde Webseite im Browser eines Nutzers koennte
sich also verbinden, wenn der Server nicht selbst prueft (Cross-Site WebSocket Hijacking,
ADR-0007 Regel 2). Abgelehnt wird deshalb schon vor dem ``accept`` (HTTP 403):

- ohne das Subprotokoll ``va.v1``,
- ohne ``Origin`` oder mit fremdem ``Origin``. Ohne ``WEB_API_ALLOWED_ORIGINS`` gilt nur dieselbe
  Herkunft: Host und Port von ``Origin`` gleich dem ``Host``-Header, den nginx mit Port
  weiterreicht (``$http_host``).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from .protocol import (
    MAX_MESSAGE_BYTES,
    PROTOCOL,
    Error,
    Hello,
    Ping,
    Pong,
    ProtocolError,
    Resync,
    Subscribe,
    Unsubscribe,
    parse_client_message,
)
from .replay import Replayer

if TYPE_CHECKING:
    from ..settings import WebApiSettings
    from .hub import Client, WebSocketHub

log = logging.getLogger(__name__)

router = APIRouter()

CLOSE_POLICY = 1008
CLOSE_TOO_BIG = 1009


def origin_allowed(origin: str | None, host: str | None, allowed: frozenset[str]) -> bool:
    if not origin:
        return False
    origin = origin.strip().rstrip("/").lower()
    if allowed:
        return origin in allowed
    parts = urlsplit(origin)
    return parts.scheme in ("http", "https") and bool(host) and parts.netloc == host.lower()


@router.websocket("/ws")
async def realtime(ws: WebSocket) -> None:
    settings: WebApiSettings = ws.app.state.settings
    offered = ws.scope.get("subprotocols") or []
    if PROTOCOL not in offered or not origin_allowed(
        ws.headers.get("origin"), ws.headers.get("host"), settings.origins
    ):
        log.info("WebSocket abgelehnt (Origin %s)", ws.headers.get("origin"))
        await ws.close(code=CLOSE_POLICY)  # vor accept: Uvicorn antwortet mit 403
        return
    await ws.accept(subprotocol=PROTOCOL)

    hub: WebSocketHub = ws.app.state.hub
    replayer: Replayer = ws.app.state.replayer or Replayer()
    client = hub.connect(ws)
    try:
        hub.send(client, Hello(server_time=datetime.now(UTC), last_seq=await replayer.last_seq()))
        while True:
            incoming = await ws.receive()
            if incoming["type"] == "websocket.disconnect":
                return
            text = incoming.get("text")
            if text is None:
                hub.send(client, Error(code="bad_request", message="Nur Textnachrichten (JSON)"))
                continue
            if len(text.encode()) > MAX_MESSAGE_BYTES:
                await ws.close(code=CLOSE_TOO_BIG)
                return
            try:
                request = parse_client_message(text)
            except ProtocolError as error:
                hub.send(client, Error(code=error.code, message=error.message))
                continue
            await _handle(hub, client, request, replayer)
    except WebSocketDisconnect:
        return
    finally:
        await hub.disconnect(client)


async def _handle(
    hub: WebSocketHub,
    client: Client,
    request: Subscribe | Unsubscribe | Ping,
    replayer: Replayer,
) -> None:
    match request:
        case Ping():
            hub.send(client, Pong())
        case Unsubscribe(topics=topics):
            hub.unsubscribe(client, topics)
        case Subscribe(topics=topics, resume_from=None):
            hub.subscribe(client, topics)
        case Subscribe(topics=topics, resume_from=after):
            # Zuerst abonnieren und Live-Events zurueckhalten, dann nachspielen
            hub.begin_replay(client)
            hub.subscribe(client, topics)
            events = await replayer.replay(tuple(topics), after or 0)
            hub.end_replay(client, events or [])
            if events is None:
                for topic in dict.fromkeys(topics):
                    hub.send(client, Resync(topic=topic))
