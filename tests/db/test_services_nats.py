"""Drei getrennte Services und das web-api (P5.1a): NATS und Datenbank sind echt.

Jeder Service laeuft wie in seinem eigenen Image: eigene Settings und seit P5.3 eigene Rolle
(``va_market_data``, ``va_scoring``, ``va_notification``), eigener Einstieg
(``va_<service>.entrypoints.service.setup``), ``run_service`` aus ``va_platform``. Ein Start aus
dem UI endet wie mit dem Worker. Vorschau und Report kommen per Request/Reply von scoring bzw.
notification. Ohne ``TEST_DATABASE_URL`` oder ``TEST_NATS_URL`` uebersprungen.
"""

from __future__ import annotations

import threading
import time
from dataclasses import replace
from functools import partial
from pathlib import Path
from typing import Any
from unittest.mock import Mock

from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.engine import make_url

from tests.db.conftest import ROLE_PASSWORDS, _url_for
from tests.db.test_worker_nats import _finished, _web_client
from va_contracts.events.v1 import RunOptionsV1
from va_market_data.entrypoints import service as market_data
from va_market_data.entrypoints.settings import MarketDataSettings
from va_notification.entrypoints import service as notification
from va_notification.entrypoints.settings import NotificationSettings
from va_platform.db import create_db_engine
from va_platform.service import run_service
from va_scoring.entrypoints import service as scoring
from va_scoring.entrypoints.settings import ScoringSettings

FIXTURE = Path(__file__).parents[1] / "fixtures" / "replay" / "2026-10-30_scoring-run-1.json"
TIMEOUT = 120.0


def _settings(cls: Any, db_settings: Any, role: str, **update: Any) -> Any:
    """Die Settings eines Service aus denen des Batches, mit seiner eigenen Rolle (P5.3)."""
    database = make_url(db_settings.database_url.get_secret_value()).database
    assert database
    url = SecretStr(_url_for(database, role, ROLE_PASSWORDS[role]))
    return cls.model_validate({**dict(db_settings), "database_url": url, **update})


def test_three_services_run_the_chain(db_settings, engine, nats_url):
    md = _settings(
        MarketDataSettings,
        db_settings,
        "va_market_data",
        nats_url=nats_url,
        replay_source=FIXTURE,
    )
    sc = _settings(ScoringSettings, db_settings, "va_scoring", nats_url=nats_url)
    nt = _settings(
        NotificationSettings, db_settings, "va_notification", nats_url=nats_url, smtp_plain=True
    )
    app_engine = create_db_engine(nt.database_url.get_secret_value())
    send = Mock()
    adapters = replace(
        notification.build_adapters(nt, app_engine),
        sender=Mock(send=send),
        heartbeat=Mock(ping=Mock(return_value=None)),
    )
    stop = threading.Event()
    services = [
        threading.Thread(
            target=run_service,
            kwargs={"name": name, "settings": settings, "setup": setup, "stop": stop},
            daemon=True,
        )
        for name, settings, setup in (
            ("market-data", md, partial(market_data.setup, settings=md)),
            ("scoring", sc, partial(scoring.setup, settings=sc)),
            ("notification", nt, partial(notification.setup, settings=nt, adapters=adapters)),
        )
    ]
    for service in services:
        service.start()
    try:
        with _web_client(db_settings, nats_url) as web:
            deadline = time.monotonic() + 60
            while web.get("/api/v1/scoring/factors").status_code == 503:
                assert time.monotonic() < deadline, "scoring antwortet nicht"
                time.sleep(0.2)

            run_id = web.app.state.runs.start(RunOptionsV1())  # type: ignore[attr-defined]
            deadline = time.monotonic() + TIMEOUT
            while (run := _finished(engine, run_id)) is None and time.monotonic() < deadline:
                time.sleep(0.5)
            assert run is not None, "Run nicht abgeschlossen"

            detail = web.get(f"/api/v1/runs/{run_id}").json()
            report = web.get(f"/api/v1/reports/{detail['report_id']}")
            preview = web.post("/api/v1/scoring/preview", json={"value_weight": 0.5})
    finally:
        stop.set()
        for service in services:
            service.join(timeout=60)
        app_engine.dispose()

    assert all(not service.is_alive() for service in services)
    assert (run.status, run.exit_code) in {("success", 0), ("partial", 0)}
    send.assert_called_once()
    assert report.status_code == 200
    assert report.json()["html"].startswith("<!DOCTYPE")
    assert preview.status_code == 200
    assert preview.json()["scoring_run_id"] == run.scoring_run_id
    with engine.connect() as conn:
        copied = conn.execute(
            text("SELECT count(*) FROM scoring.input_snapshot WHERE fetch_run_id = :id"),
            {"id": run.fetch_run_id},
        ).scalar_one()
    assert copied == 90  # scoring rechnet die Vorschau aus seiner eigenen Kopie
