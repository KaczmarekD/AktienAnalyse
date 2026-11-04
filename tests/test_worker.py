"""Dienste-Prozess ``python -m src.worker`` (P4.7) ohne NATS: Dead Letter und Einstieg.

Der Worker haengt market-data, scoring und notification dauerhaft an NATS. Scheitert ein Handler
endgueltig, meldet er ``screening.run.failed`` mit Trigger und Optionen des Events, damit das
web-api den Run abschliesst und notification die Fehlermail schickt. Den ganzen Weg mit NATS und
Datenbank prueft ``tests/db/test_worker_nats.py``.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from src.worker import main
from va_contracts import new_envelope
from va_contracts.events.v1 import (
    PROFILE_SAVED,
    RUN_FAILED,
    RUN_REQUESTED,
    SCORING_RUN_COMPLETED,
    FundamentalsV1,
    IdentityV1,
    ProfileSavedV1,
    RankingRowV1,
    RunFailedV1,
    RunOptionsV1,
    ScoringRunCompletedV1,
    ScreeningRunRequestedV1,
    UniverseInfoV1,
)
from va_platform.bus import DeadLetter
from va_platform.service import run_failure

SOURCE = "va/test"


def _dead(consumer: str, spec: Any, data: Any) -> DeadLetter:
    envelope = new_envelope(spec, data, source=SOURCE, correlationid="4")
    return DeadLetter(consumer=consumer, envelope=envelope, attempts=5, error=RuntimeError("Bug"))


def _completed(run_id: int | None, trigger: str) -> ScoringRunCompletedV1:
    fund = FundamentalsV1(identity=IdentityV1(symbol="A", name="A AG", index="DAX"))
    return ScoringRunCompletedV1(
        run_id=run_id,
        trigger=trigger,  # type: ignore[arg-type]
        options=RunOptionsV1(notify=False),
        scoring_run_id=20,
        fetch_run_id=10,
        as_of=date(2026, 11, 7),
        universe=UniverseInfoV1(source="iShares", as_of=None, size=1),
        value_weight=0.6,
        quality_weight=0.4,
        ranking=[RankingRowV1(fundamentals=fund, rank_overall=1)],
    )


class TestRunFailure:
    def test_a_dead_letter_becomes_a_failure_of_its_run(self):
        options = RunOptionsV1(dry_run=True)
        request = ScreeningRunRequestedV1(run_id=4, trigger="manual", options=options)
        dead = _dead("market-data", RUN_REQUESTED, request)

        failure = run_failure(dead, source="va/worker")

        assert failure is not None
        assert failure.type == RUN_FAILED.type
        assert (failure.source, failure.correlationid) == ("va/worker", "4")
        assert failure.causationid == dead.envelope.id
        data = failure.data
        assert isinstance(data, RunFailedV1)
        assert (data.run_id, data.trigger, data.options) == (4, "manual", options)
        assert (data.stage, data.reason) == ("market-data", "market-data: Bug")
        assert "RuntimeError" in (data.detail or "")

    def test_a_rescore_fails_without_a_run(self):
        dead = _dead("notification", SCORING_RUN_COMPLETED, _completed(None, "rescore"))
        failure = run_failure(dead, source="va/worker")
        assert failure is not None
        assert (failure.data.run_id, failure.data.trigger) == (None, "rescore")
        assert failure.data.stage == "notification"

    def test_an_unknown_consumer_is_the_watchdog(self):
        dead = _dead("batch", SCORING_RUN_COMPLETED, _completed(4, "scheduled"))
        failure = run_failure(dead, source="va/worker")
        assert failure is not None
        assert failure.data.stage == "watchdog"

    def test_a_failed_failure_is_not_reported_again(self):
        data = RunFailedV1(
            run_id=4, trigger="manual", options=RunOptionsV1(), stage="scoring", reason="x"
        )
        assert run_failure(_dead("notification", RUN_FAILED, data), source="va/worker") is None

    def test_an_event_without_a_run_is_not_reported(self):
        data = ProfileSavedV1(profile_id=1, version=2)
        assert run_failure(_dead("web-api", PROFILE_SAVED, data), source="va/worker") is None


class TestMain:
    @pytest.fixture(autouse=True)
    def _no_log_files(self, monkeypatch):
        """``setup_logging`` baute die Handler am Root-Logger fuer alle weiteren Tests um."""
        monkeypatch.setattr("src.worker.setup_logging", lambda logs_dir: None)

    def test_without_nats_the_worker_does_not_start(self, settings, monkeypatch):
        monkeypatch.setattr("src.worker.load_settings", lambda: settings)
        assert settings.nats_url is None
        assert main() == 2  # wie der Batch: Konfigurationsfehler

    def test_it_runs_until_stopped(self, settings, monkeypatch):
        """``serve`` kehrt erst mit SIGTERM (hier: dem Stopp-Event) zurueck."""
        calls: list[str] = []

        def serve(settings: Any, stop: Any, **kwargs: Any) -> None:
            calls.append(settings.nats_url)
            assert not stop.is_set()

        nats = settings.model_copy(update={"nats_url": "nats://nats:4222"})
        monkeypatch.setattr("src.worker.load_settings", lambda: nats)
        monkeypatch.setattr("src.worker.serve", serve)
        assert main() == 0
        assert calls == ["nats://nats:4222"]


@pytest.mark.parametrize("module", ["src.worker"])
def test_the_module_is_runnable(module):
    """``python -m src.worker``: Compose startet den Dienst so."""
    import importlib

    worker = importlib.import_module(module)
    assert callable(worker.main)
