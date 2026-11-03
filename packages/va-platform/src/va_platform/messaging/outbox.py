"""Outbox des Senders und das Relay, das sie leert (P4.2, docs/architecture/events.md).

Fachdaten und Event landen in einer Transaktion: ``Outbox.add`` schreibt in die Session des
Aufrufers, also gibt es das Event genau dann, wenn auch die Fachdaten gespeichert sind. Das
Relay veroeffentlicht die offenen Eintraege danach und setzt ``published_at``. Geht dabei
etwas schief, bleibt der Eintrag offen und kommt beim naechsten Durchlauf dran. Doppelt zu
senden ist harmlos: Die Event-ID ist die ``Nats-Msg-Id``, JetStream verwirft Duplikate.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

from sqlalchemy import Text, cast, func, insert, select, update

from va_contracts.events.v1 import BY_DATASCHEMA

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy import Engine
    from sqlalchemy.orm import Session

    from va_contracts import Envelope

    from .models import OutboxMixin

log = logging.getLogger(__name__)


class VolatileEventError(ValueError):
    """Fluechtige Events (``live.va.…``) laufen am Stream vorbei, nie ueber die Outbox."""


@dataclass(frozen=True)
class OutboxMessage:
    """Ein offener Eintrag, so wie der Publisher ihn sendet."""

    id: UUID  # Event-ID, beim Senden die Nats-Msg-Id
    subject: str
    payload: bytes  # die Huelle als JSON


class Publisher(Protocol):
    async def publish(self, message: OutboxMessage) -> None:
        """Kehrt erst zurueck, wenn der Broker das Event bestaetigt hat, sonst wirft er."""
        ...


class Outbox:
    """Die Outbox eines Schemas, ``model`` ist dessen Tabelle (``OutboxMixin``)."""

    def __init__(self, model: type[OutboxMixin]) -> None:
        self.model = model

    def add(self, session: Session, envelope: Envelope[Any]) -> None:
        """Merkt das Event in der laufenden Transaktion vor. Ohne Commit gibt es kein Event."""
        spec = BY_DATASCHEMA[envelope.dataschema]
        if spec.volatile:
            msg = f"{spec.subject} ist fluechtig und geht nicht ueber die Outbox"
            raise VolatileEventError(msg)
        session.execute(
            insert(self.model).values(
                id=envelope.id, subject=spec.subject, payload=envelope.model_dump(mode="json")
            )
        )


class OutboxRelay:
    """Veroeffentlicht die offenen Eintraege einer Outbox, mindestens einmal und in Reihenfolge.

    Die Datenbank laeuft synchron, die Zugriffe deshalb ueber ``asyncio.to_thread``. Der
    Publisher ist asynchron (JetStream). Ein Relay je Outbox reicht; laufen doch zwei, senden
    sie hoechstens doppelt.
    """

    def __init__(
        self, engine: Engine, outbox: Outbox, publisher: Publisher, *, batch_size: int = 100
    ) -> None:
        if batch_size < 1:
            msg = f"batch_size muss mindestens 1 sein, nicht {batch_size}"
            raise ValueError(msg)
        self._engine = engine
        self._model = outbox.model
        self._publisher = publisher
        self._batch_size = batch_size

    async def publish_pending(self) -> int:
        """Sendet alles Offene nach ``created_at`` und Event-ID, gibt die Anzahl zurueck.

        Jeder Eintrag wird nach dem Ack markiert. Wirft der Publisher, bricht der Durchlauf ab:
        Dieser und alle spaeteren Eintraege bleiben offen. Innerhalb einer Transaktion bleibt
        die Reihenfolge erhalten. Ueber Transaktionen hinweg gilt sie nur ungefaehr:
        ``created_at`` ist der Beginn der Transaktion, nicht ihr Commit.
        """
        published = 0
        while True:
            batch = await asyncio.to_thread(self._pending)
            for message in batch:
                await self._publisher.publish(message)
                await asyncio.to_thread(self._mark_published, message.id)
                published += 1
            if len(batch) < self._batch_size:
                return published

    async def run(
        self, stop: asyncio.Event, *, interval: float = 1.0, max_interval: float = 30.0
    ) -> None:
        """``publish_pending`` alle ``interval`` Sekunden, bis ``stop`` gesetzt ist.

        Ein Fehler (Broker oder Datenbank weg) beendet die Schleife nicht. Die Pause verdoppelt
        sich dann bis ``max_interval``. Nur der erste Fehler einer Serie kommt mit Traceback
        ins Log, die Erholung wird gemeldet.
        """
        delay = interval
        failures = 0
        while not stop.is_set():
            try:
                await self.publish_pending()
            except Exception:
                failures += 1
                delay = min(delay * 2, max(max_interval, interval))
                log.warning(
                    "%s: Veroeffentlichen gescheitert (%d. Mal), neuer Versuch in %.1f s",
                    self._model.__name__,
                    failures,
                    delay,
                    exc_info=failures == 1,
                )
            else:
                if failures:
                    log.info(
                        "%s: wieder erreichbar nach %d Fehlern", self._model.__name__, failures
                    )
                failures, delay = 0, interval
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=delay)

    def _pending(self) -> list[OutboxMessage]:
        model = self._model
        query = (
            select(model.id, model.subject, cast(model.payload, Text))
            .where(model.published_at.is_(None))
            .order_by(model.created_at, model.id)  # UUIDv7: gleiche Transaktion, gleiche Folge
            .limit(self._batch_size)
        )
        with self._engine.connect() as conn:
            return [
                OutboxMessage(event_id, subject, payload.encode())
                for event_id, subject, payload in conn.execute(query)
            ]

    def _mark_published(self, event_id: UUID) -> None:
        model = self._model
        with self._engine.begin() as conn:
            conn.execute(
                update(model)
                .where(model.id == event_id, model.published_at.is_(None))
                .values(published_at=func.now())
            )
