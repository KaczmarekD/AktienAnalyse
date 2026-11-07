"""``ReliableBus`` (P4.3b): Die Handler eines Service verarbeiten jedes Event einmal.

Ueber NATS kann ein Event erneut kommen, etwa nach einem verlorenen Ack, oder als Rest eines
abgebrochenen Laufs liegen bleiben. Der ``ReliableBus`` umhuellt den Bus fuer die Handler eines
Service, mit Inbox und Outbox aus dessen Schema:

1. Ist das Event aelter als ``max_age``, wird es uebersprungen.
2. Hat der Consumer es schon verarbeitet (Inbox), wird es uebersprungen.
3. Sonst laeuft der Handler. Was er veroeffentlicht, sammelt der Wrapper.
4. Inbox-Eintrag und gesammelte Events kommen in einer Transaktion in die Outbox.
5. Dann gibt ``drain_outbox`` die offenen Eintraege an den Bus weiter.

Wirft der Handler, gibt es weder Inbox-Eintrag noch Folge-Events; ueber Wiederholung oder Dead
Letter entscheidet wie bisher der Bus. Fluechtige Events und alles, was ausserhalb einer
Zustellung veroeffentlicht wird, gehen direkt an den Bus.

Die Fachdaten schreibt der Handler selbst, kurz vor dem Abschluss (Entscheidung "pragmatisch",
docs/architecture/implementierungsplan.md, P4.3b). Stuerzt der Prozess genau dazwischen ab,
laeuft der Handler bei erneuter Zustellung noch einmal; dagegen stehen fachliche Sperren in den
Services (Abruf des Tages, keine zweite Report-Mail).
"""

from __future__ import annotations

import logging
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from va_contracts import parse_envelope
from va_contracts.events.v1 import BY_DATASCHEMA

from ..db import session_scope
from .inbox import Inbox
from .outbox import Outbox, drain_outbox

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import timedelta

    from sqlalchemy import Engine

    from va_contracts import Contract, Envelope
    from va_contracts.events.v1 import EventSpec

    from ..bus import EventBus, Handler
    from .models import InboxMixin, OutboxMixin
    from .outbox import OutboxMessage

log = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(UTC)


class ReliableBus:
    """``EventBus`` fuer die Handler eines Service, mit dessen Inbox und Outbox."""

    def __init__(
        self,
        bus: EventBus,
        engine: Engine,
        *,
        inbox: type[InboxMixin],
        outbox: type[OutboxMixin],
        max_age: timedelta | None = None,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._bus = bus
        self._engine = engine
        self._inbox = Inbox(inbox)
        self._outbox = Outbox(outbox)
        self._max_age = max_age
        self._clock = clock
        # Je Thread: Ueber NATS laufen die Handler mehrerer Consumer gleichzeitig
        self._collected: ContextVar[list[Envelope[Any]] | None] = ContextVar(
            f"va-reliable-{outbox.__name__}", default=None
        )

    def subscribe[T: Contract](
        self, spec: EventSpec[T], consumer: str, handler: Handler[T]
    ) -> None:
        def deliver(env: Envelope[T]) -> None:
            self._deliver(consumer, handler, env)

        self._bus.subscribe(spec, consumer, deliver)

    def publish(self, envelope: Envelope[Any]) -> None:
        collected = self._collected.get()
        if collected is None or BY_DATASCHEMA[envelope.dataschema].volatile:
            self._bus.publish(envelope)
        else:
            collected.append(envelope)

    def flush(self) -> int:
        """Offene Eintraege der Outbox an den Bus geben; Anzahl der weitergegebenen."""
        return drain_outbox(self._engine, self._outbox, self._forward)

    def _forward(self, message: OutboxMessage) -> None:
        self._bus.publish(parse_envelope(message.payload))

    def _deliver[T: Contract](self, consumer: str, handler: Handler[T], env: Envelope[T]) -> None:
        # D1.6: Ein Event mit eigenem Hoechstalter (etwa ein Link, der 24 h gilt) wartet so lange,
        # die Run-Kette nur RUN_TIMEOUT_MINUTES
        max_age = BY_DATASCHEMA[env.dataschema].max_age or self._max_age
        if max_age is not None and self._clock() - env.time > max_age:
            log.warning(
                "%s: %s (%s) vom %s ist veraltet, uebersprungen",
                consumer,
                env.type,
                env.id,
                env.time.isoformat(timespec="seconds"),
            )
            return
        with session_scope(self._engine) as s:
            seen = self._inbox.seen(s, env.id, consumer)
        if seen:
            log.info("%s: %s (%s) schon verarbeitet, uebersprungen", consumer, env.type, env.id)
            self.flush()  # was beim letzten Mal liegen blieb
            return

        collected: list[Envelope[Any]] = []
        token = self._collected.set(collected)
        try:
            handler(env)
        finally:
            self._collected.reset(token)

        with session_scope(self._engine) as s:
            if not self._inbox.claim(s, env.id, consumer):
                log.warning(
                    "%s: %s (%s) wurde parallel verarbeitet, Folge-Events verworfen",
                    consumer,
                    env.type,
                    env.id,
                )
                return
            for event in collected:
                self._outbox.add(s, event)
        self.flush()
