"""Eventmanager des web-api (P4.4, docs/architecture/web-api-realtime.md, ADR-0006).

Jedes Event in zwei Schritten:

1. Inbox-Eintrag und alle Projektionen seines Typs in einer Transaktion (Schema ``web``). Wirft
   eine Projektion, ist nichts gespeichert, und die Exception geht an den Bus: JetStream stellt
   erneut zu. Ein schon verarbeitetes Event aendert nichts mehr.
2. Erst nach dem Commit gehen die Meldungen an den ``Broadcaster``, je Topic eine. Wer daraufhin
   per REST nachlaedt, sieht den neuen Stand. Bis zum WebSocket-Hub (P4.5) protokolliert der
   ``LoggingBroadcaster`` nur.

``open_event_consumer`` haengt den Eventmanager an den provisionierten NATS-Consumer
``web-api`` (``va.>``). Die Handler des ``NatsBus`` laufen in Threads, der Eventmanager ist
deshalb synchron.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

from pydantic import BaseModel

from va_contracts.events.v1 import (
    EVENTS,
    PROFILE_ACTIVATED,
    PROFILE_SAVED,
    REPORT_SENT,
    RUN_FAILED,
    RUN_REQUESTED,
    SCORING_RUN_COMPLETED,
    SNAPSHOT_COMPLETED,
)
from va_platform.db import session_scope
from va_platform.messaging import Inbox
from va_platform.nats import MAX_DELIVER, NatsBus, current_sequence

from ..adapters.postgres.models import WebInbox
from ..projections import register

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy import Engine
    from sqlalchemy.orm import Session

    from va_contracts import Envelope
    from va_contracts.events.v1 import EventSpec
    from va_platform.bus import DeadLetter

log = logging.getLogger(__name__)

CONSUMER = "web-api"  # der provisionierte Consumer mit va.>

type Projection = Callable[[Session, Envelope[Any]], None]

# Topics des WebSocket-Protokolls (web-api-realtime.md) je Event-Typ
TOPICS: dict[str, tuple[str, ...]] = {
    RUN_REQUESTED.type: ("runs",),
    SNAPSHOT_COMPLETED.type: ("runs",),
    SCORING_RUN_COMPLETED.type: ("runs", "ranking"),
    REPORT_SENT.type: ("runs",),
    RUN_FAILED.type: ("runs",),
    PROFILE_SAVED.type: ("profiles",),
    PROFILE_ACTIVATED.type: ("profiles",),
}


@dataclass(frozen=True)
class EventMessage:
    """Eine Aenderung fuer die Clients. Der WebSocket-Hub (P4.5) bildet sie aufs Protokoll ab."""

    topic: str
    type: str
    seq: int | None  # Stream-Sequenz aus JetStream, Grundlage fuer resumeFrom
    data: dict[str, Any]


class Broadcaster(Protocol):
    def publish(self, message: EventMessage) -> None: ...


class LoggingBroadcaster:
    """Bis zum WebSocket-Hub (P4.5): meldet nur ins Log."""

    def publish(self, message: EventMessage) -> None:
        log.debug("Topic %s: %s (seq %s)", message.topic, message.type, message.seq)


def topics_for(envelope: Envelope[Any]) -> tuple[str, ...]:
    if envelope.type == SCORING_RUN_COMPLETED.type and envelope.data.run_id is None:
        return ("ranking",)  # ein Rescore hat keinen Run
    return TOPICS.get(envelope.type, ())


class EventManager:
    """Drehscheibe im web-api: Event -> Projektionen (eine Transaktion) -> Broadcaster."""

    def __init__(
        self, engine: Engine, broadcaster: Broadcaster, *, consumer: str = CONSUMER
    ) -> None:
        self._engine = engine
        self._broadcaster = broadcaster
        self._consumer = consumer
        self._inbox = Inbox(WebInbox)
        self._projections: defaultdict[str, list[Projection]] = defaultdict(list)

    def projection(self, spec: EventSpec[Any]) -> Callable[[Projection], Projection]:
        """Registriert eine Projektion fuer einen Event-Typ (als Dekorator nutzbar)."""

        def register(fn: Projection) -> Projection:
            self._projections[spec.type].append(fn)
            return fn

        return register

    def dispatch(self, envelope: Envelope[Any], seq: int | None = None) -> bool:
        """``True``, wenn das Event neu war und projiziert wurde; ``False`` bei einer Wiederholung."""
        with session_scope(self._engine) as session:
            if not self._inbox.claim(session, envelope.id, self._consumer):
                log.info("%s (%s) schon verarbeitet, uebersprungen", envelope.type, envelope.id)
                return False
            for project in self._projections.get(envelope.type, ()):
                project(session, envelope)
        # Erst nach dem Commit: Wer daraufhin per REST nachlaedt, sieht den neuen Stand
        data = _plain(envelope.data)
        for topic in topics_for(envelope):
            try:
                self._broadcaster.publish(EventMessage(topic, envelope.type, seq, data))
            except Exception:
                log.warning("Meldung an Topic %s nicht verteilt", topic, exc_info=True)
        return True

    def record_dead_letter(self, dead: DeadLetter) -> None:
        """Nach ``max_deliver`` Versuchen aufgegeben: in der Inbox vermerken (events.md)."""
        with session_scope(self._engine) as session:
            self._inbox.record_dead_letter(
                session,
                dead.envelope.id,
                self._consumer,
                f"{type(dead.error).__name__}: {dead.error}",
            )


def _plain(data: Any) -> dict[str, Any]:
    if isinstance(data, BaseModel):
        return data.model_dump(mode="json")
    return dict(data)


def open_event_consumer(nats_url: str, engine: Engine, broadcaster: Broadcaster) -> NatsBus:
    """Startet den Consumer ``web-api``: alle dauerhaften Events gehen an den Eventmanager.

    ``engine`` schreibt mit der Rolle ``va_web``. Der Aufrufer schliesst den Bus am Ende.
    """
    manager = EventManager(engine, broadcaster)
    register(manager)

    def dead_letter(dead: DeadLetter) -> None:
        try:
            manager.record_dead_letter(dead)
        except Exception:
            log.exception("Dead Letter %s nicht vermerkt", dead.envelope.id)

    def handle(env: Envelope[Any]) -> None:
        manager.dispatch(env, current_sequence())

    bus = NatsBus(nats_url, max_deliver=MAX_DELIVER, on_dead_letter=dead_letter)
    bus.start()
    try:
        for spec in EVENTS.values():
            if not spec.volatile:
                bus.subscribe(spec, CONSUMER, handle)
    except BaseException:
        bus.close()
        raise
    return bus
