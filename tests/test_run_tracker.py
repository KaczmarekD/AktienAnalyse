"""RunTracker: leitet aus den Events den Abschluss von ``batch.run`` ab (P1.8).

Er ist der Vorlaeufer der Run-Projektion im web-api: Er liest nur Events, keine Tabellen
der Module.
"""

from __future__ import annotations

from datetime import date

from src.run_tracker import RunTracker
from va_contracts import new_envelope
from va_contracts.events.v1 import (
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
    ScreeningRunRequestedV1,
    SnapshotCompletedV1,
    UniverseInfoV1,
)
from va_platform.bus import DeadLetter, InProcessBus

OPTIONS = RunOptionsV1()
UNIVERSE = UniverseInfoV1(source="iShares", as_of=date(2026, 10, 16), size=3)


def _fund(symbol: str) -> FundamentalsV1:
    return FundamentalsV1(identity=IdentityV1(symbol=symbol, name=symbol, index="DAX"))


def _snapshot() -> SnapshotCompletedV1:
    return SnapshotCompletedV1(
        run_id=1,
        trigger="scheduled",
        options=OPTIONS,
        fetch_run_id=10,
        as_of=date(2026, 10, 17),
        success_share=1.0,
        universe=UNIVERSE,
        fundamentals=[_fund("A"), _fund("B"), _fund("C")],
    )


def _completed(composites: tuple[float | None, ...]) -> ScoringRunCompletedV1:
    return ScoringRunCompletedV1(
        run_id=1,
        trigger="scheduled",
        options=OPTIONS,
        scoring_run_id=20,
        fetch_run_id=10,
        as_of=date(2026, 10, 17),
        universe=UNIVERSE,
        value_weight=0.6,
        quality_weight=0.4,
        ranking=[
            RankingRowV1(fundamentals=_fund(s), rank_overall=i, composite_score=c)
            for i, (s, c) in enumerate(zip("ABC", composites, strict=False), 1)
        ],
    )


def _failed(reason: str, **kw) -> RunFailedV1:
    return RunFailedV1(run_id=1, trigger="scheduled", options=OPTIONS, reason=reason, **kw)


def _tracked(*events) -> RunTracker:
    bus = InProcessBus(max_deliver=1)
    tracker = RunTracker(run_id=1)
    tracker.subscribe(bus)
    specs = {
        SnapshotCompletedV1: SNAPSHOT_COMPLETED,
        ScoringRunCompletedV1: SCORING_RUN_COMPLETED,
        ReportSentV1: REPORT_SENT,
        RunFailedV1: RUN_FAILED,
    }
    for data in events:
        bus.publish(new_envelope(specs[type(data)], data, source="va/test"))
    return tracker


def test_without_end_event_there_is_no_outcome():
    assert _tracked(_snapshot()).outcome is None


def test_complete_run_is_a_success():
    sent = ReportSentV1(run_id=1, report_id=30, subject="[ok 3/3]", dry_run=False)
    outcome = _tracked(_snapshot(), _completed((0.9, 0.5, 0.2)), sent).outcome
    assert outcome is not None
    assert outcome.exit_code == 0
    assert outcome.finish_kwargs() == {
        "status": "success",
        "exit_code": 0,
        "fetch_run_id": 10,
        "scoring_run_id": 20,
        "report_id": 30,
        "universe_size": 3,
        "scored_count": 3,
        "failed_count": 0,
        "error": None,
    }


def test_unscored_titles_make_it_partial():
    sent = ReportSentV1(run_id=1, report_id=30, subject="[partial 2/3]", dry_run=True)
    outcome = _tracked(_snapshot(), _completed((0.9, None)), sent).outcome
    assert outcome is not None
    kwargs = outcome.finish_kwargs()
    assert (kwargs["status"], kwargs["scored_count"], kwargs["failed_count"]) == ("partial", 1, 2)


def test_no_data_ends_with_code_3():
    outcome = _tracked(_snapshot(), _failed("no_data", stage="scoring", scoring_run_id=20)).outcome
    assert outcome is not None
    assert outcome.finish_kwargs() == {
        "status": "no_data",
        "exit_code": 3,
        "fetch_run_id": 10,
        "scoring_run_id": 20,
        "report_id": None,
        "universe_size": 3,
        "scored_count": 0,
        "failed_count": 3,
        "error": None,
    }


def test_failure_ends_with_code_1_and_the_details():
    outcome = _tracked(
        _snapshot(),
        _failed("smtp down", stage="notification", detail="Traceback ... OSError: smtp down"),
    ).outcome
    assert outcome is not None
    kwargs = outcome.finish_kwargs()
    assert (kwargs["status"], kwargs["exit_code"], kwargs["fetch_run_id"]) == ("failed", 1, 10)
    assert kwargs["error"] == "Traceback ... OSError: smtp down"


def test_failure_without_detail_keeps_the_reason():
    outcome = _tracked(_failed("timeout", stage="watchdog")).outcome
    assert outcome is not None
    assert outcome.finish_kwargs()["error"] == "timeout"


def test_events_of_other_runs_are_ignored():
    other = ReportSentV1(run_id=2, report_id=31, subject="x", dry_run=False)
    assert _tracked(other).outcome is None


def test_dead_letter_fails_the_run():
    tracker = RunTracker(run_id=1)
    env = new_envelope(
        RUN_REQUESTED,
        ScreeningRunRequestedV1(run_id=1, trigger="scheduled"),
        source="va/test",
    )
    tracker.on_dead_letter(DeadLetter("market-data", env, 1, RuntimeError("Bug")))
    outcome = tracker.outcome
    assert outcome is not None
    assert (outcome.status, outcome.exit_code) == ("failed", 1)
    assert "market-data" in (outcome.error or "")
    assert "Bug" in (outcome.error or "")
