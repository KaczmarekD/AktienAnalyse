"""Run-Verwaltung des web-api (P4.7) gegen ein echtes PostgreSQL, mit steuerbarer Uhr.

Das web-api legt Runs an (Start aus dem UI, Scheduler), ueberwacht sie (Watchdog) und schliesst
sie aus den Events ab. Es schreibt dafuer mit der Rolle ``va_web`` in ``batch.run``; welche Runs
ihm gehoeren, steht in ``web.run_request``. Runs des Batches (Cron, ``make run``) schliesst
weiter der Batch selbst ab.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError

from src.db.recorder import BatchRecorder
from va_contracts import Envelope, new_envelope, parse_envelope
from va_contracts.events.v1 import (
    REASON_NO_DATA,
    REPORT_SENT,
    RUN_FAILED,
    RUN_REQUESTED,
    SCORING_RUN_COMPLETED,
    SNAPSHOT_COMPLETED,
    FundamentalsV1,
    IdentityV1,
    RankingRowV1,
    ReportSentV1,
    RunFailedV1,
    RunOptionsV1,
    ScoringRunCompletedV1,
    SnapshotCompletedV1,
    UniverseInfoV1,
)
from va_platform import tracing
from va_web_api.events import EventManager
from va_web_api.ports import RunActive
from va_web_api.projections import register
from va_web_api.runs import RunManager, WatchdogLimits

LIMITS = WatchdogLimits(
    fetch=timedelta(minutes=45), scoring=timedelta(minutes=5), report=timedelta(minutes=5)
)
UNIVERSE = UniverseInfoV1(source="iShares", as_of=date(2026, 11, 6), size=3)


class Clock:
    """Steuerbare Uhr: startet bei der echten Zeit, damit sie zu ``now()`` der Datenbank passt."""

    def __init__(self) -> None:
        self.now = datetime.now(UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs: float) -> datetime:
        self.now += timedelta(**kwargs)
        return self.now


class Sink:
    """Nimmt die Events aus der Outbox entgegen, wie der NatsBus."""

    def __init__(self) -> None:
        self.sent: list[Envelope[Any]] = []

    def __call__(self, envelope: Envelope[Any]) -> None:
        self.sent.append(envelope)


class Broadcast:
    def publish(self, message: Any) -> None:
        pass


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def manager(web_engine: Engine, clock: Clock) -> RunManager:
    return RunManager(web_engine, version="9.9.9", limits=LIMITS, clock=clock)


@pytest.fixture
def events(web_engine: Engine) -> EventManager:
    events = EventManager(web_engine, Broadcast())
    register(events)
    return events


def _rows(engine: Engine, sql: str, **params: Any) -> list[Any]:
    with engine.connect() as conn:
        return list(conn.execute(text(sql), params).all())


def _run(engine: Engine, run_id: int) -> Any:
    [row] = _rows(engine, "SELECT * FROM batch.run WHERE id = :id", id=run_id)
    return row


def _outbox(engine: Engine) -> list[Envelope[Any]]:
    rows = _rows(engine, "SELECT payload::text FROM web.outbox ORDER BY created_at, id")
    return [parse_envelope(payload.encode()) for (payload,) in rows]


def _at(envelope: Envelope[Any], when: datetime) -> Envelope[Any]:
    return envelope.model_copy(update={"time": when})


def _fund(symbol: str) -> FundamentalsV1:
    return FundamentalsV1(identity=IdentityV1(symbol=symbol, name=f"{symbol} AG", index="DAX"))


def _snapshot(run_id: int, when: datetime, trigger: str = "manual") -> Envelope[Any]:
    data = SnapshotCompletedV1(
        run_id=run_id,
        trigger=trigger,  # type: ignore[arg-type]
        options=RunOptionsV1(),
        fetch_run_id=10,
        as_of=date(2026, 11, 7),
        success_share=1.0,
        universe=UNIVERSE,
        fundamentals=[_fund("A"), _fund("B"), _fund("C")],
    )
    return _at(new_envelope(SNAPSHOT_COMPLETED, data, source="va/test"), when)


def _scored(run_id: int, when: datetime, *, scored: int = 3) -> Envelope[Any]:
    rows = [
        RankingRowV1(
            fundamentals=_fund(symbol),
            rank_overall=rank,
            composite_score=1 - rank / 10 if rank <= scored else None,
        )
        for rank, symbol in enumerate("ABC", start=1)
    ]
    data = ScoringRunCompletedV1(
        run_id=run_id,
        trigger="manual",
        options=RunOptionsV1(),
        scoring_run_id=20,
        fetch_run_id=10,
        as_of=date(2026, 11, 7),
        universe=UNIVERSE,
        value_weight=0.6,
        quality_weight=0.4,
        ranking=rows,
    )
    return _at(new_envelope(SCORING_RUN_COMPLETED, data, source="va/test"), when)


def _sent(run_id: int, when: datetime) -> Envelope[Any]:
    data = ReportSentV1(run_id=run_id, report_id=30, subject="[ok]", dry_run=False)
    return _at(new_envelope(REPORT_SENT, data, source="va/test"), when)


def _failed(run_id: int, when: datetime, reason: str, detail: str | None = None) -> Envelope[Any]:
    data = RunFailedV1(
        run_id=run_id,
        trigger="manual",
        options=RunOptionsV1(),
        stage="market-data",
        reason=reason,
        detail=detail,
    )
    return _at(new_envelope(RUN_FAILED, data, source="va/test"), when)


class TestStart:
    def test_a_start_creates_the_run_and_the_event(self, manager, engine, clock):
        run_id = manager.start(RunOptionsV1(dry_run=True, notify=False))

        run = _run(engine, run_id)
        assert (run.kind, run.status, run.app_version) == ("batch", "running", "9.9.9")
        assert (run.dry_run, run.force_refresh, run.finished_at) == (True, False, None)
        assert run.started_at == clock.now

        [request] = _rows(engine, "SELECT * FROM web.run_request")
        assert (request.run_id, request.trigger, request.slot) == (run_id, "manual", None)
        assert (request.force_refresh, request.dry_run, request.notify) == (False, True, False)
        assert request.requested_at == clock.now

        [event] = _outbox(engine)
        assert event.type == RUN_REQUESTED.type
        assert event.correlationid == str(run_id)
        assert event.data.run_id == run_id
        assert event.data.trigger == "manual"
        assert event.data.options == RunOptionsV1(dry_run=True, notify=False)

    def test_a_start_opens_the_trace_of_the_run(self, manager, engine):
        """P5.5: Der Run beginnt hier; sein Event traegt den Trace-Kontext durch die Outbox."""
        exporter = InMemorySpanExporter()
        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(exporter))
        tracing.set_provider(provider)
        try:
            run_id = manager.start(RunOptionsV1())
        finally:
            tracing.set_provider(None)
        [root] = exporter.get_finished_spans()
        assert root.name == "run"
        assert root.attributes == {"va.run_id": str(run_id), "va.trigger": "manual"}
        [event] = _outbox(engine)
        assert event.traceparent is not None
        assert root.context is not None
        assert event.traceparent.split("-")[1] == f"{root.context.trace_id:032x}"

    def test_pending_events_go_out_once(self, manager, engine):
        run_id = manager.start(RunOptionsV1())
        sink = Sink()
        assert manager.publish_pending(sink) == 1
        assert manager.publish_pending(sink) == 0
        assert [env.data.run_id for env in sink.sent] == [run_id]
        [(published,)] = _rows(engine, "SELECT published_at FROM web.outbox")
        assert published is not None

    def test_a_manual_start_waits_for_the_open_run(self, manager, events, clock):
        first = manager.start(RunOptionsV1())
        with pytest.raises(RunActive) as error:
            manager.start(RunOptionsV1())
        assert error.value.run_id == first

        events.dispatch(_failed(first, clock.advance(minutes=1), "Yahoo weg"))
        assert manager.start(RunOptionsV1()) > first

    def test_a_running_batch_also_blocks(self, manager, app_engine):
        batch_run = BatchRecorder(app_engine).start_run(
            kind="batch", dry_run=False, force_refresh=False, universe_mode="ALL", settings=None
        )
        with pytest.raises(RunActive) as error:
            manager.start(RunOptionsV1())
        assert error.value.run_id == batch_run

    def test_a_batch_run_that_never_finished_does_not_block_forever(
        self, manager, app_engine, clock
    ):
        BatchRecorder(app_engine).start_run(
            kind="batch", dry_run=False, force_refresh=False, universe_mode="ALL", settings=None
        )
        clock.advance(minutes=LIMITS.total.total_seconds() / 60 + 1)
        assert manager.start(RunOptionsV1()) > 0


class TestSchedule:
    def test_the_same_slot_creates_one_run(self, manager, engine):
        slot = datetime(2026, 11, 7, 6, 30, tzinfo=UTC)
        run_id = manager.schedule(slot)
        assert run_id is not None
        assert manager.schedule(slot) is None

        assert len(_rows(engine, "SELECT id FROM batch.run")) == 1
        [request] = _rows(engine, "SELECT trigger, slot FROM web.run_request")
        assert tuple(request) == ("scheduled", slot)
        [event] = _outbox(engine)
        assert (event.data.run_id, event.data.trigger) == (run_id, "scheduled")
        assert event.data.options == RunOptionsV1()

    def test_the_next_slot_is_a_new_run(self, manager):
        slot = datetime(2026, 11, 7, 6, 30, tzinfo=UTC)
        first = manager.schedule(slot)
        second = manager.schedule(slot + timedelta(days=7))
        assert first is not None
        assert second is not None
        assert second != first

    def test_an_open_run_does_not_stop_the_schedule(self, manager):
        manager.start(RunOptionsV1())
        assert manager.schedule(datetime(2026, 11, 7, 6, 30, tzinfo=UTC)) is not None


class TestWatchdog:
    def test_nothing_happens_before_the_limit(self, manager, engine, clock):
        manager.start(RunOptionsV1())
        clock.advance(minutes=44)
        assert manager.check() == []
        assert len(_outbox(engine)) == 1

    def test_a_hanging_fetch_fails_the_run(self, manager, engine, clock):
        run_id = manager.start(RunOptionsV1(dry_run=True))
        clock.advance(minutes=46)
        assert manager.check() == [run_id]

        _, failure = _outbox(engine)
        assert failure.type == RUN_FAILED.type
        assert failure.correlationid == str(run_id)
        assert (failure.data.run_id, failure.data.trigger) == (run_id, "manual")
        assert (failure.data.stage, failure.data.reason) == ("watchdog", "timeout")
        assert failure.data.options == RunOptionsV1(dry_run=True)
        assert "Abruf" in (failure.data.detail or "")

        [status] = _rows(engine, "SELECT status, error FROM web.run_status")
        assert tuple(status) == ("failed", "timeout")
        run = _run(engine, run_id)
        assert (run.status, run.exit_code) == ("failed", 1)
        assert run.finished_at == clock.now
        assert "Abruf" in run.error

    def test_a_run_is_reported_once(self, manager, engine, clock):
        manager.start(RunOptionsV1())
        clock.advance(minutes=46)
        assert len(manager.check()) == 1
        clock.advance(minutes=10)
        assert manager.check() == []
        assert len(_outbox(engine)) == 2

    def test_each_stage_has_its_own_limit(self, manager, events, engine, clock):
        run_id = manager.start(RunOptionsV1())
        events.dispatch(_snapshot(run_id, clock.advance(minutes=42)))
        clock.advance(minutes=4)  # 46 min nach dem Start, aber erst 4 min nach dem Abruf
        assert manager.check() == []
        clock.advance(minutes=2)
        assert manager.check() == [run_id]
        failure = _outbox(engine)[-1]
        assert "Bewertung" in (failure.data.detail or "")

    def test_the_mail_stage(self, manager, events, engine, clock):
        run_id = manager.start(RunOptionsV1())
        events.dispatch(_snapshot(run_id, clock.advance(minutes=10)))
        events.dispatch(_scored(run_id, clock.advance(minutes=1)))
        clock.advance(minutes=6)
        assert manager.check() == [run_id]
        assert "Mail" in (_outbox(engine)[-1].data.detail or "")

    def test_finished_runs_and_batch_runs_are_left_alone(self, manager, events, app_engine, clock):
        run_id = manager.start(RunOptionsV1())
        events.dispatch(_failed(run_id, clock.advance(minutes=1), "Yahoo weg"))
        BatchRecorder(app_engine).start_run(
            kind="batch", dry_run=False, force_refresh=False, universe_mode="ALL", settings=None
        )
        clock.advance(hours=3)
        assert manager.check() == []

    def test_the_failure_coming_back_changes_nothing(self, manager, events, engine, clock):
        run_id = manager.start(RunOptionsV1())
        clock.advance(minutes=46)
        manager.check()
        before = _run(engine, run_id)
        sink = Sink()
        manager.publish_pending(sink)
        for envelope in sink.sent:  # ueber NATS kommen beide Events zurueck
            events.dispatch(envelope)
        assert _run(engine, run_id) == before
        [status] = _rows(engine, "SELECT status, error FROM web.run_status")
        assert tuple(status) == ("failed", "timeout")


class TestFinish:
    def test_a_report_finishes_the_run(self, manager, events, engine, clock):
        run_id = manager.start(RunOptionsV1())
        for env in (
            _snapshot(run_id, clock.advance(minutes=10)),
            _scored(run_id, clock.advance(minutes=1), scored=2),
            _sent(run_id, clock.advance(minutes=1)),
        ):
            events.dispatch(env)
        run = _run(engine, run_id)
        assert (run.status, run.exit_code, run.error) == ("partial", 0, None)
        assert (run.fetch_run_id, run.scoring_run_id, run.report_id) == (10, 20, 30)
        assert (run.universe_size, run.scored_count, run.failed_count) == (3, 2, 1)
        assert run.finished_at is not None

    def test_all_scored_is_a_success(self, manager, events, engine, clock):
        run_id = manager.start(RunOptionsV1())
        events.dispatch(_scored(run_id, clock.advance(minutes=1)))
        events.dispatch(_sent(run_id, clock.advance(minutes=1)))
        run = _run(engine, run_id)
        assert (run.status, run.scored_count, run.failed_count) == ("success", 3, 0)

    def test_no_data(self, manager, events, engine, clock):
        run_id = manager.start(RunOptionsV1())
        events.dispatch(_snapshot(run_id, clock.advance(minutes=10)))
        events.dispatch(_failed(run_id, clock.advance(minutes=1), REASON_NO_DATA))
        run = _run(engine, run_id)
        assert (run.status, run.exit_code, run.error) == ("no_data", 3, None)
        assert (run.scored_count, run.failed_count) == (0, 3)

    def test_a_failure_keeps_its_detail(self, manager, events, engine, clock):
        run_id = manager.start(RunOptionsV1())
        events.dispatch(_failed(run_id, clock.advance(minutes=1), "Yahoo weg", "Traceback …"))
        run = _run(engine, run_id)
        assert (run.status, run.exit_code, run.error) == ("failed", 1, "Traceback …")

    def test_the_first_result_stays(self, manager, events, engine, clock):
        """``batch.run`` wird nur einmal abgeschlossen; der spaete Fehlschlag steht im Status."""
        run_id = manager.start(RunOptionsV1())
        events.dispatch(_scored(run_id, clock.advance(minutes=1)))
        events.dispatch(_sent(run_id, clock.advance(minutes=1)))
        events.dispatch(_failed(run_id, clock.advance(minutes=1), "spaet"))
        assert _run(engine, run_id).status == "success"
        [(status,)] = _rows(engine, "SELECT status FROM web.run_status")
        assert status == "failed"

    def test_batch_runs_finish_themselves(self, events, engine, app_engine, clock):
        run_id = BatchRecorder(app_engine).start_run(
            kind="batch", dry_run=False, force_refresh=False, universe_mode="ALL", settings=None
        )
        events.dispatch(_scored(run_id, clock.advance(minutes=1)))
        events.dispatch(_sent(run_id, clock.advance(minutes=1)))
        run = _run(engine, run_id)
        assert (run.status, run.finished_at) == ("running", None)


class TestRights:
    def test_the_web_role_cannot_delete_runs(self, manager, web_engine):
        run_id = manager.start(RunOptionsV1())
        with pytest.raises(DBAPIError), web_engine.begin() as conn:
            conn.execute(text("DELETE FROM batch.run WHERE id = :id"), {"id": run_id})

    def test_a_run_is_finished_only_once(self, manager, events, web_engine, clock):
        run_id = manager.start(RunOptionsV1())
        events.dispatch(_failed(run_id, clock.advance(minutes=1), "Yahoo weg"))
        with pytest.raises(DBAPIError, match="abgeschlossen"), web_engine.begin() as conn:
            conn.execute(
                text("UPDATE batch.run SET status = 'success', finished_at = now() WHERE id = :id"),
                {"id": run_id},
            )

    def test_only_the_finish_columns_are_writable(self, manager, web_engine):
        run_id = manager.start(RunOptionsV1())
        with pytest.raises(DBAPIError, match="permission denied"), web_engine.begin() as conn:
            conn.execute(
                text("UPDATE batch.run SET kind = 'import', finished_at = now() WHERE id = :id"),
                {"id": run_id},
            )

    def test_requests_are_append_only(self, manager, web_engine):
        manager.start(RunOptionsV1())
        for sql in ("UPDATE web.run_request SET notify = false", "DELETE FROM web.run_request"):
            with pytest.raises(DBAPIError), web_engine.begin() as conn:
                conn.execute(text(sql))

    def test_the_web_role_sees_no_other_batch_table(self, web_engine):
        with pytest.raises(DBAPIError, match="permission denied"), web_engine.connect() as conn:
            conn.execute(text("SELECT * FROM batch.run_log"))
