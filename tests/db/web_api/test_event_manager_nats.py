"""Der Event-Consumer des web-api ueber NATS (P4.4): Datenbank und NATS sind echt.

Ein Event, das ueber JetStream kommt, landet in der Projektion, und die Meldung traegt die
Stream-Sequenz (Grundlage fuer ``resumeFrom`` in P4.5). Ohne ``TEST_DATABASE_URL`` oder
``TEST_NATS_URL`` uebersprungen.
"""

from __future__ import annotations

import time
from typing import Any

from sqlalchemy import Engine, text

from va_contracts import new_envelope
from va_contracts.events.v1 import RUN_REQUESTED, RunOptionsV1, ScreeningRunRequestedV1
from va_platform.nats import NatsBus
from va_web_api.events import EventMessage, open_event_consumer


class Recorder:
    def __init__(self) -> None:
        self.messages: list[EventMessage] = []

    def publish(self, message: EventMessage) -> None:
        self.messages.append(message)


def _status(engine: Engine) -> list[Any]:
    with engine.connect() as conn:
        return list(conn.execute(text("SELECT run_id, status FROM web.run_status")).all())


def test_event_from_nats_lands_in_the_projection(engine, web_engine, nats_url):
    recorder = Recorder()
    consumer = open_event_consumer(nats_url, web_engine, recorder)
    sender = NatsBus(nats_url)
    sender.start()
    try:
        data = ScreeningRunRequestedV1(run_id=5, trigger="manual", options=RunOptionsV1())
        sender.publish(new_envelope(RUN_REQUESTED, data, source="va/test"))
        consumer.settle(timeout=20)
        deadline = time.monotonic() + 5
        while not recorder.messages and time.monotonic() < deadline:
            time.sleep(0.05)
    finally:
        sender.close()
        consumer.close()

    assert [tuple(r) for r in _status(engine)] == [(5, "requested")]
    [message] = recorder.messages
    assert (message.topic, message.type) == ("runs", RUN_REQUESTED.type)
    assert message.seq is not None
    assert message.seq >= 1
