"""``NatsBus`` (P4.3): was nur ueber NATS vorkommt.

Die gemeinsamen Vertragstests stehen in ``test_bus.py``. Hier steht, was es im Prozess nicht
gibt: fremde Nachrichten im Stream, lange Handler, das geordnete Schliessen und das
Zusammenspiel mit der Provisionierung aus P4.1. Ohne ``TEST_NATS_URL`` uebersprungen.
"""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Awaitable, Callable, Iterator
from typing import Any

import pytest

from va_contracts import Envelope, new_envelope
from va_contracts.events.v1 import (
    FETCH_PROGRESSED,
    REPORT_SENT,
    RUN_REQUESTED,
    FetchProgressedV1,
    RunOptionsV1,
    ScreeningRunRequestedV1,
)
from va_platform.bus import DeadLetter

DAY = 24 * 60 * 60


def _requested(run_id: int = 1) -> Envelope[ScreeningRunRequestedV1]:
    data = ScreeningRunRequestedV1(run_id=run_id, trigger="manual", options=RunOptionsV1())
    return new_envelope(RUN_REQUESTED, data, source="va/test", correlationid=str(run_id))


def _with_nats(url: str, action: Callable[[Any, Any], Awaitable[Any]]) -> Any:
    """Eine eigene Verbindung neben dem Bus, fuer Rohdaten und Abfragen: (js, jsm)."""

    async def main() -> Any:
        import nats

        nc = await nats.connect(url)
        try:
            return await action(nc.jetstream(), nc.jsm())
        finally:
            await nc.close()

    return asyncio.run(main())


@pytest.fixture
def dead() -> list[DeadLetter]:
    return []


@pytest.fixture
def bus(nats_url, dead) -> Iterator[Any]:
    from va_platform.nats import NatsBus

    nats_bus = NatsBus(nats_url, max_deliver=2, on_dead_letter=dead.append, retry_delay=0.05)
    nats_bus.start()
    try:
        yield nats_bus
    finally:
        nats_bus.close()


class TestForeignMessages:
    def test_unknown_payload_version_becomes_a_dead_letter(self, nats_url, bus, dead):
        """Eine neuere Version, die dieser Stand nicht kennt: erst Wiederholung, dann Dead
        Letter mit der lesbaren Huelle."""
        received: list[Envelope[Any]] = []
        bus.subscribe(RUN_REQUESTED, "market-data", received.append)
        sent = _requested()
        raw = sent.model_dump_json().replace(":v1", ":v9").encode()

        async def publish(js: Any, jsm: Any) -> None:
            await js.publish(RUN_REQUESTED.subject, raw, headers={"Nats-Msg-Id": str(sent.id)})

        _with_nats(nats_url, publish)
        bus.settle(timeout=20)
        assert received == []
        assert [(d.consumer, d.attempts) for d in dead] == [("market-data", 2)]
        assert dead[0].envelope.id == sent.id
        assert dead[0].envelope.type == RUN_REQUESTED.type

    def test_unreadable_envelope_is_dropped(self, nats_url, bus, dead):
        received: list[Envelope[Any]] = []
        bus.subscribe(RUN_REQUESTED, "market-data", received.append)

        async def publish(js: Any, jsm: Any) -> None:
            await js.publish(RUN_REQUESTED.subject, b"kein json")

        _with_nats(nats_url, publish)
        bus.settle(timeout=20)
        assert received == []
        assert dead == []  # ohne lesbare Huelle gibt es kein Event fuer den Callback

        async def pending(js: Any, jsm: Any) -> tuple[int, int]:
            info = await jsm.consumer_info("VA_EVENTS", "market-data")
            return info.num_pending, info.num_ack_pending

        assert _with_nats(nats_url, pending) == (0, 0)  # verworfen, kommt nicht wieder


class TestLongHandlers:
    def test_handler_longer_than_ack_wait_runs_once(self, nats_url, dead):
        """In-Progress-Acks: Der Abruf von market-data dauert Minuten, ack_wait 60 s."""
        from va_platform.nats import NatsBus

        calls: list[float] = []

        def slow(env: Envelope[Any]) -> None:
            calls.append(time.monotonic())
            time.sleep(2.5)

        nats_bus = NatsBus(nats_url, max_deliver=2, on_dead_letter=dead.append, ack_wait=1.0)
        nats_bus.start()
        try:
            nats_bus.subscribe(RUN_REQUESTED, "slow", slow)
            nats_bus.publish(_requested())
            nats_bus.settle(timeout=20)
        finally:
            nats_bus.close()
        assert len(calls) == 1
        assert dead == []

    def test_close_lets_a_running_handler_finish_and_ack(self, nats_url, bus):
        started = threading.Event()
        finished: list[int] = []

        def handler(env: Envelope[Any]) -> None:
            started.set()
            time.sleep(1.0)
            finished.append(env.data.run_id)

        bus.subscribe(RUN_REQUESTED, "market-data", handler)
        bus.publish(_requested(7))
        assert started.wait(timeout=10)
        bus.close()
        assert finished == [7]

        async def pending(js: Any, jsm: Any) -> tuple[int, int]:
            info = await jsm.consumer_info("VA_EVENTS", "market-data")
            return info.num_pending, info.num_ack_pending

        assert _with_nats(nats_url, pending) == (0, 0)


