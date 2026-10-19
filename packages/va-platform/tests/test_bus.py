"""Vertragstests fuer die Bus-Schnittstelle ``EventBus`` (P1.8).

Die Tests kennen nur die Schnittstelle: ``subscribe``, ``publish`` und das Ende der
Zustellung. Die Fixture ``bus`` ist parametrisiert; mit Phase 4 kommt dort NATS dazu, die
Tests bleiben unveraendert. ``settle`` wartet, bis alles zugestellt ist (im Prozess sofort).
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any

import pytest

from va_contracts import Envelope, new_envelope
from va_contracts.events.v1 import (
    REPORT_SENT,
    RUN_REQUESTED,
    ReportSentV1,
    RunOptionsV1,
    ScreeningRunRequestedV1,
)
from va_platform.bus import DeadLetter, EventBus, InProcessBus

MAX_DELIVER = 3


@dataclass
class Harness:
    bus: EventBus
    settle: Callable[[], None]
    dead: list[DeadLetter] = field(default_factory=list)


@pytest.fixture(params=["in_process"])
def harness(request) -> Iterator[Harness]:
    dead: list[DeadLetter] = []
    if request.param == "in_process":
        bus = InProcessBus(max_deliver=MAX_DELIVER, on_dead_letter=dead.append)
        yield Harness(bus=bus, settle=lambda: None, dead=dead)


def _requested(run_id: int = 1) -> Envelope[ScreeningRunRequestedV1]:
    data = ScreeningRunRequestedV1(run_id=run_id, trigger="manual", options=RunOptionsV1())
    return new_envelope(RUN_REQUESTED, data, source="va/test", correlationid=str(run_id))


def _sent(run_id: int = 1) -> Envelope[ReportSentV1]:
    data = ReportSentV1(run_id=run_id, report_id=7, subject="[ok 1/1]", dry_run=False)
    return new_envelope(REPORT_SENT, data, source="va/test")


class TestDelivery:
    def test_subscriber_receives_the_event(self, harness):
        received: list[Envelope[Any]] = []
        harness.bus.subscribe(RUN_REQUESTED, "market-data", received.append)
        sent = _requested()
        harness.bus.publish(sent)
        harness.settle()
        assert len(received) == 1
        assert received[0] == sent
        assert isinstance(received[0].data, ScreeningRunRequestedV1)

    def test_only_the_subscribed_type_arrives(self, harness):
        received: list[Envelope[Any]] = []
        harness.bus.subscribe(REPORT_SENT, "web-api", received.append)
        harness.bus.publish(_requested())
        harness.settle()
        assert received == []

    def test_event_without_subscriber_is_fine(self, harness):
        harness.bus.publish(_requested())
        harness.settle()
        assert harness.dead == []

    def test_receiver_gets_a_copy_from_the_wire(self, harness):
        """Was ankommt, hat den Weg ueber JSON hinter sich - wie spaeter ueber NATS."""
        received: list[Envelope[Any]] = []
        harness.bus.subscribe(RUN_REQUESTED, "market-data", received.append)
        sent = _requested()
        harness.bus.publish(sent)
        harness.settle()
        assert received[0] is not sent
        assert received[0].model_dump_json() == sent.model_dump_json()

    def test_events_published_by_a_handler_are_delivered(self, harness):
        chain: list[str] = []

        def market_data(env: Envelope[Any]) -> None:
            chain.append(env.type)
            harness.bus.publish(_sent(env.data.run_id))

        harness.bus.subscribe(RUN_REQUESTED, "market-data", market_data)
        harness.bus.subscribe(REPORT_SENT, "web-api", lambda env: chain.append(env.type))
        harness.bus.publish(_requested())
        harness.settle()
        assert chain == [RUN_REQUESTED.type, REPORT_SENT.type]

    def test_order_of_events_is_kept_per_subscriber(self, harness):
        seen: list[int] = []
        harness.bus.subscribe(
            RUN_REQUESTED, "market-data", lambda env: seen.append(env.data.run_id)
        )
        for run_id in (1, 2, 3):
            harness.bus.publish(_requested(run_id))
        harness.settle()
        assert seen == [1, 2, 3]


class TestFanOut:
    def test_every_consumer_gets_its_own_copy(self, harness):
        a: list[Envelope[Any]] = []
        b: list[Envelope[Any]] = []
        harness.bus.subscribe(RUN_REQUESTED, "market-data", a.append)
        harness.bus.subscribe(RUN_REQUESTED, "web-api", b.append)
        harness.bus.publish(_requested())
        harness.settle()
        assert len(a) == len(b) == 1
        assert a[0].id == b[0].id

    def test_same_consumer_twice_is_rejected(self, harness):
        harness.bus.subscribe(RUN_REQUESTED, "market-data", lambda env: None)
        with pytest.raises(ValueError, match="market-data"):
            harness.bus.subscribe(RUN_REQUESTED, "market-data", lambda env: None)


class TestFailures:
    def test_failing_consumer_does_not_block_the_others(self, harness):
        received: list[Envelope[Any]] = []

        def broken(env: Envelope[Any]) -> None:
            raise RuntimeError("kaputt")

        harness.bus.subscribe(RUN_REQUESTED, "broken", broken)
        harness.bus.subscribe(RUN_REQUESTED, "web-api", received.append)
        harness.bus.publish(_requested())
        harness.settle()
        assert len(received) == 1

    def test_failed_delivery_is_repeated_with_the_same_event_id(self, harness):
        attempts: list[Envelope[Any]] = []

        def flaky(env: Envelope[Any]) -> None:
            attempts.append(env)
            if len(attempts) == 1:
                raise ConnectionError("kurz weg")

        harness.bus.subscribe(RUN_REQUESTED, "market-data", flaky)
        harness.bus.publish(_requested())
        harness.settle()
        assert len(attempts) == 2
        assert attempts[0].id == attempts[1].id  # Grundlage fuer die Inbox (Deduplizierung)
        assert harness.dead == []

    def test_after_max_deliver_the_event_is_a_dead_letter(self, harness):
        attempts: list[int] = []

        def broken(env: Envelope[Any]) -> None:
            attempts.append(1)
            raise RuntimeError("dauerhaft kaputt")

        harness.bus.subscribe(RUN_REQUESTED, "market-data", broken)
        sent = _requested()
        harness.bus.publish(sent)
        harness.settle()
        assert len(attempts) == MAX_DELIVER
        assert len(harness.dead) == 1
        dead = harness.dead[0]
        assert (dead.consumer, dead.envelope.id, dead.attempts) == ("market-data", sent.id, 3)
        assert "dauerhaft kaputt" in str(dead.error)

    def test_publishing_continues_after_a_dead_letter(self, harness):
        received: list[int] = []

        def broken_once_per_event(env: Envelope[Any]) -> None:
            if env.data.run_id == 1:
                raise RuntimeError("nur Run 1")
            received.append(env.data.run_id)

        harness.bus.subscribe(RUN_REQUESTED, "market-data", broken_once_per_event)
        harness.bus.publish(_requested(1))
        harness.bus.publish(_requested(2))
        harness.settle()
        assert received == [2]
        assert [d.envelope.data.run_id for d in harness.dead] == [1]


def test_max_deliver_must_be_positive():
    with pytest.raises(ValueError, match="max_deliver"):
        InProcessBus(max_deliver=0)
