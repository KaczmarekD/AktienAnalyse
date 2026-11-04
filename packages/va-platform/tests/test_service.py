"""Gemeinsames der Services (P5.1a): ``run_service``, ``run_failure`` und ``LocalCaller``.

``run_service`` startet den Bus, ruft die Verdrahtung des Service auf und laeuft bis zum
Stopp-Event; ein Dead Letter wird zu ``screening.run.failed``. ``LocalCaller`` beantwortet
Request/Reply im selben Prozess mit denselben Handlern wie ``NatsBus.serve``. Die Tests mit NATS
brauchen ``TEST_NATS_URL``.
"""

from __future__ import annotations

import threading
import time
from typing import Any

import pytest

from va_contracts import Envelope, new_envelope
from va_contracts.events.v1 import (
    PROFILE_SAVED,
    RUN_FAILED,
    RUN_REQUESTED,
    ProfileSavedV1,
    RunOptionsV1,
    ScreeningRunRequestedV1,
)
from va_contracts.rpc.v1 import (
    PROFILE_ACTIVATE,
    PROFILE_SAVE,
    ActivateReplyV1,
    ActivateRequestV1,
)
from va_platform.bus import DeadLetter
from va_platform.nats import NatsBus, RpcUnavailable
from va_platform.service import LocalCaller, ServiceSettings, run_failure, run_service


def _request(run_id: int = 4) -> Envelope[ScreeningRunRequestedV1]:
    data = ScreeningRunRequestedV1(
        run_id=run_id, trigger="manual", options=RunOptionsV1(dry_run=True)
    )
    return new_envelope(RUN_REQUESTED, data, source="va/test", correlationid=str(run_id))


class TestRunFailure:
    def test_a_dead_letter_fails_its_run(self):
        dead = DeadLetter("market-data", _request(), 5, RuntimeError("Bug"))
        failure = run_failure(dead, source="va/market-data")
        assert failure is not None
        assert (failure.data.run_id, failure.data.trigger) == (4, "manual")
        assert failure.data.options == RunOptionsV1(dry_run=True)
        assert (failure.data.stage, failure.data.reason) == ("market-data", "market-data: Bug")
        assert failure.correlationid == "4"

    def test_no_failure_without_a_run(self):
        env = new_envelope(PROFILE_SAVED, ProfileSavedV1(profile_id=1, version=2), source="x")
        assert run_failure(DeadLetter("web-api", env, 5, RuntimeError()), source="x") is None


class TestLocalCaller:
    def test_answers_like_serve(self):
        caller = LocalCaller({PROFILE_ACTIVATE: lambda request: ActivateReplyV1()})
        reply = caller.call(PROFILE_ACTIVATE, ActivateRequestV1(profile_id=1, version=2))
        assert reply == ActivateReplyV1()

    def test_an_exception_is_internal(self):
        def boom(request: ActivateRequestV1) -> ActivateReplyV1:
            msg = "Datenbank weg"
            raise RuntimeError(msg)

        reply = LocalCaller({PROFILE_ACTIVATE: boom}).call(
            PROFILE_ACTIVATE, ActivateRequestV1(profile_id=1, version=2)
        )
        assert reply.error is not None
        assert reply.error.code == "internal"
        assert "Datenbank weg" in reply.error.message

    def test_an_unknown_command_has_no_responder(self):
        with pytest.raises(RpcUnavailable):
            LocalCaller({}).call(PROFILE_SAVE, object())  # type: ignore[arg-type]


class TestRunService:
    def test_runs_until_stopped_and_reports_dead_letters(self, nats_url, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://x:x@127.0.0.1:1/none")
        settings = ServiceSettings(nats_url=nats_url)  # type: ignore[call-arg]
        stop = threading.Event()
        ready = threading.Event()
        calls: list[Envelope[Any]] = []

        def setup(bus: NatsBus, engine: Any) -> None:
            def broken(env: Envelope[Any]) -> None:
                calls.append(env)
                msg = "Bug im Handler"
                raise RuntimeError(msg)

            bus.subscribe(RUN_REQUESTED, "market-data", broken)
            ready.set()

        service = threading.Thread(
            target=run_service,
            kwargs={
                "name": "market-data",
                "settings": settings,
                "setup": setup,
                "stop": stop,
                "max_deliver": 1,
            },
            daemon=True,
        )
        service.start()
        probe = NatsBus(nats_url)
        probe.start()
        failures: list[Envelope[Any]] = []
        try:
            probe.subscribe(RUN_FAILED, "svc-probe", failures.append)
            assert ready.wait(20)
            probe.publish(_request())
            deadline = time.monotonic() + 20
            while not failures and time.monotonic() < deadline:
                time.sleep(0.05)
        finally:
            stop.set()
            service.join(timeout=30)
            probe.close()

        assert not service.is_alive()
        assert len(calls) == 1
        [failure] = failures
        assert (failure.data.run_id, failure.data.stage) == (4, "market-data")
        assert failure.source == "va/market-data"

    def test_without_nats_it_does_not_start(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://x:x@127.0.0.1:1/none")
        settings = ServiceSettings(nats_url=None)  # type: ignore[call-arg]
        with pytest.raises(ValueError, match="NATS_URL"):
            run_service(
                name="scoring",
                settings=settings,
                setup=lambda bus, engine: None,
                stop=threading.Event(),
            )
