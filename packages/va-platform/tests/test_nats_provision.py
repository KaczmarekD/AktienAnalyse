"""JetStream gegen einen echten NATS-Server (docs/architecture/events.md): Provisionierung (P4.1)
und der Publisher der Outbox (P4.2).

Ohne ``TEST_NATS_URL`` uebersprungen, wie die DB-Tests ohne ``TEST_DATABASE_URL``. Lokal
``make test-nats-up`` (Port 54222), in der CI ein Container mit JetStream. Der Server ist ein
Wegwerf-Server: Jeder Test beginnt ohne Stream.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import subprocess
import sys
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

import pytest

URL = os.environ.get("TEST_NATS_URL", "").strip()
pytestmark = pytest.mark.skipif(not URL, reason="TEST_NATS_URL nicht gesetzt (make test-nats-up)")

DAY = 24 * 60 * 60
CONSUMERS = {
    "market-data": ["va.screening.run.requested"],
    "scoring": ["va.marketdata.snapshot.completed"],
    "notification": ["va.scoring.run.completed", "va.screening.run.failed"],
    "web-api": ["va.>"],
}


def _run(scenario: Callable[[Any, Any], Awaitable[None]]) -> None:
    """Verbindung, frischer Server ohne Stream, dann das Szenario mit (nc, jsm)."""

    async def main() -> None:
        import nats
        from nats.js.errors import NotFoundError

        nc = await nats.connect(URL)
        try:
            jsm = nc.jsm()
            with contextlib.suppress(NotFoundError):
                await jsm.delete_stream("VA_EVENTS")
            await scenario(nc, jsm)
        finally:
            await nc.close()

    asyncio.run(main())


def test_stream_as_in_events_md():
    from nats.js.api import StorageType

    from va_platform.nats import provision

    async def scenario(nc: Any, jsm: Any) -> None:
        await provision(jsm)
        config = (await jsm.stream_info("VA_EVENTS")).config
        assert config.subjects == ["va.>"]
        assert config.storage == StorageType.FILE
        assert config.max_age == 30 * DAY
        assert config.duplicate_window == 10 * 60

    _run(scenario)


def test_second_call_changes_nothing():
    from va_platform.nats import provision

    async def scenario(nc: Any, jsm: Any) -> None:
        await provision(jsm)
        first = await jsm.stream_info("VA_EVENTS")
        await provision(jsm)
        second = await jsm.stream_info("VA_EVENTS")
        assert second.created == first.created
        assert second.config == first.config

    _run(scenario)


def test_drifted_setting_is_corrected():
    from va_platform.nats import provision

    async def scenario(nc: Any, jsm: Any) -> None:
        await provision(jsm)
        config = (await jsm.stream_info("VA_EVENTS")).config
        config.max_age = DAY
        await jsm.update_stream(config)
        await provision(jsm)
        assert (await jsm.stream_info("VA_EVENTS")).config.max_age == 30 * DAY

    _run(scenario)


def test_durable_consumers_with_filter_and_limits():
    from nats.js.api import AckPolicy

    from va_platform.nats import provision

    async def scenario(nc: Any, jsm: Any) -> None:
        await provision(jsm)
        await provision(jsm)  # idempotent auch fuer die Consumer
        for name, subjects in CONSUMERS.items():
            config = (await jsm.consumer_info("VA_EVENTS", name)).config
            assert config.durable_name == name
            filters = config.filter_subjects or [config.filter_subject]
            assert sorted(filters) == sorted(subjects), name
            assert config.ack_policy == AckPolicy.EXPLICIT
            assert config.max_deliver == 5

    _run(scenario)


def test_same_message_id_lands_once():
    from va_platform.nats import provision

    async def scenario(nc: Any, jsm: Any) -> None:
        await provision(jsm)
        js = nc.jetstream()
        headers = {"Nats-Msg-Id": "0193f5a2-0000-7000-8000-000000000001"}
        first = await js.publish("va.screening.run.requested", b"{}", headers=headers)
        again = await js.publish("va.screening.run.requested", b"{}", headers=headers)
        # nats-py meldet bei der ersten Nachricht None statt False
        assert not first.duplicate
        assert again.duplicate is True
        assert (await jsm.stream_info("VA_EVENTS")).state.messages == 1

    _run(scenario)


def test_outbox_publisher_sends_the_event_id_as_message_id():
    """P4.2: Das Relay darf doppelt senden, im Stream landet das Event einmal."""
    from va_contracts import new_envelope, parse_envelope
    from va_contracts.events.v1 import REPORT_SENT, ReportSentV1
    from va_platform.messaging import OutboxMessage
    from va_platform.nats import JetStreamPublisher, provision

    data = ReportSentV1(run_id=1, report_id=7, subject="[ok 1/1]", dry_run=False)
    envelope = new_envelope(REPORT_SENT, data, source="va/test")
    message = OutboxMessage(envelope.id, REPORT_SENT.subject, envelope.model_dump_json().encode())

    async def scenario(nc: Any, jsm: Any) -> None:
        await provision(jsm)
        publisher = JetStreamPublisher(nc.jetstream())
        await publisher.publish(message)
        await publisher.publish(message)
        state = (await jsm.stream_info("VA_EVENTS")).state
        assert state.messages == 1
        stored = await jsm.get_msg("VA_EVENTS", state.last_seq)
        assert stored.subject == "va.notification.report.sent"
        assert stored.headers["Nats-Msg-Id"] == str(envelope.id)
        assert parse_envelope(stored.data) == envelope

    _run(scenario)


def test_outbox_publisher_fails_without_the_stream():
    """Ohne Stream kein Ack: Der Eintrag bleibt offen, statt still verloren zu gehen."""
    from nats.js.errors import NoStreamResponseError

    from va_platform.messaging import OutboxMessage
    from va_platform.nats import JetStreamPublisher

    message = OutboxMessage(
        UUID("0193f5a2-0000-7000-8000-000000000002"), "va.notification.report.sent", b"{}"
    )

    async def scenario(nc: Any, jsm: Any) -> None:  # _run hat den Stream geloescht
        with pytest.raises(NoStreamResponseError):
            await JetStreamPublisher(nc.jetstream(), timeout=2).publish(message)

    _run(scenario)


def test_live_messages_stay_out_of_the_stream():
    from nats.js.errors import NoStreamResponseError

    from va_platform.nats import provision

    async def scenario(nc: Any, jsm: Any) -> None:
        await provision(jsm)
        await nc.publish("live.va.marketdata.fetch.progressed", b"{}")
        await nc.flush()
        with pytest.raises(NoStreamResponseError):
            await nc.jetstream().publish("live.va.marketdata.fetch.progressed", b"{}")
        assert (await jsm.stream_info("VA_EVENTS")).state.messages == 0

    _run(scenario)


def test_command_line_provisions_with_nats_url():
    async def wipe(nc: Any, jsm: Any) -> None:
        pass

    _run(wipe)
    result = subprocess.run(  # feste Argumente, keine Shell
        [sys.executable, "-m", "va_platform.nats"],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "NATS_URL": URL},
        timeout=60,
    )
    assert result.returncode == 0, result.stderr

    async def exists() -> None:
        import nats

        nc = await nats.connect(URL)
        try:
            info = await nc.jsm().stream_info("VA_EVENTS")
            assert info.config.subjects == ["va.>"]
        finally:
            await nc.close()

    asyncio.run(exists())
