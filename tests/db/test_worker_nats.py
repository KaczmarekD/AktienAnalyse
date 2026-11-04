"""Ein Run aus dem web-api, ausgefuehrt vom Worker (P4.7): NATS und Datenbank sind echt.

Das web-api legt den Run an und schickt ``screening.run.requested`` aus seiner Outbox. Der
Worker fuehrt die Kette mit der Replay-Fixture aus, der Eventmanager des web-api schliesst
``batch.run`` ab. Ohne ``TEST_DATABASE_URL`` oder ``TEST_NATS_URL`` uebersprungen.
"""

from __future__ import annotations

import threading
import time
from dataclasses import replace
from pathlib import Path
from typing import Any
from unittest.mock import Mock

from sqlalchemy import Engine, text

from src.composition import build_adapters
from src.worker import serve
from va_contracts.events.v1 import RunOptionsV1
from va_web_api.events import open_event_consumer
from va_web_api.runs import RunManager, WatchdogLimits

FIXTURE = Path(__file__).parents[1] / "fixtures" / "replay" / "2026-10-30_scoring-run-1.json"
TIMEOUT = 120.0


class Broadcast:
    def publish(self, message: Any) -> None:
        pass


def _finished(engine: Engine, run_id: int) -> Any:
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT * FROM batch.run WHERE id = :id AND finished_at IS NOT NULL"),
            {"id": run_id},
        ).one_or_none()


def test_a_run_from_the_web_api_runs_through_the_worker(db_settings, engine, web_engine, nats_url):
    settings = db_settings.model_copy(
        update={
            "replay_source": FIXTURE,
            "smtp_plain": True,
            "event_bus": "nats",
            "nats_url": nats_url,
        }
    )
    send = Mock()
    adapters = replace(
        build_adapters(settings),
        sender=Mock(send=send),
        heartbeat=Mock(ping=Mock(return_value=None)),
    )
    stop = threading.Event()
    worker = threading.Thread(
        target=serve, args=(settings, stop), kwargs={"adapters": adapters}, daemon=True
    )
    worker.start()
    consumer = open_event_consumer(nats_url, web_engine, Broadcast())
    try:
        runs = RunManager(web_engine, version="test", limits=WatchdogLimits())
        run_id = runs.start(RunOptionsV1())
        assert runs.publish_pending(consumer.publish) == 1

        deadline = time.monotonic() + TIMEOUT
        while (run := _finished(engine, run_id)) is None and time.monotonic() < deadline:
            time.sleep(0.5)
    finally:
        stop.set()
        worker.join(timeout=60)
        consumer.close()

    assert not worker.is_alive()
    assert run is not None, "Run nicht abgeschlossen"
    assert (run.status, run.exit_code) in {("success", 0), ("partial", 0)}
    assert run.report_id is not None
    assert run.scoring_run_id is not None
    send.assert_called_once()
    # Healthcheck nur fuer geplante Runs: Ein Start aus dem UI pingt nicht
    adapters.heartbeat.ping.assert_not_called()  # type: ignore[attr-defined]
