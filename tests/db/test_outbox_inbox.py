"""Outbox und Inbox (P4.2) gegen ein echtes PostgreSQL (docs/architecture/events.md).

Die Outbox haelt ein Event fest, bis das Relay es veroeffentlicht hat. Die Inbox sorgt dafuer,
dass ein Consumer ein Event nur einmal verarbeitet. Beide schreiben in der Transaktion der
Fachdaten. Die Tests nehmen das Schema ``scoring``, der Schreibschutz gilt fuer alle vier.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError, ProgrammingError
from sqlalchemy.orm import Session

from va_contracts import Envelope, new_envelope, parse_envelope
from va_contracts.events.v1 import (
    FETCH_PROGRESSED,
    REPORT_SENT,
    RUN_FAILED,
    FetchProgressedV1,
    ReportSentV1,
    RunFailedV1,
    RunOptionsV1,
)
from va_platform.bus import follow_up
from va_platform.db import APP_SCHEMAS, session_scope
from va_platform.messaging import Inbox, Outbox, OutboxMessage, OutboxRelay, VolatileEventError
from va_scoring.adapters.postgres.models import ScoringInbox, ScoringOutbox

CONSUMER = "notification"


def _sent(report_id: int = 7) -> Envelope[ReportSentV1]:
    data = ReportSentV1(run_id=1, report_id=report_id, subject="[ok 1/1]", dry_run=False)
    return new_envelope(REPORT_SENT, data, source="va/test", correlationid="1")


@dataclass
class RecordingPublisher:
    """Wie JetStream: nimmt an oder wirft. ``fail_at`` zaehlt die Aufrufe ab 1."""

    fail_at: set[int] = field(default_factory=set)
    sent: list[OutboxMessage] = field(default_factory=list)
    calls: int = 0

    async def publish(self, message: OutboxMessage) -> None:
        self.calls += 1
        if self.calls in self.fail_at:
            msg = "NATS nicht erreichbar"
            raise ConnectionError(msg)
        self.sent.append(message)


def _relay(engine: Engine, publisher: RecordingPublisher, **kwargs: Any) -> OutboxRelay:
    return OutboxRelay(engine, Outbox(ScoringOutbox), publisher, **kwargs)


def _publish(engine: Engine, publisher: RecordingPublisher, **kwargs: Any) -> int:
    return asyncio.run(_relay(engine, publisher, **kwargs).publish_pending())


def _add(engine: Engine, *envelopes: Envelope[Any]) -> None:
    with session_scope(engine) as s:
        for envelope in envelopes:
            Outbox(ScoringOutbox).add(s, envelope)


def _rows(engine: Engine, sql: str) -> list[Any]:
    with engine.connect() as conn:
        return list(conn.execute(text(sql)).all())


def _pending(engine: Engine) -> list[UUID]:
    rows = _rows(
        engine,
        "SELECT id FROM scoring.outbox WHERE published_at IS NULL ORDER BY created_at, id",
    )
    return [row.id for row in rows]


def _exec(engine: Engine, sql: str, **params: object) -> None:
    with engine.begin() as conn:
        conn.execute(text(sql), params)


class TestOutbox:
    def test_event_is_stored_with_subject_and_envelope(self, engine):
        envelope = _sent()
        _add(engine, envelope)
        [row] = _rows(engine, "SELECT id, subject, payload, published_at FROM scoring.outbox")
        assert row.id == envelope.id
        assert row.subject == "va.notification.report.sent"
        assert row.payload == envelope.model_dump(mode="json")
        assert row.published_at is None

    def test_event_exists_only_after_commit(self, engine):
        publisher = RecordingPublisher()
        with Session(engine) as s:
            Outbox(ScoringOutbox).add(s, _sent())
            s.flush()
            assert _publish(engine, publisher) == 0  # vor dem Commit sieht das Relay nichts
            s.commit()
        assert _publish(engine, publisher) == 1

    def test_rollback_leaves_no_entry(self, engine):
        def fails_after_the_event() -> None:
            with session_scope(engine) as s:
                Outbox(ScoringOutbox).add(s, _sent())
                msg = "Fachdaten ungueltig"
                raise RuntimeError(msg)

        with pytest.raises(RuntimeError):
            fails_after_the_event()
        assert _rows(engine, "SELECT id FROM scoring.outbox") == []

    def test_volatile_events_never_enter_the_outbox(self, engine):
        data = FetchProgressedV1(run_id=1, done=1, total=90, symbol="SAP.DE", ok=True)
        envelope = new_envelope(FETCH_PROGRESSED, data, source="va/test")
        with pytest.raises(VolatileEventError), session_scope(engine) as s:
            Outbox(ScoringOutbox).add(s, envelope)
        assert _rows(engine, "SELECT id FROM scoring.outbox") == []


class TestRelay:
    def test_publishes_pending_events_in_order_and_marks_them(self, engine):
        first, second, third = _sent(1), _sent(2), _sent(3)
        _add(engine, first, second)
        _add(engine, third)
        publisher = RecordingPublisher()

        assert _publish(engine, publisher) == 3
        assert [m.id for m in publisher.sent] == [first.id, second.id, third.id]
        assert {m.subject for m in publisher.sent} == {"va.notification.report.sent"}
        assert parse_envelope(publisher.sent[0].payload) == first
        assert _pending(engine) == []

        assert _publish(engine, publisher) == 0  # nichts mehr offen
        assert len(publisher.sent) == 3

    def test_failed_publish_keeps_it_and_all_later_ones(self, engine):
        first, second, third = _sent(1), _sent(2), _sent(3)
        _add(engine, first, second, third)

        with pytest.raises(ConnectionError):
            _publish(engine, RecordingPublisher(fail_at={2}))
        assert _pending(engine) == [second.id, third.id]

        publisher = RecordingPublisher()
        assert _publish(engine, publisher) == 2  # der naechste Lauf holt sie nach
        assert [m.id for m in publisher.sent] == [second.id, third.id]
        assert _pending(engine) == []

    def test_more_events_than_one_batch(self, engine):
        envelopes = [_sent(i) for i in range(1, 6)]
        _add(engine, *envelopes)
        publisher = RecordingPublisher()
        assert _publish(engine, publisher, batch_size=2) == 5
        assert [m.id for m in publisher.sent] == [e.id for e in envelopes]

    def test_run_survives_failed_publishes(self, engine, caplog):
        _add(engine, _sent())
        publisher = RecordingPublisher(fail_at={1, 2})
        relay = _relay(engine, publisher)

        async def scenario() -> None:
            stop = asyncio.Event()
            task = asyncio.create_task(relay.run(stop, interval=0.01, max_interval=0.05))
            async with asyncio.timeout(10):
                while not publisher.sent:
                    await asyncio.sleep(0.01)
            stop.set()
            await task

        with caplog.at_level(logging.INFO, logger="va_platform.messaging.outbox"):
            asyncio.run(scenario())
        assert publisher.calls >= 3
        assert _pending(engine) == []
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 2
        assert [bool(r.exc_info) for r in warnings] == [True, False]  # Traceback nur 1x
        assert any("wieder erreichbar" in r.getMessage() for r in caplog.records)


class TestInbox:
    def test_duplicate_is_processed_once_per_consumer(self, engine):
        envelope = _sent()
        calls: list[str] = []

        def work(consumer: str) -> Callable[[Session], None]:
            return lambda _session: calls.append(consumer)

        inbox = Inbox(ScoringInbox)
        assert inbox.process_once(engine, envelope.id, CONSUMER, work(CONSUMER)) is True
        assert inbox.process_once(engine, envelope.id, CONSUMER, work(CONSUMER)) is False
        assert inbox.process_once(engine, envelope.id, "web-api", work("web-api")) is True
        assert calls == [CONSUMER, "web-api"]
        rows = _rows(engine, "SELECT consumer, error FROM scoring.inbox ORDER BY consumer")
        assert [(r.consumer, r.error) for r in rows] == [(CONSUMER, None), ("web-api", None)]

    def test_failed_processing_leaves_no_entry(self, engine):
        envelope = _sent()
        inbox = Inbox(ScoringInbox)

        def failing(_session: Session) -> None:
            msg = "Handler gescheitert"
            raise RuntimeError(msg)

        with pytest.raises(RuntimeError):
            inbox.process_once(engine, envelope.id, CONSUMER, failing)
        assert _rows(engine, "SELECT message_id FROM scoring.inbox") == []
        assert inbox.process_once(engine, envelope.id, CONSUMER, lambda _s: None) is True

    def test_inbox_entry_and_follow_up_event_commit_together(self, engine):
        cause = _sent()
        data = RunFailedV1(
            run_id=1,
            trigger="scheduled",
            options=RunOptionsV1(),
            stage="notification",
            reason="SMTP nicht erreichbar",
        )
        failed = follow_up(cause, RUN_FAILED, data, source="va/test")
        inbox = Inbox(ScoringInbox)

        def emit_then_fail(session: Session) -> None:
            Outbox(ScoringOutbox).add(session, failed)
            msg = "nach dem Folge-Event gescheitert"
            raise RuntimeError(msg)

        with pytest.raises(RuntimeError):
            inbox.process_once(engine, cause.id, CONSUMER, emit_then_fail)
        assert _rows(engine, "SELECT message_id FROM scoring.inbox") == []
        assert _rows(engine, "SELECT id FROM scoring.outbox") == []

        def emit(session: Session) -> None:
            Outbox(ScoringOutbox).add(session, failed)

        assert inbox.process_once(engine, cause.id, CONSUMER, emit) is True
        assert len(_rows(engine, "SELECT message_id FROM scoring.inbox")) == 1
        [row] = _rows(engine, "SELECT payload FROM scoring.outbox")
        assert row.payload["causationid"] == str(cause.id)

    @pytest.mark.parametrize(("first_commits", "second_processes"), [(True, False), (False, True)])
    def test_parallel_delivery_waits_for_the_first(self, engine, first_commits, second_processes):
        """Stellt JetStream erneut zu, waehrend die erste Zustellung noch laeuft (ack_wait)."""
        envelope = _sent()
        inbox = Inbox(ScoringInbox)
        with Session(engine) as first, ThreadPoolExecutor(max_workers=1) as pool:
            assert inbox.claim(first, envelope.id, CONSUMER) is True
            second = pool.submit(inbox.process_once, engine, envelope.id, CONSUMER, lambda _s: None)
            time.sleep(0.5)
            assert not second.done()  # wartet auf die Transaktion der ersten Zustellung
            if first_commits:
                first.commit()
            else:
                first.rollback()
            assert second.result(timeout=10) is second_processes
        assert len(_rows(engine, "SELECT message_id FROM scoring.inbox")) == 1

    def test_dead_letter_is_not_processed_again(self, engine):
        envelope = _sent()
        inbox = Inbox(ScoringInbox)
        with session_scope(engine) as s:
            assert inbox.record_dead_letter(s, envelope.id, CONSUMER, "Traceback ...") is True
        calls: list[Session] = []
        assert inbox.process_once(engine, envelope.id, CONSUMER, calls.append) is False
        assert calls == []
        [row] = _rows(engine, "SELECT error FROM scoring.inbox")
        assert row.error == "Traceback ..."


def _insert_raw(engine: Engine, schema: str, event_id: UUID) -> None:
    _exec(
        engine,
        f"INSERT INTO {schema}.outbox (id, subject, payload) VALUES (:id, 'va.x', '{{}}')",
        id=event_id,
    )


@pytest.mark.parametrize("schema", APP_SCHEMAS)
class TestOutboxGuard:
    def test_published_at_may_be_set_once(self, engine, schema):
        event_id = _sent().id
        _insert_raw(engine, schema, event_id)
        update = f"UPDATE {schema}.outbox SET published_at = now() WHERE id = :id"
        _exec(engine, update, id=event_id)
        with pytest.raises(DBAPIError, match="veroeffentlicht"):
            _exec(engine, update, id=event_id)

    def test_update_must_set_published_at(self, engine, schema):
        event_id = _sent().id
        _insert_raw(engine, schema, event_id)
        with pytest.raises(DBAPIError, match="published_at"):
            _exec(
                engine, f"UPDATE {schema}.outbox SET subject = 'va.y' WHERE id = :id", id=event_id
            )

    @pytest.mark.parametrize(
        "assignment",
        ["subject = 'va.y'", "payload = '{\"a\": 1}'", "created_at = now() - interval '1 day'"],
    )
    def test_other_columns_stay_unchanged(self, engine, schema, assignment):
        event_id = _sent().id
        _insert_raw(engine, schema, event_id)
        with pytest.raises(DBAPIError, match="nur published_at"):
            _exec(
                engine,
                f"UPDATE {schema}.outbox SET published_at = now(), {assignment} WHERE id = :id",
                id=event_id,
            )

    def test_outbox_and_inbox_are_never_deleted(self, engine, schema):
        event_id = _sent().id
        _insert_raw(engine, schema, event_id)
        _exec(
            engine,
            f"INSERT INTO {schema}.inbox (message_id, consumer) VALUES (:id, 'scoring')",
            id=event_id,
        )
        for sql in (
            f"DELETE FROM {schema}.outbox",
            f"DELETE FROM {schema}.inbox",
            f"UPDATE {schema}.inbox SET consumer = 'x'",
        ):
            with pytest.raises(DBAPIError, match="verboten"):
                _exec(engine, sql)


class TestRoles:
    def test_app_role_writes_relays_and_deduplicates(self, app_engine):
        _add(app_engine, _sent())
        assert _publish(app_engine, RecordingPublisher()) == 1
        inbox = Inbox(ScoringInbox)
        envelope = _sent()
        assert inbox.process_once(app_engine, envelope.id, CONSUMER, lambda _s: None) is True
        assert inbox.process_once(app_engine, envelope.id, CONSUMER, lambda _s: None) is False

    def test_app_role_may_only_set_published_at(self, engine, app_engine):
        _insert_raw(engine, "scoring", _sent().id)
        with pytest.raises(ProgrammingError, match="permission denied"):
            _exec(app_engine, "UPDATE scoring.outbox SET subject = 'va.y'")
        with pytest.raises(ProgrammingError, match="permission denied"):
            _exec(app_engine, "DELETE FROM scoring.outbox")

    def test_read_role_cannot_mark_events(self, engine, read_engine):
        _insert_raw(engine, "scoring", _sent().id)
        assert len(_rows(read_engine, "SELECT id FROM scoring.outbox")) == 1
        with pytest.raises(ProgrammingError, match="permission denied"):
            _exec(read_engine, "UPDATE scoring.outbox SET published_at = now()")
