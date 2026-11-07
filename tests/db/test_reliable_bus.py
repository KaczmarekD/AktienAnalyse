"""``ReliableBus`` (P4.3b): jedes Event je Consumer einmal, Folge-Events ueber die Outbox.

Der Bus ist der im Prozess, Inbox und Outbox sind die echten Tabellen des Schemas ``scoring``.
Die Fachdaten schreibt der Handler selbst, hier geht es nur um Zustellung und Folge-Events.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import Engine, text

from va_contracts import Envelope, new_envelope
from va_contracts.events.v1 import (
    EMAIL_CONFIRMATION_REQUESTED,
    FETCH_PROGRESSED,
    REPORT_SENT,
    RUN_REQUESTED,
    EmailConfirmationRequestedV1,
    FetchProgressedV1,
    ReportSentV1,
    RunOptionsV1,
    ScreeningRunRequestedV1,
)
from va_platform.bus import DeadLetter, InProcessBus
from va_platform.db import session_scope
from va_platform.messaging import Outbox, OutboxMessage, ReliableBus, drain_outbox
from va_scoring.adapters.postgres.models import ScoringInbox, ScoringOutbox

CONSUMER = "scoring"
MAX_AGE = timedelta(hours=2)


def _requested(run_id: int = 1, *, age: timedelta | None = None) -> Envelope[Any]:
    data = ScreeningRunRequestedV1(run_id=run_id, trigger="manual", options=RunOptionsV1())
    envelope = new_envelope(RUN_REQUESTED, data, source="va/test", correlationid=str(run_id))
    if age is None:
        return envelope
    return envelope.model_copy(update={"time": datetime.now(UTC) - age})


def _sent(run_id: int = 1) -> Envelope[Any]:
    data = ReportSentV1(run_id=run_id, report_id=7, subject="[ok 1/1]", dry_run=False)
    return new_envelope(REPORT_SENT, data, source="va/test")


def _rows(engine: Engine, sql: str) -> list[Any]:
    with engine.connect() as conn:
        return list(conn.execute(text(sql)).all())


class Chain:
    """Bus im Prozess, ein ReliableBus fuer scoring und eine Sonde fuer ``report.sent``."""

    def __init__(self, engine: Engine) -> None:
        self.dead: list[DeadLetter] = []
        self.bus = InProcessBus(max_deliver=1, on_dead_letter=self.dead.append)
        self.reliable = ReliableBus(
            self.bus, engine, inbox=ScoringInbox, outbox=ScoringOutbox, max_age=MAX_AGE
        )
        self.calls: list[Envelope[Any]] = []
        self.received: list[Envelope[Any]] = []
        self.bus.subscribe(REPORT_SENT, "probe", self.received.append)

    def handle_with(self, handler: Any) -> None:
        def wrapped(env: Envelope[Any]) -> None:
            self.calls.append(env)
            handler(env)

        self.reliable.subscribe(RUN_REQUESTED, CONSUMER, wrapped)


@pytest.fixture
def chain(engine) -> Chain:
    return Chain(engine)


class TestDelivery:
    def test_follow_up_events_go_through_the_outbox(self, engine, chain):
        chain.handle_with(lambda env: chain.reliable.publish(_sent(env.data.run_id)))
        request = _requested()
        chain.bus.publish(request)

        assert [e.data.run_id for e in chain.received] == [1]
        [row] = _rows(engine, "SELECT subject, published_at FROM scoring.outbox")
        assert row.subject == "va.notification.report.sent"
        assert row.published_at is not None
        [inbox] = _rows(engine, "SELECT message_id, consumer, error FROM scoring.inbox")
        assert (inbox.message_id, inbox.consumer, inbox.error) == (request.id, CONSUMER, None)

    def test_redelivery_runs_the_handler_once(self, engine, chain):
        chain.handle_with(lambda env: chain.reliable.publish(_sent(env.data.run_id)))
        request = _requested()
        chain.bus.publish(request)
        chain.bus.publish(request)  # dieselbe Event-ID, wie nach einem verlorenen Ack
        assert len(chain.calls) == 1
        assert len(chain.received) == 1
        assert len(_rows(engine, "SELECT id FROM scoring.outbox")) == 1

    def test_failing_handler_leaves_nothing(self, engine, chain):
        def broken(env: Envelope[Any]) -> None:
            chain.reliable.publish(_sent(env.data.run_id))
            msg = "Bug im Handler"
            raise RuntimeError(msg)

        chain.handle_with(broken)
        chain.bus.publish(_requested())
        assert len(chain.dead) == 1
        assert chain.received == []
        assert _rows(engine, "SELECT message_id FROM scoring.inbox") == []
        assert _rows(engine, "SELECT id FROM scoring.outbox") == []

    def test_stale_event_is_skipped(self, engine, chain):
        """Aus einem abgebrochenen Lauf: aelter als max_age startet nichts mehr."""
        chain.handle_with(lambda env: chain.reliable.publish(_sent(env.data.run_id)))
        chain.bus.publish(_requested(age=MAX_AGE + timedelta(minutes=1)))
        assert chain.calls == []
        assert chain.received == []
        assert _rows(engine, "SELECT message_id FROM scoring.inbox") == []

    def test_an_event_with_its_own_max_age_waits_longer(self, engine, chain):
        """D1.6: Ein Bestaetigungslink gilt 24 h; nach einem Neustart der NAS darf die Mail noch
        raus, auch wenn RUN_TIMEOUT_MINUTES laengst vorbei ist."""
        seen: list[Envelope[Any]] = []
        chain.reliable.subscribe(EMAIL_CONFIRMATION_REQUESTED, "notification-private", seen.append)
        data = EmailConfirmationRequestedV1(
            user_id=2,
            email="anna@example.com",
            link="https://va.example/confirm-email?token=x",
            expires_at=datetime.now(UTC) + timedelta(hours=20),
        )
        old = new_envelope(EMAIL_CONFIRMATION_REQUESTED, data, source="va/test")
        chain.bus.publish(old.model_copy(update={"time": datetime.now(UTC) - timedelta(hours=4)}))
        assert len(seen) == 1
        too_old = new_envelope(EMAIL_CONFIRMATION_REQUESTED, data, source="va/test")
        chain.bus.publish(
            too_old.model_copy(update={"time": datetime.now(UTC) - timedelta(hours=25)})
        )
        assert len(seen) == 1

    def test_volatile_and_outside_events_go_directly(self, engine, chain):
        progress: list[Envelope[Any]] = []
        chain.bus.subscribe(FETCH_PROGRESSED, "probe", progress.append)
        data = FetchProgressedV1(run_id=1, done=1, total=90, symbol="SAP.DE", ok=True)

        def report_progress(env: Envelope[Any]) -> None:
            chain.reliable.publish(new_envelope(FETCH_PROGRESSED, data, source="va/test"))

        chain.handle_with(report_progress)
        chain.bus.publish(_requested())
        chain.reliable.publish(_sent(5))  # ausserhalb einer Zustellung, etwa der Start
        assert len(progress) == 1
        assert [e.data.run_id for e in chain.received] == [5]
        assert _rows(engine, "SELECT id FROM scoring.outbox") == []


class TestLeftovers:
    def test_leftover_entry_goes_out_with_the_next_delivery(self, engine, chain):
        """Committet, aber nie veroeffentlicht (etwa NATS weg beim letzten Versand)."""
        with session_scope(engine) as s:
            Outbox(ScoringOutbox).add(s, _sent(9))
        chain.handle_with(lambda env: None)
        chain.bus.publish(_requested())
        assert [e.data.run_id for e in chain.received] == [9]
        assert _rows(engine, "SELECT id FROM scoring.outbox WHERE published_at IS NULL") == []

    def test_an_already_processed_event_still_sends_leftovers(self, engine, chain):
        chain.handle_with(lambda env: None)
        request = _requested()
        chain.bus.publish(request)
        with session_scope(engine) as s:
            Outbox(ScoringOutbox).add(s, _sent(9))
        chain.bus.publish(request)
        assert len(chain.calls) == 1
        assert [e.data.run_id for e in chain.received] == [9]


class TestDrainOutbox:
    def test_in_order_and_marked(self, engine):
        sent = [_sent(i) for i in (1, 2, 3)]
        with session_scope(engine) as s:
            for envelope in sent:
                Outbox(ScoringOutbox).add(s, envelope)
        published: list[OutboxMessage] = []
        assert drain_outbox(engine, Outbox(ScoringOutbox), published.append) == 3
        assert [m.id for m in published] == [e.id for e in sent]
        assert drain_outbox(engine, Outbox(ScoringOutbox), published.append) == 0

    def test_stops_at_the_first_failure(self, engine):
        sent = [_sent(i) for i in (1, 2, 3)]
        with session_scope(engine) as s:
            for envelope in sent:
                Outbox(ScoringOutbox).add(s, envelope)
        published: list[OutboxMessage] = []

        def flaky(message: OutboxMessage) -> None:
            if len(published) == 1:
                msg = "Bus weg"
                raise ConnectionError(msg)
            published.append(message)

        with pytest.raises(ConnectionError):
            drain_outbox(engine, Outbox(ScoringOutbox), flaky)
        pending = _rows(
            engine,
            "SELECT id FROM scoring.outbox WHERE published_at IS NULL ORDER BY created_at, id",
        )
        assert [row.id for row in pending] == [sent[1].id, sent[2].id]
