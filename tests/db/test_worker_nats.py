"""Der Worker mit dem web-api (P4.7, P4.8): NATS und Datenbank sind echt.

- Das web-api legt einen Run an und schickt ``screening.run.requested`` aus seiner Outbox. Der
  Worker fuehrt die Kette mit der Replay-Fixture aus, der Eventmanager schliesst ``batch.run`` ab.
- Profil-Befehle ueber NATS: Der Worker speichert und meldet ``scoring.profile.saved`` bzw.
  ``.activated``, der Eventmanager reicht sie an die offenen Tabs weiter (Topic ``profiles``).

Ohne ``TEST_DATABASE_URL`` oder ``TEST_NATS_URL`` uebersprungen.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from typing import Any
from unittest.mock import Mock

from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Engine, text
from sqlalchemy.engine import make_url

from src.composition import build_adapters
from src.web import create_app
from src.worker import serve
from tests.db.conftest import ROLE_PASSWORDS, _url_for
from tests.db.test_replay_run_db import _replay_run
from va_contracts.events.v1 import RunOptionsV1
from va_contracts.profile import ProfileParamsV1
from va_platform.nats import NatsBus
from va_web_api.events import open_event_consumer
from va_web_api.ports import ScoringUnavailable
from va_web_api.rpc import RemoteScoring
from va_web_api.runs import RunManager, WatchdogLimits
from va_web_api.settings import WebApiSettings

FIXTURE = Path(__file__).parents[1] / "fixtures" / "replay" / "2026-10-30_scoring-run-1.json"
TIMEOUT = 120.0


class Broadcast:
    def publish(self, message: Any) -> None:
        pass


@contextmanager
def _web_client(db_settings, nats_url: str | None = None) -> Iterator[TestClient]:
    """Das web-api: ohne ``nats_url`` aus den Tabellen, mit aus Projektionen und NATS."""
    database = make_url(db_settings.database_url.get_secret_value()).database
    assert database
    read = _url_for(database, "va_read", ROLE_PASSWORDS["va_read"])
    web = _url_for(database, "va_web", ROLE_PASSWORDS["va_web"])
    settings = WebApiSettings(
        database_url=SecretStr(read),
        nats_url=nats_url,
        projections_database_url=None if nats_url is None else SecretStr(web),
    )
    with TestClient(create_app(settings)) as client:
        if nats_url is not None:
            deadline = time.monotonic() + 30
            while client.app.state.events is None:  # type: ignore[attr-defined]
                assert time.monotonic() < deadline, "Event-Consumer startet nicht"
                time.sleep(0.1)
        yield client


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


class Recorder:
    def __init__(self) -> None:
        self.messages: list[Any] = []

    def publish(self, message: Any) -> None:
        self.messages.append(message)


def _answers(scoring: RemoteScoring) -> bool:
    try:
        scoring.factors()
    except ScoringUnavailable:
        return False
    return True


def test_profile_commands_over_nats_reach_the_open_tabs(db_settings, engine, web_engine, nats_url):
    settings = db_settings.model_copy(update={"replay_source": FIXTURE, "smtp_plain": True})
    rc, _ = _replay_run(settings)  # legt das Profil "Standard" v1 an
    assert rc == 0
    with engine.connect() as conn:
        profile_id = conn.execute(text("SELECT id FROM scoring.profile")).scalar_one()

    stop = threading.Event()
    nats_settings = settings.model_copy(update={"event_bus": "nats", "nats_url": nats_url})
    worker = threading.Thread(target=serve, args=(nats_settings, stop), daemon=True)
    worker.start()
    recorder = Recorder()
    consumer = open_event_consumer(nats_url, web_engine, recorder)
    client = NatsBus(nats_url)
    client.start()
    try:
        scoring = RemoteScoring(lambda: client)
        deadline = time.monotonic() + 60
        while not _answers(scoring):
            assert time.monotonic() < deadline, "Worker antwortet nicht"
            time.sleep(0.2)

        params = ProfileParamsV1(value_weight=0.5)
        version = scoring.save_version(profile_id, params, based_on=1, comment="P4.8")
        scoring.activate(profile_id, version)

        deadline = time.monotonic() + 30
        while len([m for m in recorder.messages if m.topic == "profiles"]) < 2:
            assert time.monotonic() < deadline, "Profil-Events nicht angekommen"
            time.sleep(0.1)
    finally:
        client.close()
        consumer.close()
        stop.set()
        worker.join(timeout=60)

    assert version == 2
    with engine.connect() as conn:
        active = conn.execute(
            text("SELECT version FROM scoring.profile_activation ORDER BY id DESC LIMIT 1")
        ).scalar_one()
    assert active == 2
    profiles = sorted(m.type for m in recorder.messages if m.topic == "profiles")
    assert profiles == ["scoring.profile.activated", "scoring.profile.saved"]


def _without_times(value: Any) -> Any:
    """Der Zeitpunkt des Bewertungslaufs kommt aus dem Event, nicht aus ``scoring_run``."""
    if isinstance(value, dict):
        return {k: _without_times(v) for k, v in value.items() if k != "created_at"}
    if isinstance(value, list):
        return [_without_times(v) for v in value]
    return value


def test_projections_from_events_answer_like_the_tables(db_settings, engine, web_engine, nats_url):
    """P4.9: Ein Lauf ueber NATS fuellt die Projektionen; REST antwortet wie aus den Tabellen."""
    settings = db_settings.model_copy(
        update={
            "replay_source": FIXTURE,
            "smtp_plain": True,
            "event_bus": "nats",
            "nats_url": nats_url,
        }
    )
    adapters = replace(
        build_adapters(settings),
        sender=Mock(send=Mock()),
        heartbeat=Mock(ping=Mock(return_value=None)),
    )
    stop = threading.Event()
    worker = threading.Thread(
        target=serve, args=(settings, stop), kwargs={"adapters": adapters}, daemon=True
    )
    worker.start()
    try:
        with _web_client(db_settings, nats_url) as projections, _web_client(db_settings) as tables:
            runs = projections.app.state.runs  # type: ignore[attr-defined]
            run_id = runs.start(RunOptionsV1())
            deadline = time.monotonic() + TIMEOUT
            while _finished(engine, run_id) is None and time.monotonic() < deadline:
                time.sleep(0.5)
            assert _finished(engine, run_id) is not None, "Run nicht abgeschlossen"

            ranking = tables.get("/api/v1/ranking/latest").json()
            assert len(ranking["rows"]) == 90
            assert _without_times(projections.get("/api/v1/ranking/latest").json()) == (
                _without_times(ranking)
            )
            for row in ranking["rows"][::9]:
                path = f"/api/v1/instruments/{row['symbol']}"
                assert _without_times(projections.get(path).json()) == _without_times(
                    tables.get(path).json()
                )
            detail = projections.get(f"/api/v1/runs/{run_id}").json()
            assert detail == tables.get(f"/api/v1/runs/{run_id}").json()
    finally:
        stop.set()
        worker.join(timeout=60)
