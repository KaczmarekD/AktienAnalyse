"""Verpasste Events nachspielen (P4.5, ``resumeFrom``): aus dem Stream ``VA_EVENTS``.

Der Client meldet die letzte Sequenz, die er gesehen hat. Der ``NatsReplayer`` liest die
Nachrichten danach direkt aus dem Stream, ordnet sie den Topics zu (wie der Eventmanager) und
gibt die der abonnierten Topics zurueck. ``None`` heisst ``resync``: Die Luecke ist groesser als
``limit``, aelter als der Stream, oder NATS ist nicht erreichbar. Der Client laedt dann per REST
neu.

Eine eigene Verbindung in der Event-Loop von Uvicorn, unabhaengig vom ``NatsBus`` des
Event-Consumers. Sie entsteht beim ersten Bedarf.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

import nats
from nats.js.errors import NotFoundError

from va_contracts import parse_envelope
from va_platform.nats import STREAM_NAME, inbox_prefix

from ..events import EventMessage, plain, topics_for

if TYPE_CHECKING:
    from nats.aio.client import Client
    from nats.js.manager import JetStreamManager

log = logging.getLogger(__name__)

REPLAY_LIMIT = 500


class Replayer:
    """Ohne NATS (NAS, E2E): Es gibt nichts nachzuspielen."""

    async def last_seq(self) -> int | None:
        return None

    async def replay(
        self,
        topics: tuple[str, ...],  # noqa: ARG002 - Signatur wie NatsReplayer
        after: int,  # noqa: ARG002
    ) -> list[EventMessage] | None:
        return None


class NatsReplayer(Replayer):
    def __init__(self, url: str, *, limit: int = REPLAY_LIMIT, timeout: float = 2.0) -> None:
        self._url = url
        self._limit = limit
        self._timeout = timeout
        self._nc: Client | None = None
        self._lock = asyncio.Lock()

    async def last_seq(self) -> int | None:
        try:
            jsm = await self._jsm()
            return (await jsm.stream_info(STREAM_NAME)).state.last_seq
        except Exception:
            log.debug("Letzte Sequenz nicht lesbar", exc_info=True)
            return None

    async def replay(self, topics: tuple[str, ...], after: int) -> list[EventMessage] | None:
        try:
            jsm = await self._jsm()
            state = (await jsm.stream_info(STREAM_NAME)).state
        except Exception:
            log.info("Nachspielen nicht moeglich, NATS nicht erreichbar", exc_info=True)
            return None
        if after >= state.last_seq:
            return []
        if after + 1 < state.first_seq or state.last_seq - after > self._limit:
            return None  # aelter als der Stream oder zu viel: neu laden
        wanted = set(topics)
        events: list[EventMessage] = []
        for seq in range(after + 1, state.last_seq + 1):
            message = await self._message(jsm, seq)
            if message is None:
                continue
            for topic in topics_for(message):
                if topic in wanted:
                    events.append(EventMessage(topic, message.type, seq, plain(message.data)))
        return events

    async def close(self) -> None:
        if self._nc is not None and not self._nc.is_closed:
            await self._nc.close()

    async def _message(self, jsm: JetStreamManager, seq: int) -> Any:
        try:
            raw = await jsm.get_msg(STREAM_NAME, seq)
        except NotFoundError:
            return None  # geloescht oder abgelaufen
        try:
            return parse_envelope(raw.data or b"")
        except Exception:
            log.debug("Nachricht %d nicht lesbar, uebersprungen", seq, exc_info=True)
            return None

    async def _jsm(self) -> JetStreamManager:
        async with self._lock:
            if self._nc is None or self._nc.is_closed:
                self._nc = await nats.connect(
                    self._url,
                    connect_timeout=self._timeout,
                    max_reconnect_attempts=1,
                    name="va-web-api-replay",
                    # D1.5: eigene Inbox des NATS-Nutzers web-api
                    inbox_prefix=inbox_prefix(self._url),
                )
            return self._nc.jsm()