class TestProvisioning:
    def test_stream_is_provisioned_and_consumers_stay_as_they_are(self, nats_url, bus):
        from nats.js.api import StorageType

        bus.subscribe(RUN_REQUESTED, "market-data", lambda env: None)

        async def state(js: Any, jsm: Any) -> tuple[Any, Any]:
            stream = (await jsm.stream_info("VA_EVENTS")).config
            consumer = (await jsm.consumer_info("VA_EVENTS", "market-data")).config
            return stream, consumer

        stream, consumer = _with_nats(nats_url, state)
        assert stream.storage == StorageType.FILE
        assert stream.max_age == 30 * DAY
        assert stream.duplicate_window == 10 * 60
        assert consumer.filter_subject == RUN_REQUESTED.subject
        assert consumer.ack_wait == 60
        assert consumer.max_deliver == 5

    def test_provisioned_consumer_must_cover_the_subject(self, bus):
        with pytest.raises(ValueError, match="market-data"):
            bus.subscribe(REPORT_SENT, "market-data", lambda env: None)

    def test_bus_limit_must_not_exceed_the_consumer_limit(self, nats_url):
        from va_platform.nats import NatsBus

        with pytest.raises(ValueError, match="max_deliver"):
            NatsBus(nats_url, max_deliver=6)


class TestVolatileEvents:
    def test_progress_bypasses_the_stream(self, nats_url, bus):
        data = FetchProgressedV1(run_id=1, done=1, total=90, symbol="SAP.DE", ok=True)
        bus.publish(new_envelope(FETCH_PROGRESSED, data, source="va/test"))

        async def messages(js: Any, jsm: Any) -> int:
            return (await jsm.stream_info("VA_EVENTS")).state.messages

        assert _with_nats(nats_url, messages) == 0

    def test_volatile_events_reach_a_subscriber(self, bus):
        """P4.5: Fortschritt fuer den WebSocket, ueber Core-NATS ohne Wiederholung."""
        from va_platform.nats import current_sequence

        received: list[tuple[int, int | None]] = []
        bus.subscribe(
            FETCH_PROGRESSED,
            "web-api",
            lambda env: received.append((env.data.done, current_sequence())),
        )
        for done in (1, 2):
            data = FetchProgressedV1(run_id=1, done=done, total=90, symbol="SAP.DE", ok=True)
            bus.publish(new_envelope(FETCH_PROGRESSED, data, source="va/test"))
        deadline = time.monotonic() + 10
        while len(received) < 2 and time.monotonic() < deadline:
            time.sleep(0.02)
        assert received == [(1, None), (2, None)]  # fluechtig: ohne Stream-Sequenz


class TestPrivateEvents:
    """D1.6: priv.va. ueber VA_PRIVATE, nicht ueber VA_EVENTS."""

    def test_a_private_event_reaches_its_consumer_through_va_private(self, nats_url, bus):
        from datetime import UTC, datetime, timedelta

        from va_contracts.events.v1 import (
            EMAIL_CONFIRMATION_REQUESTED,
            EmailConfirmationRequestedV1,
        )

        received: list[str] = []
        bus.subscribe(
            EMAIL_CONFIRMATION_REQUESTED,
            "notification-private",
            lambda env: received.append(env.data.email),
        )
        data = EmailConfirmationRequestedV1(
            user_id=2,
            email="anna@example.com",
            link="https://va.example/confirm-email?token=x",
            expires_at=datetime.now(UTC) + timedelta(hours=24),
        )
        bus.publish(new_envelope(EMAIL_CONFIRMATION_REQUESTED, data, source="va/test"))
        bus.settle(timeout=20)
        assert received == ["anna@example.com"]

        async def counts(js: Any, jsm: Any) -> tuple[int, int]:
            private = (await jsm.stream_info("VA_PRIVATE")).state.messages
            public = (await jsm.stream_info("VA_EVENTS")).state.messages
            return private, public

        assert _with_nats(nats_url, counts) == (1, 0)

    def test_a_provisioned_consumer_comes_with_its_stream_when_subscribed(self, nats_url):
        """Startet ein Dienst nur mit seinem Haupt-Consumer (``run_service(name=...)``), legt das
        Abonnieren eines weiteren vorgegebenen Consumers ihn samt Stream an, wie die
        Provisionierung. Vorher scheiterte es an einem frischen Server mit 'stream not found'."""
        from va_contracts.events.v1 import EMAIL_CONFIRMATION_REQUESTED
        from va_platform.nats import NatsBus

        bus = NatsBus(nats_url, consumers=("notification",))
        bus.start()
        try:
            bus.subscribe(EMAIL_CONFIRMATION_REQUESTED, "notification-private", lambda env: None)
        finally:
            bus.close()

        async def private(js: Any, jsm: Any) -> tuple[str | None, str | None]:
            info = await jsm.consumer_info("VA_PRIVATE", "notification-private")
            return info.config.filter_subject, str(info.config.deliver_policy)

        subject, policy = _with_nats(nats_url, private)
        assert subject == "priv.va.identity.email_confirmation.requested"
        assert "new" not in policy.lower()  # wie provisioniert: auch aeltere Nachrichten


class TestSequence:
    def test_handler_sees_the_stream_sequence(self, bus):
        """P4.4: Das web-api reicht sie an den WebSocket weiter (resumeFrom, P4.5)."""
        from va_platform.nats import current_sequence

        seen: list[int | None] = []
        bus.subscribe(RUN_REQUESTED, "market-data", lambda env: seen.append(current_sequence()))
        bus.publish(_requested(1))
        bus.publish(_requested(2))
        bus.settle(timeout=20)
        assert seen == [1, 2]
        assert current_sequence() is None  # ausserhalb einer Zustellung


def test_unreachable_server_fails_fast():
    """P4.4: Beim Start nicht minutenlang haengen (nats-py versucht es sonst 60-mal)."""
    from va_platform.nats import NatsBus

    bus = NatsBus("nats://127.0.0.1:1", timeout=2)
    started = time.monotonic()
    with pytest.raises(Exception):  # noqa: B017, PT011 - nats-py meldet NoServersError o. Ae.
        bus.start()
    assert time.monotonic() - started < 30
