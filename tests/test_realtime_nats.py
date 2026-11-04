"""``NatsReplayer`` (P4.5): verpasste Events fuer den WebSocket aus dem Stream ``VA_EVENTS``.

Gegen einen echten NATS-Server, nur mit ``TEST_NATS_URL``. Der Stream ist fuer jeden Test neu.
"""

from __future__ import annotations

import asyncio
from typing import Any

from va_contracts import new_envelope
from va_contracts.events.v1 import (
    PROFILE_SAVED,
    REPORT_SENT,
    RUN_REQUESTED,
    ProfileSavedV1,
    ReportSentV1,
    RunOptionsV1,
    ScreeningRunRequestedV1,
)
from va_platform.nats import NatsBus
from va_web_api.realtime.replay import NatsReplayer


def _publish_three(url: str) -> None:
    bus = NatsBus(url)  # legt den Stream per Provisionierung an
    bus.start()
    try:
        data = ScreeningRunRequestedV1(run_id=1, trigger="manual", options=RunOptionsV1())
        bus.publish(new_envelope(RUN_REQUESTED, data, source="va/test"))
        bus.publish(
            new_envelope(PROFILE_SAVED, ProfileSavedV1(profile_id=1, version=2), source="t")
        )
        sent = ReportSentV1(run_id=1, report_id=3, subject="[ok]", dry_run=False)
        bus.publish(new_envelope(REPORT_SENT, sent, source="va/test"))
    finally:
        bus.close()


def _replay(url: str, topics: tuple[str, ...], after: int, **kwargs: Any) -> Any:
    async def main() -> Any:
        replayer = NatsReplayer(url, **kwargs)
        try:
            return await replayer.last_seq(), await replayer.replay(topics, after)
        finally:
            await replayer.close()

    return asyncio.run(main())


def test_replays_the_events_of_the_topics_after_a_sequence(nats_url):
    _publish_three(nats_url)
    last, events = _replay(nats_url, ("runs",), 0)
    assert last == 3
    assert [(e.topic, e.type, e.seq) for e in events] == [
        ("runs", RUN_REQUESTED.type, 1),
        ("runs", REPORT_SENT.type, 3),
    ]
    assert events[0].data["run_id"] == 1

    _, later = _replay(nats_url, ("runs", "profiles"), 1)
    assert [(e.topic, e.seq) for e in later] == [("profiles", 2), ("runs", 3)]


def test_nothing_missed_is_an_empty_replay(nats_url):
    _publish_three(nats_url)
    _, events = _replay(nats_url, ("runs",), 3)
    assert events == []


def test_too_large_a_gap_is_none(nats_url):
    _publish_three(nats_url)
    _, events = _replay(nats_url, ("runs",), 0, limit=2)
    assert events is None


def test_unreachable_nats_is_none():
    last, events = _replay("nats://127.0.0.1:1", ("runs",), 0)
    assert (last, events) == (None, None)
