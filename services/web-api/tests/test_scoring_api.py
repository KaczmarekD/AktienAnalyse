"""Router ``scoring`` (P3.3) ohne Datenbank: Profil-Befehle und Vorschau ueber Fake-Ports.

Speichern und Vorschau rechnet in Phase 3 der Code von scoring im selben Prozess (``src.web``),
ab Phase 4 per Request/Reply (P4.8). Die API bleibt dabei gleich: Jeder Test mit ``client`` laeuft
zweimal, im Prozess und ueber NATS (``RemoteScoring`` gegen ``scoring_handlers`` mit denselben
Fakes). Die NATS-Variante braucht ``TEST_NATS_URL``.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from va_contracts.profile import ProfileParamsV1
from va_platform.nats import NatsBus
from va_web_api.main import create_app
from va_web_api.models import Factor
from va_web_api.ports import (
    PreviewBasis,
    ProfileConflict,
    RankedTitle,
    UnknownProfile,
    UnknownVersion,
)
from va_web_api.rpc import scoring_handlers
from va_web_api.settings import WebApiSettings

# Port 1: Diese Tests brauchen keine Verbindung
NO_DB = "postgresql+psycopg://x:x@127.0.0.1:1/none"
# D1.2: Die Tests pruefen die Endpunkte, nicht die Anmeldung (Uebergang bis D1.4)
SETTINGS = WebApiSettings(
    database_url=SecretStr(NO_DB), profiles_database_url=SecretStr(NO_DB), auth_required=False
)
PARAMS = ProfileParamsV1().model_dump(mode="json")


def _title(symbol: str, rank: int | None, *, trap: bool = False) -> RankedTitle:
    composite = None if rank is None else 1 - rank / 10
    return RankedTitle(
        symbol=symbol,
        name=f"{symbol} AG",
        index="DAX",
        passed_filter=True,
        rank=rank,
        composite_score=composite,
        value_score=composite,
        quality_score=composite,
        value_trap_flag=trap,
    )


@dataclass
class FakePreview:
    calls: list[ProfileParamsV1] = field(default_factory=list)
    basis: PreviewBasis = field(
        default_factory=lambda: PreviewBasis(
            scoring_run_id=7,
            fetch_run_id=5,
            fetched_on=date(2026, 10, 30),
            active_profile_id=1,
            active_name="Standard",
            active_version=1,
            # Vorher: A, B, C vorn; nachher: A, C, D - B faellt raus, D kommt dazu
            current=[_title("A", 1), _title("B", 2), _title("C", 3), _title("D", 4, trap=True)],
            preview=[_title("A", 1), _title("C", 2), _title("D", 3), _title("B", 4)],
        )
    )

    def factors(self) -> list[Factor]:
        return [
            Factor(key="ev_ebit", group="value", label="EV/EBIT", better="low", hint="…"),
            Factor(key="roic", group="quality", label="ROIC", better="high", hint="…"),
        ]

    def preview(self, params: ProfileParamsV1) -> PreviewBasis:
        self.calls.append(params)
        return self.basis


@dataclass
class FakeCommands:
    newest: int = 3
    known_versions: tuple[int, ...] = (1, 2, 3)
    saved: list[dict[str, Any]] = field(default_factory=list)
    activated: list[tuple[int, int]] = field(default_factory=list)

    def save_version(
        self, profile_id: int, params: ProfileParamsV1, *, based_on: int, comment: str | None
    ) -> int:
        if profile_id != 1:
            raise UnknownProfile(profile_id)
        if based_on != self.newest:
            raise ProfileConflict(self.newest)
        self.saved.append({"params": params, "based_on": based_on, "comment": comment})
        self.newest += 1
        return self.newest

    def activate(self, profile_id: int, version: int) -> None:
        if profile_id != 1:
            raise UnknownProfile(profile_id)
        if version not in self.known_versions:
            raise UnknownVersion(version)
        self.activated.append((profile_id, version))


@pytest.fixture
def preview() -> FakePreview:
    return FakePreview()


@pytest.fixture
def commands() -> FakeCommands:
    return FakeCommands()


@pytest.fixture(params=["in_process", "nats"])
def client(request, preview, commands):
    if request.param == "in_process":
        app = create_app(SETTINGS, preview=lambda engine: preview, commands=lambda engine: commands)
        with TestClient(app) as c:
            yield c
        return
    # P4.8: ueber NATS, der Server beantwortet die Anfragen mit denselben Fakes
    url = request.getfixturevalue("nats_url")
    server = NatsBus(url)
    server.start()
    try:
        for spec, handler in scoring_handlers(preview, commands).items():
            server.serve(spec, handler, queue="scoring")
        with TestClient(create_app(SETTINGS.model_copy(update={"nats_url": url}))) as c:
            _wait_for_rpc(c)
            yield c
    finally:
        server.close()


def _wait_for_rpc(client: TestClient) -> None:
    """Die NATS-Verbindung fuer Request/Reply entsteht im Hintergrund des Lifespans."""
    deadline = time.monotonic() + 20
    while client.app.state.rpc is None:  # type: ignore[attr-defined]
        assert time.monotonic() < deadline, "keine NATS-Verbindung"
        time.sleep(0.05)


def _put(client: TestClient, if_match: str | None, params: dict[str, Any] | None = None):
    headers = {} if if_match is None else {"If-Match": if_match}
    body = {"params": params or PARAMS, "comment": "mehr Value"}
    return client.put("/api/v1/scoring/profiles/1", json=body, headers=headers)


class TestSave:
    def test_without_if_match_is_428(self, client, commands):
        assert _put(client, None).status_code == 428
        assert commands.saved == []

    def test_stale_version_is_409(self, client, commands):
        response = _put(client, '"2"')
        assert response.status_code == 409
        assert "3" in response.json()["detail"]  # nennt die aktuelle Version
        assert commands.saved == []

    def test_saves_a_new_version_on_top_of_the_named_one(self, client, commands):
        response = _put(client, '"3"', {**PARAMS, "value_weight": 0.5})
        assert response.status_code == 201
        assert response.json() == {"profile_id": 1, "version": 4, "parent_version": 3}
        assert response.headers["etag"] == '"4"'
        [saved] = commands.saved
        assert (saved["params"].value_weight, saved["based_on"], saved["comment"]) == (
            0.5,
            3,
            "mehr Value",
        )

    def test_weak_etag_is_accepted(self, client):
        assert _put(client, 'W/"3"').status_code == 201

    def test_garbage_if_match_is_400(self, client):
        assert _put(client, "irgendwas").status_code == 400

    def test_invalid_params_are_422(self, client, commands):
        response = _put(client, '"3"', {**PARAMS, "value_factors": ["ev_ebit"]})
        assert response.status_code == 422
        assert commands.saved == []

    def test_unknown_profile_is_404(self, client):
        response = client.put(
            "/api/v1/scoring/profiles/9",
            json={"params": PARAMS},
            headers={"If-Match": '"1"'},
        )
        assert response.status_code == 404


class TestActivate:
    def test_activates_the_version(self, client, commands):
        response = client.post("/api/v1/scoring/profiles/1/activate", json={"version": 2})
        assert response.status_code == 200
        assert response.json() == {"profile_id": 1, "version": 2}
        assert commands.activated == [(1, 2)]

    def test_unknown_version_is_404(self, client, commands):
        response = client.post("/api/v1/scoring/profiles/1/activate", json={"version": 9})
        assert response.status_code == 404
        assert commands.activated == []

    def test_needs_json(self, client):
        response = client.post("/api/v1/scoring/profiles/1/activate", content="version=2")
        assert response.status_code == 415


class TestPreview:
    def test_one_factor_is_422(self, client, preview):
        response = client.post(
            "/api/v1/scoring/preview", json={**PARAMS, "quality_factors": ["roic"]}
        )
        assert response.status_code == 422
        assert preview.calls == []

    def test_unknown_field_is_422(self, client):
        assert client.post("/api/v1/scoring/preview", json={"value_wieght": 0.5}).status_code == 422

    def test_compares_with_the_active_profile(self, client, preview):
        response = client.post(
            "/api/v1/scoring/preview?top=3", json={**PARAMS, "value_weight": 0.7}
        )
        assert response.status_code == 200
        body = response.json()
        assert preview.calls[0].value_weight == 0.7
        assert (body["scoring_run_id"], body["fetch_run_id"], body["fetched_on"]) == (
            7,
            5,
            "2026-10-30",
        )
        assert body["active"] == {"profile_id": 1, "name": "Standard", "version": 1}
        assert (body["top"], body["entered"], body["left"]) == (3, ["D"], ["B"])
        assert body["trap_changed"] == ["D"]
        rows = {r["symbol"]: r for r in body["rows"]}
        assert [r["symbol"] for r in body["rows"]] == ["A", "C", "D", "B"]
        assert (rows["C"]["rank"], rows["C"]["rank_active"]) == (2, 3)
        assert (rows["D"]["value_trap_flag"], rows["D"]["value_trap_flag_active"]) == (False, True)

    def test_top_is_bounded(self, client):
        assert client.post("/api/v1/scoring/preview?top=0", json=PARAMS).status_code == 422

    def test_factors(self, client):
        response = client.get("/api/v1/scoring/factors")
        assert response.status_code == 200
        assert [f["key"] for f in response.json()] == ["ev_ebit", "roic"]


class TestWithoutBackend:
    """Ohne Schreibzugang oder ohne Scoring-Code antworten die Endpunkte mit 503."""

    def test_without_profiles_url_saving_is_503(self, preview, commands):
        # Ausdruecklich None: eine lokale .env mit WEB_API_PROFILES_DATABASE_URL zaehlt nicht
        settings = WebApiSettings(
            auth_required=False,  # D1.2: Endpunkte, nicht Anmeldung
            database_url=SecretStr(NO_DB),
            profiles_database_url=None,
        )
        app = create_app(settings, preview=lambda engine: preview, commands=lambda engine: commands)
        with TestClient(app) as c:
            assert _put(c, '"3"').status_code == 503
            assert c.post("/api/v1/scoring/preview", json=PARAMS).status_code == 200
        assert commands.saved == []

    def test_without_scoring_code_preview_is_503(self):
        with TestClient(create_app(SETTINGS)) as c:
            assert c.post("/api/v1/scoring/preview", json=PARAMS).status_code == 503
            assert c.get("/api/v1/scoring/factors").status_code == 503
            assert _put(c, '"1"').status_code == 503

    def test_unreachable_scoring_is_503(self):
        """P4.8: Mit NATS, aber ohne Verbindung oder ohne Worker, ist scoring nicht erreichbar."""
        settings = SETTINGS.model_copy(update={"nats_url": "nats://127.0.0.1:1"})
        with TestClient(create_app(settings)) as c:
            response = c.post("/api/v1/scoring/preview", json=PARAMS)
            assert response.status_code == 503
            assert response.json()["detail"] == "Scoring nicht erreichbar"
            assert c.get("/api/v1/scoring/factors").status_code == 503
            assert _put(c, '"1"').status_code == 503
            assert (
                c.post("/api/v1/scoring/profiles/1/activate", json={"version": 1}).status_code
                == 503
            )
