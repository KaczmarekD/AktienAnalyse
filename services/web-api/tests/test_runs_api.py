"""``POST /runs`` (P4.7) ohne Datenbank: Start eines Runs aus dem UI ueber einen Fake.

Die Run-Verwaltung gibt es nur mit NATS und Projektions-Datenbank; sonst antwortet der Endpunkt
mit 503. Was ein Start in der Datenbank anlegt, pruefen ``tests/db/web_api/test_runs.py``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from va_contracts.events.v1 import RunOptionsV1
from va_web_api.main import create_app
from va_web_api.ports import RunActive
from va_web_api.settings import WebApiSettings

# D1.2: Die Tests pruefen die Endpunkte, nicht die Anmeldung (Uebergang bis D1.4)
SETTINGS = WebApiSettings(
    database_url=SecretStr("postgresql+psycopg://x:x@127.0.0.1:1/none"),
    auth_required=False,
)


@dataclass
class FakeRuns:
    next_id: int = 7
    active: int | None = None
    calls: list[RunOptionsV1] = field(default_factory=list)

    def start(self, options: RunOptionsV1) -> int:
        if self.active is not None:
            raise RunActive(self.active)
        self.calls.append(options)
        return self.next_id


@pytest.fixture
def runs() -> FakeRuns:
    return FakeRuns()


@pytest.fixture
def client(runs: FakeRuns):
    with TestClient(create_app(SETTINGS)) as c:
        c.app.state.runs = runs  # type: ignore[attr-defined]
        yield c


def test_a_start_answers_with_the_run(client, runs):
    response = client.post("/api/v1/runs", json={"dry_run": True, "notify": False})
    assert response.status_code == 202
    assert response.json() == {"id": 7}
    assert runs.calls == [RunOptionsV1(dry_run=True, notify=False)]


def test_the_options_have_defaults(client, runs):
    assert client.post("/api/v1/runs", json={}).status_code == 202
    assert runs.calls == [RunOptionsV1(force_refresh=False, dry_run=False, notify=True)]


def test_an_open_run_is_a_conflict(client, runs):
    runs.active = 3
    response = client.post("/api/v1/runs", json={})
    assert response.status_code == 409
    assert "#3" in response.json()["detail"]
    assert runs.calls == []


def test_unknown_fields_are_rejected(client, runs):
    response = client.post("/api/v1/runs", json={"dry_run": True, "dryRun": True})
    assert response.status_code == 422
    assert runs.calls == []


def test_without_run_management_it_is_unavailable():
    with TestClient(create_app(SETTINGS)) as c:
        assert c.app.state.runs is None  # type: ignore[attr-defined]
        response = c.post("/api/v1/runs", json={})
    assert response.status_code == 503
    assert "NATS" in response.json()["detail"]


def test_the_endpoint_is_documented(client):
    paths = client.get("/api/v1/openapi.json").json()["paths"]
    post = paths["/api/v1/runs"]["post"]
    assert post["operationId"] == "start_run"
    assert {"202", "409", "422", "503"} <= set(post["responses"])
