"""WebSocket-Hub (P4.5): Verbindungen, Topic-Abos, je Client eine Warteschlange.

Laeuft in der Event-Loop von Uvicorn. Jeder Client hat eine begrenzte Warteschlange und einen
eigenen Schreib-Task. Ist die Warteschlange voll, wird der Client mit 1013 getrennt: Er verbindet
sich neu und synchronisiert sich per REST. Ein langsamer Client haelt also nie die anderen auf.

Waehrend ein Client verpasste Events nachgespielt bekommt (``resumeFrom``), haelt der Hub seine
Live-Events zurueck. Danach gehen sie raus, ohne die Sequenzen, die schon nachgespielt sind:
nichts doppelt, nichts vertauscht.

Der ``HubBroadcaster`` ist der ``Broadcaster`` des Eventmanagers (P4.4). Der laeuft in den
Threads des ``NatsBus`` und reicht die Meldungen per ``call_soon_threadsafe`` an die Loop.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

from .protocol import Event, ServerMessage, encode, event_payload

if TYPE_CHECKING:
    from ..events import EventMessage

log = logging.getLogger(__name__)

QUEUE_SIZE = 256
CLOSE_TOO_SLOW = 1013  # "Try Again Later": zu langsam, neu verbinden


class Sender(Protocol):
    """Was der Hub von einer Verbindung braucht (Starlettes ``WebSocket`` passt)."""

    async def send_text(self, data: str) -> None: ...

    async def close(self, code: int = 1000) -> None: ...


@dataclass(eq=False)
class Client:
    sender: Sender
    queue: asyncio.Queue[str]
    topics: set[str] = field(default_factory=set)
    held: list[EventMessage] | None = None  # gesetzt, solange nachgespielt wird
    closing: bool = False
    writer: asyncio.Task[None] | None = None
    closer: asyncio.Task[None] | None = None


class WebSocketHub:
    def __init__(self, *, queue_size: int = QUEUE_SIZE) -> None:
        self._queue_size = queue_size
        self._clients: set[Client] = set()

    def connect(self, sender: Sender) -> Client:
        client = Client(sender, asyncio.Queue(maxsize=self._queue_size))
        client.writer = asyncio.get_running_loop().create_task(self._write(client))
        self._clients.add(client)
        return client

    async def disconnect(self, client: Client) -> None:
        self._clients.discard(client)
        if client.writer is not None:
            client.writer.cancel()
        for task in (client.writer, client.closer):
            if task is not None:
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task

    def subscribe(self, client: Client, topics: tuple[str, ...] | list[str]) -> None:
        client.topics.update(topics)

    def unsubscribe(self, client: Client, topics: tuple[str, ...] | list[str]) -> None:
        client.topics.difference_update(topics)

    def send(self, client: Client, message: ServerMessage) -> None:
        """Antwort an genau diesen Client, ueber dieselbe Warteschlange wie die Events."""
        self._enqueue(client, encode(message))

    def publish(self, message: EventMessage) -> None:
        """Ein Event an alle Clients mit diesem Topic."""
        for client in list(self._clients):
            if message.topic not in client.topics or client.closing:
                continue
            if client.held is not None:
                client.held.append(message)
                if len(client.held) > self._queue_size:
                    self._close(client, CLOSE_TOO_SLOW)
                continue
            self._enqueue(client, _encode_event(message))

    def begin_replay(self, client: Client) -> None:
        client.held = []

    def end_replay(self, client: Client, replayed: list[EventMessage]) -> None:
        """Erst das Nachgespielte, dann zurueckgehaltene Live-Events ohne Doppelte."""
        held, client.held = client.held or [], None
        newest = max((m.seq for m in replayed if m.seq is not None), default=None)
        for message in replayed:
            self._enqueue(client, _encode_event(message))
        for message in held:
            if newest is not None and message.seq is not None and message.seq <= newest:
                continue
            self._enqueue(client, _encode_event(message))

    def _enqueue(self, client: Client, text: str) -> None:
        if client.closing:
            return
        try:
            client.queue.put_nowait(text)
        except asyncio.QueueFull:
            self._close(client, CLOSE_TOO_SLOW)

    def _close(self, client: Client, code: int) -> None:
        if client.closing:
            return
        client.closing = True
        log.info("WebSocket-Client zu langsam, getrennt (%d)", code)
        if client.writer is not None:
            client.writer.cancel()
        client.closer = asyncio.get_running_loop().create_task(_close_quietly(client, code))

    async def _write(self, client: Client) -> None:
        while True:
            text = await client.queue.get()
            try:
                await client.sender.send_text(text)
            except Exception:
                log.debug("WebSocket-Client nicht mehr erreichbar", exc_info=True)
                client.closing = True
                return


async def _close_quietly(client: Client, code: int) -> None:
    with contextlib.suppress(Exception):
        await client.sender.close(code)


def _encode_event(message: EventMessage) -> str:
    return encode(
        Event(
            topic=message.topic,
            type=message.type,
            seq=message.seq,
            data=event_payload(message.type, message.data),
        )
    )


class HubBroadcaster:
    """``Broadcaster`` fuer den Eventmanager: aus beliebigen Threads in die Loop des Hubs."""

    def __init__(self, hub: WebSocketHub, loop: asyncio.AbstractEventLoop) -> None:
        self._hub = hub
        self._loop = loop

    def publish(self, message: EventMessage) -> None:
        try:
            self._loop.call_soon_threadsafe(self._hub.publish, message)
        except RuntimeError:
            log.debug("Event-Loop beendet, Meldung %s verworfen", message.type)
