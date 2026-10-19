"""Event-Bus: Schnittstelle ``EventBus`` und die Umsetzung im Prozess (P1.8).

Ab Phase 4 kommt eine zweite Umsetzung ueber NATS JetStream dazu. Handler und Contracts
bleiben dabei gleich, die Vertragstests (``packages/va-platform/tests/test_bus.py``) laufen
gegen beide. Deshalb verhaelt sich ``InProcessBus`` wie der spaetere Transport:

- Jedes Event geht als JSON ueber die "Leitung". Ein Empfaenger bekommt eine eigene Kopie,
  geparst mit ``parse_envelope``, nie das Objekt des Senders.
- Jeder Consumer bekommt jedes Event seines Typs (Fan-out), in der Reihenfolge der
  Veroeffentlichung.
- Wirft ein Handler, wird dasselbe Event (gleiche ID) erneut zugestellt, hoechstens
  ``max_deliver``-mal. Danach ist es ein ``DeadLetter``. Die anderen Consumer merken davon
  nichts.

Zustellung im Prozess: ``publish`` stellt alles zu, auch die Events, die Handler dabei
veroeffentlichen, und kehrt erst danach zurueck. Ein Event, das ein Handler veroeffentlicht,
kommt nach dem Event an die Reihe, das gerade zugestellt wird (Warteschlange, keine
Rekursion).
"""

from __future__ import annotations

import logging
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from va_contracts import Contract, Envelope, new_envelope, parse_envelope
from va_contracts.events.v1 import EventSpec

log = logging.getLogger(__name__)

type Handler[T: Contract] = Callable[[Envelope[T]], None]


@dataclass(frozen=True)
class DeadLetter:
    """Ein Event, das ein Consumer auch nach ``max_deliver`` Versuchen nicht verarbeitet hat."""

    consumer: str
    envelope: Envelope[Any]
    attempts: int
    error: BaseException


class EventBus(Protocol):
    def subscribe[T: Contract](
        self, spec: EventSpec[T], consumer: str, handler: Handler[T]
    ) -> None:
        """``consumer`` ist der dauerhafte Name des Empfaengers (spaeter der NATS-Consumer)."""
        ...

    def publish(self, envelope: Envelope[Any]) -> None: ...


def follow_up[T: Contract](
    cause: Envelope[Any], spec: EventSpec[T], data: T, *, source: str
) -> Envelope[T]:
    """Ein Event als Folge von ``cause``: gleiche Korrelation (Run), ``cause`` als Ursache."""
    return new_envelope(
        spec, data, source=source, correlationid=cause.correlationid, causationid=cause.id
    )


@dataclass(frozen=True)
class _Subscription:
    consumer: str
    handler: Handler[Any]


class InProcessBus:
    """``EventBus`` im selben Prozess, fuer den Batch bis Phase 4."""

    def __init__(
        self,
        *,
        max_deliver: int = 3,
        on_dead_letter: Callable[[DeadLetter], None] | None = None,
    ) -> None:
        if max_deliver < 1:
            msg = f"max_deliver muss mindestens 1 sein, nicht {max_deliver}"
            raise ValueError(msg)
        self._max_deliver = max_deliver
        self._on_dead_letter = on_dead_letter
        self._subscriptions: dict[str, list[_Subscription]] = {}
        self._queue: deque[tuple[str, str]] = deque()
        self._dispatching = False

    def subscribe[T: Contract](
        self, spec: EventSpec[T], consumer: str, handler: Handler[T]
    ) -> None:
        subscriptions = self._subscriptions.setdefault(spec.type, [])
        if any(s.consumer == consumer for s in subscriptions):
            msg = f"{consumer} hat {spec.type} bereits abonniert"
            raise ValueError(msg)
        subscriptions.append(_Subscription(consumer, handler))

    def publish(self, envelope: Envelope[Any]) -> None:
        self._queue.append((envelope.type, envelope.model_dump_json()))
        if self._dispatching:
            return  # der aeussere publish-Aufruf stellt es zu
        self._dispatching = True
        try:
            while self._queue:
                event_type, raw = self._queue.popleft()
                for subscription in self._subscriptions.get(event_type, []):
                    self._deliver(subscription, raw)
        finally:
            self._dispatching = False

    def _deliver(self, subscription: _Subscription, raw: str) -> None:
        # Nur die Huelle: Sie bleibt lesbar, auch wenn die Payload es nicht ist
        head = Envelope[dict[str, Any]].model_validate_json(raw)
        for attempt in range(1, self._max_deliver + 1):
            try:
                subscription.handler(parse_envelope(raw))
            except Exception as error:
                log.warning(
                    "%s: %s (%s) fehlgeschlagen, Versuch %d/%d",
                    subscription.consumer,
                    head.type,
                    head.id,
                    attempt,
                    self._max_deliver,
                    exc_info=True,
                )
                if attempt == self._max_deliver:
                    self._dead_letter(
                        DeadLetter(subscription.consumer, _readable(raw, head), attempt, error)
                    )
            else:
                return

    def _dead_letter(self, dead: DeadLetter) -> None:
        log.error(
            "%s: %s (%s) nach %d Versuchen aufgegeben",
            dead.consumer,
            dead.envelope.type,
            dead.envelope.id,
            dead.attempts,
        )
        if self._on_dead_letter is not None:
            self._on_dead_letter(dead)


def _readable(raw: str, head: Envelope[Any]) -> Envelope[Any]:
    """Das Event mit typisierter Payload, wenn sie lesbar ist - sonst nur die Huelle."""
    try:
        return parse_envelope(raw)
    except Exception:
        return head
