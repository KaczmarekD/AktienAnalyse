"""``EventManager`` und Projektionen des web-api (P4.4) gegen ein echtes PostgreSQL.

Der Eventmanager schreibt Inbox-Eintrag und Projektionen in einer Transaktion (Schema ``web``)
und meldet erst nach dem Commit an den ``Broadcaster``. Der ist hier ein Fake, der beim Melden
mit einer zweiten Verbindung nachsieht, was schon sichtbar ist.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError, ProgrammingError

from va_contracts import Envelope, new_envelope
from va_contracts.events.v1 import (
    PROFILE_SAVED,
    REASON_NO_DATA,
    REPORT_SENT,
    RUN_FAILED,
    RUN_REQUESTED,
    SCORING_RUN_COMPLETED,
    SNAPSHOT_COMPLETED,
    FundamentalsV1,
    IdentityV1,
    ProfileSavedV1,
    RankingRowV1,
    ReportSentV1,
    RunFailedV1,
    RunOptionsV1,
    ScoringRunCompletedV1,
    ScreeningRunRequestedV1,
    SnapshotCompletedV1,
    UniverseInfoV1,
)
from va_web_api.events import EventManager, EventMessage
from va_web_api.projections import register

OPTIONS = RunOptionsV1()
UNIVERSE = UniverseInfoV1(source="iShares", as_of=date(2026, 10, 16), size=3)


def _env(spec: Any, data: Any) -> Envelope[Any]:
    return new_envelope(spec, data, source="va/test")


def _requested(run_id: int = 1) -> Envelope[Any]:
    data = ScreeningRunRequestedV1(run_id=run_id, trigger="scheduled", options=OPTIONS)
    return _env(RUN_REQUESTED, data)


def _fund(symbol: str) -> FundamentalsV1:
    return FundamentalsV1(identity=IdentityV1(symbol=symbol, name=f"{symbol} AG", index="DAX"))


def _snapshot() -> Envelope[Any]:
    data = SnapshotCompletedV1(
        run_id=1,
        trigger="scheduled",
        options=OPTIONS,
        fetch_run_id=10,
        as_of=date(2026, 10, 17),
        success_share=1.0,
        universe=UNIVERSE,
        fundamentals=[_fund("A"), _fund("B"), _fund("C")],
    )
    return _env(SNAPSHOT_COMPLETED, data)


def _completed(run_id: int | None = 1, trigger: str = "scheduled") -> Envelope[Any]:
    data = ScoringRunCompletedV1(
        run_id=run_id,
        trigger=trigger,  # type: ignore[arg-type]
        options=OPTIONS,
        scoring_run_id=20,
        fetch_run_id=10,
        as_of=date(2026, 10, 17),
        universe=UNIVERSE,
        value_weight=0.6,
        quality_weight=0.4,
        ranking=[
            RankingRowV1(
                fundamentals=_fund("A"),
                rank_overall=1,
                value_score=0.9,
                quality_score=0.8,
                composite_score=0.86,
            ),
            RankingRowV1(
                fundamentals=_fund("B"),
                rank_overall=2,
                value_score=0.95,
                quality_score=0.1,
                composite_score=0.61,
                value_trap_flag=True,
            ),
            RankingRowV1(fundamentals=_fund("C"), rank_overall=3),  # ohne Composite
        ],
    )
    return _env(SCORING_RUN_COMPLETED, data)


def _sent() -> Envelope[Any]:
    return _env(REPORT_SENT, ReportSentV1(run_id=1, report_id=30, subject="[ok]", dry_run=False))


def _failed(reason: str = "Yahoo weg") -> Envelope[Any]:
    data = RunFailedV1(
        run_id=1, trigger="scheduled", options=OPTIONS, stage="market-data", reason=reason
    )
    return _env(RUN_FAILED, data)


class Recorder:
    """``Broadcaster``: merkt sich die Meldungen und was eine zweite Verbindung dann sieht."""

    def __init__(self, engine: Engine, *, fail: bool = False) -> None:
        self.engine = engine
        self.fail = fail
        self.messages: list[EventMessage] = []
        self.visible: list[int] = []

    def publish(self, message: EventMessage) -> None:
        with self.engine.connect() as conn:
            self.visible.append(
                conn.execute(text("SELECT count(*) FROM web.run_status")).scalar_one()
            )
        self.messages.append(message)
        if self.fail:
            msg = "WebSocket-Hub kaputt"
            raise RuntimeError(msg)


def _manager(engine: Engine, recorder: Recorder) -> EventManager:
    manager = EventManager(engine, recorder)
    register(manager)
    return manager


def _rows(engine: Engine, sql: str) -> list[Any]:
    with engine.connect() as conn:
        return list(conn.execute(text(sql)).all())


def _status(engine: Engine) -> Any:
    [row] = _rows(engine, "SELECT * FROM web.run_status")
    return row


class TestDispatch:
    def test_broadcast_comes_after_the_commit(self, engine):
        recorder = Recorder(engine)
        assert _manager(engine, recorder).dispatch(_requested(), seq=42) is True
        assert [(m.topic, m.type, m.seq) for m in recorder.messages] == [
            ("runs", RUN_REQUESTED.type, 42)
        ]
        assert recorder.visible == [1]  # beim Melden schon committet
        assert recorder.messages[0].data["run_id"] == 1

    def test_failing_projection_rolls_back_and_raises(self, engine):
        recorder = Recorder(engine)
        manager = _manager(engine, recorder)

        @manager.projection(RUN_REQUESTED)
        def broken(session: Any, env: Envelope[Any]) -> None:
            msg = "Projektion kaputt"
            raise RuntimeError(msg)

        with pytest.raises(RuntimeError, match="Projektion kaputt"):
            manager.dispatch(_requested())
        assert recorder.messages == []
        assert _rows(engine, "SELECT run_id FROM web.run_status") == []
        assert _rows(engine, "SELECT message_id FROM web.inbox") == []

    def test_redelivery_changes_nothing(self, engine):
        recorder = Recorder(engine)
        manager = _manager(engine, recorder)
        request = _requested()
        assert manager.dispatch(request) is True
        before = _status(engine)
        assert manager.dispatch(request) is False
        assert len(recorder.messages) == 1
        assert _status(engine) == before

    def test_broadcast_failure_keeps_the_event(self, engine):
        recorder = Recorder(engine, fail=True)
        assert _manager(engine, recorder).dispatch(_requested()) is True
        assert _status(engine).status == "requested"
        assert len(_rows(engine, "SELECT message_id FROM web.inbox")) == 1


class TestRunStatus:
    def test_follows_the_chain(self, engine):
        manager = _manager(engine, Recorder(engine))
        for env in (_requested(), _snapshot(), _completed(), _sent()):
            manager.dispatch(env)
        row = _status(engine)
        assert (row.run_id, row.status, row.trigger) == (1, "reported", "scheduled")
        assert (row.fetch_run_id, row.scoring_run_id, row.report_id) == (10, 20, 30)
        assert (row.universe_size, row.scored_count) == (3, 2)
        assert row.error is None
        assert row.last_event_type == REPORT_SENT.type

    def test_failure_wins_over_a_later_report(self, engine):
        manager = _manager(engine, Recorder(engine))
        for env in (_requested(), _failed("Yahoo weg"), _sent()):
            manager.dispatch(env)
        row = _status(engine)
        assert (row.status, row.error) == ("failed", "Yahoo weg")

    def test_no_data(self, engine):
        manager = _manager(engine, Recorder(engine))
        manager.dispatch(_requested())
        manager.dispatch(_failed(REASON_NO_DATA))
        assert _status(engine).status == "no_data"

    def test_an_event_without_request_starts_the_row(self, engine):
        """Das web-api kann mitten in einem Lauf starten."""
        manager = _manager(engine, Recorder(engine))
        manager.dispatch(_snapshot())
        row = _status(engine)
        assert (row.run_id, row.status, row.fetch_run_id) == (1, "fetched", 10)


class TestRanking:
    def test_scoring_completed_writes_the_ranking(self, engine):
        recorder = Recorder(engine)
        _manager(engine, recorder).dispatch(_completed())
        rows = _rows(
            engine,
            "SELECT scoring_run_id, run_id, symbol, name, index, rank_overall, composite_score, "
            "value_score, quality_score, value_trap FROM web.ranking_row ORDER BY rank_overall",
        )
        assert [tuple(r) for r in rows] == [
            (20, 1, "A", "A AG", "DAX", 1, 0.86, 0.9, 0.8, False),
            (20, 1, "B", "B AG", "DAX", 2, 0.61, 0.95, 0.1, True),
            (20, 1, "C", "C AG", "DAX", 3, None, None, None, False),
        ]
        assert [m.topic for m in recorder.messages] == ["runs", "ranking"]

    def test_rescore_has_a_ranking_but_no_run(self, engine):
        recorder = Recorder(engine)
        _manager(engine, recorder).dispatch(_completed(run_id=None, trigger="rescore"))
        assert len(_rows(engine, "SELECT symbol FROM web.ranking_row")) == 3
        assert _rows(engine, "SELECT run_id FROM web.run_status") == []
        assert [m.topic for m in recorder.messages] == ["ranking"]

    def test_profile_events_only_notify(self, engine):
        recorder = Recorder(engine)
        env = _env(PROFILE_SAVED, ProfileSavedV1(profile_id=1, version=2))
        assert _manager(engine, recorder).dispatch(env) is True
        assert [m.topic for m in recorder.messages] == ["profiles"]


def _exec(engine: Engine, sql: str) -> None:
    with engine.begin() as conn:
        conn.execute(text(sql))


class TestProtectionAndRoles:
    def test_ranking_and_inbox_are_append_only(self, engine):
        _manager(engine, Recorder(engine)).dispatch(_completed())
        for sql in (
            "UPDATE web.ranking_row SET rank_overall = 9",
            "DELETE FROM web.ranking_row",
            "DELETE FROM web.inbox",
            "UPDATE web.inbox SET consumer = 'x'",
        ):
            with pytest.raises(DBAPIError, match="verboten"):
                _exec(engine, sql)

    def test_run_status_may_change_but_not_vanish(self, engine):
        _manager(engine, Recorder(engine)).dispatch(_requested())
        _exec(engine, "UPDATE web.run_status SET status = 'fetched'")
        with pytest.raises(DBAPIError, match="verboten"):
            _exec(engine, "DELETE FROM web.run_status")

    def test_web_role_writes_only_into_web(self, engine, web_engine):
        recorder = Recorder(engine)
        for env in (_requested(), _completed()):
            _manager(web_engine, recorder).dispatch(env)
        assert _status(engine).status == "scored"
        with pytest.raises(ProgrammingError, match="permission denied"):
            _exec(web_engine, "SELECT count(*) FROM batch.run")

    def test_read_role_reads_web(self, engine, read_engine):
        _manager(engine, Recorder(engine)).dispatch(_requested())
        assert len(_rows(read_engine, "SELECT run_id FROM web.run_status")) == 1
        with pytest.raises(ProgrammingError, match="permission denied"):
            _exec(read_engine, "UPDATE web.run_status SET status = 'x'")
