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

import asyncio
import contextlib
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..identity.domain import token_hash
from ..identity.service import LAN_USER, IdentityService, User
from ..security import origin_allowed
from .protocol import (
    CLOSE_SESSION_ENDED,
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
    topic_owner,
)
from .replay import Replayer

if TYPE_CHECKING:
    from ..settings import WebApiSettings
    from .hub import Client, WebSocketHub

log = logging.getLogger(__name__)

router = APIRouter()

CLOSE_POLICY = 1008
CLOSE_TOO_BIG = 1009
SESSION_CHECK_SECONDS = 60.0  # D1.3: so oft prueft jede Verbindung ihre Sitzung


async def _session_user(ws: WebSocket, settings: WebApiSettings) -> tuple[User, str | None] | None:
    """Wer sich verbindet, mit dem Hash der Sitzung; ``None``: abzulehnen.

    Im Uebergang ohne Sitzungspflicht ``LAN_USER`` ohne Sitzung (wie unter ADR-0007).
    """
    if not settings.auth_required:
        return LAN_USER, None
    identity = getattr(ws.app.state, "identity", None)
    token = ws.cookies.get(settings.cookie_name)
    if identity is None or not token:
        return None
    # Die Pruefung liest die Datenbank: nicht in der Event-Loop
    user = await asyncio.to_thread(identity.authenticate, token)
    return None if user is None else (user, token_hash(token))


async def _watch_session(
    hub: WebSocketHub, client: Client, identity: IdentityService, token: str
) -> None:
    """D1.3: trennt, sobald die Sitzung endet (abgelaufen, widerrufen, Konto deaktiviert).

    Ohne ``touch``: Ein offener Tab haelt die Sitzung nicht am Leben.
    """
    while True:
        await asyncio.sleep(SESSION_CHECK_SECONDS)
        try:
            user = await asyncio.to_thread(identity.authenticate, token, touch=False)
        except Exception:
            log.warning("Sitzung des WebSockets nicht pruefbar", exc_info=True)
            continue  # Datenbank weg: die Verbindung bleibt, der naechste Takt prueft erneut
        if user is None:
            hub.close(client, CLOSE_SESSION_ENDED)
            return


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
    who = await _session_user(ws, settings)
    if who is None:
        log.info("WebSocket abgelehnt (ohne Sitzung)")
        await ws.close(code=CLOSE_POLICY)
        return
    user, session = who
    await ws.accept(subprotocol=PROTOCOL)

    hub: WebSocketHub = ws.app.state.hub
    replayer: Replayer = ws.app.state.replayer or Replayer()
    client = hub.connect(ws, user_id=user.id, session=session)
    watcher = (
        None
        if session is None
        else asyncio.create_task(
            _watch_session(
                hub, client, ws.app.state.identity, ws.cookies.get(settings.cookie_name) or ""
            )
        )
    )
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
        if watcher is not None:
            watcher.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await watcher
        await hub.disconnect(client)


def _forbidden(client: Client, topics: list[str]) -> str | None:
    """Das erste Topic, das einem anderen Nutzer gehoert (``user:<id>``), sonst ``None``."""
    for topic in topics:
        owner = topic_owner(topic)
        if owner is not None and owner != client.user_id:
            return topic
    return None


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
        case Subscribe(topics=topics) if forbidden := _forbidden(client, topics):
            # D1.3: kein Topic dieser Nachricht abonnieren, wenn eines fremd ist
            hub.send(client, Error(code="forbidden", message=f"Kein Zugriff auf {forbidden}"))
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
