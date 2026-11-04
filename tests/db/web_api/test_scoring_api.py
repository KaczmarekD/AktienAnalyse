"""Profil-Endpunkte (P3.3) gegen ein echtes PostgreSQL, ueber die Composition Root ``src.web``.

Ein Replay-Lauf (echte Woche, 90 Titel) legt Abruf, Ranking und das Profil "Standard" v1 an.
Das web-api liest mit ``va_read`` und speichert Profile mit ``va_profiles``.

Seit P4.8 laeuft jeder Test zweimal: im Prozess und ueber NATS. Dort beantwortet der Worker
(``src.worker``) Vorschau und Profil-Befehle mit der Rolle ``va_app``. Die NATS-Variante braucht
``TEST_NATS_URL``.
"""

from __future__ import annotations

import threading
import time
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.engine import make_url

from src.web import create_app
from src.worker import serve
from tests.db.conftest import ROLE_PASSWORDS, _url_for
from tests.db.test_replay_run_db import FIXTURE, _replay_run
from va_web_api.settings import WebApiSettings


def _client(db_url: str, nats_url: str | None = None) -> TestClient:
    database = make_url(db_url).database
    assert database
    read = _url_for(database, "va_read", ROLE_PASSWORDS["va_read"])
    write = _url_for(database, "va_profiles", ROLE_PASSWORDS["va_profiles"])
    settings = WebApiSettings(
        database_url=SecretStr(read), profiles_database_url=SecretStr(write), nats_url=nats_url
    )
    return TestClient(create_app(settings))


def _wait_for_the_worker(client: TestClient) -> None:
    """Verbindung des web-api und Abo des Workers entstehen im Hintergrund."""
    deadline = time.monotonic() + 60
    while client.get("/api/v1/scoring/factors").status_code == 503:
        assert time.monotonic() < deadline, "scoring antwortet nicht ueber NATS"
        time.sleep(0.2)


@pytest.fixture
def replay_settings(db_settings):
    return db_settings.model_copy(update={"replay_source": FIXTURE, "smtp_plain": True})


@pytest.fixture(params=["in_process", "nats"])
def api(request, replay_settings, db_url):
    rc, _ = _replay_run(replay_settings)
    assert rc == 0
    if request.param == "in_process":
        with _client(db_url) as client:
            yield client
        return
    # P4.8: dieselben Endpunkte, beantwortet vom Worker ueber NATS
    url = request.getfixturevalue("nats_url")
    settings = replay_settings.model_copy(update={"event_bus": "nats", "nats_url": url})
    stop = threading.Event()
    worker = threading.Thread(target=serve, args=(settings, stop), daemon=True)
    worker.start()
    try:
        with _client(db_url, nats_url=url) as client:
            _wait_for_the_worker(client)
            yield client
    finally:
        stop.set()
        worker.join(timeout=60)


def _standard(api: TestClient) -> dict[str, Any]:
    [profile] = api.get("/api/v1/scoring/profiles").json()
    return profile


def _v1_params(api: TestClient) -> dict[str, Any]:
    detail = api.get(f"/api/v1/scoring/profiles/{_standard(api)['id']}").json()
    return detail["versions"][-1]["params"]


def _save(api: TestClient, params: dict[str, Any], if_match: str = '"1"'):
    return api.put(
        f"/api/v1/scoring/profiles/{_standard(api)['id']}",
        json={"params": params, "comment": "Test"},
        headers={"If-Match": if_match},
    )


class TestProfiles:
    def test_standard_is_listed_and_active(self, api):
        profile = _standard(api)
        assert (profile["name"], profile["latest_version"], profile["active_version"]) == (
            "Standard",
            1,
            1,
        )

    def test_detail_with_versions_and_etag(self, api):
        response = api.get(f"/api/v1/scoring/profiles/{_standard(api)['id']}")
        assert response.status_code == 200
        assert response.headers["etag"] == '"1"'
        [version] = response.json()["versions"]
        assert (version["version"], version["active"], version["parent_version"]) == (1, True, None)
        assert version["params"]["value_weight"] == 0.6
        assert version["comment"].startswith("Startwerte aus ENV")

    def test_unknown_profile_is_404(self, api):
        assert api.get("/api/v1/scoring/profiles/999").status_code == 404

    def test_factor_catalog(self, api):
        factors = api.get("/api/v1/scoring/factors").json()
        keys = [(f["group"], f["key"]) for f in factors]
        assert ("value", "ev_ebit") in keys
        assert ("quality", "net_debt_ebitda") in keys
        assert all(f["hint"] for f in factors)


class TestSave:
    def test_creates_the_next_version_without_activating_it(self, api):
        response = _save(api, {**_v1_params(api), "value_weight": 0.5})
        assert response.status_code == 201
        assert response.json() == {
            "profile_id": _standard(api)["id"],
            "version": 2,
            "parent_version": 1,
        }
        detail = api.get(f"/api/v1/scoring/profiles/{_standard(api)['id']}").json()
        assert [v["version"] for v in detail["versions"]] == [2, 1]
        assert detail["versions"][0]["params"]["value_weight"] == 0.5
        assert detail["active_version"] == 1  # Speichern aktiviert nicht

    def test_stale_if_match_is_409_and_writes_nothing(self, api):
        params = _v1_params(api)
        assert _save(api, {**params, "value_weight": 0.5}).status_code == 201
        # Ein zweiter Tab speichert auf derselben Grundlage
        assert _save(api, {**params, "value_weight": 0.4}).status_code == 409
        detail = api.get(f"/api/v1/scoring/profiles/{_standard(api)['id']}").json()
        assert [v["version"] for v in detail["versions"]] == [2, 1]

    def test_invalid_params_are_422(self, api):
        response = _save(api, {**_v1_params(api), "value_factors": ["ev_ebit"]})
        assert response.status_code == 422


class TestActivate:
    def test_next_run_scores_with_the_activated_version(self, api, replay_settings, engine):
        pid = _standard(api)["id"]
        assert _save(api, {**_v1_params(api), "value_weight": 0.5}).status_code == 201
        response = api.post(f"/api/v1/scoring/profiles/{pid}/activate", json={"version": 2})
        assert response.status_code == 200
        assert response.json() == {"profile_id": pid, "version": 2}
        assert _standard(api)["active_version"] == 2

        rc, _ = _replay_run(replay_settings)
        assert rc == 0
        with engine.connect() as conn:
            versions = conn.execute(
                text("SELECT profile_version FROM scoring.scoring_run ORDER BY id")
            ).scalars()
            assert list(versions) == [1, 2]

    def test_rollback_activates_v1_again(self, api, engine):
        pid = _standard(api)["id"]
        _save(api, {**_v1_params(api), "value_weight": 0.5})
        api.post(f"/api/v1/scoring/profiles/{pid}/activate", json={"version": 2})
        api.post(f"/api/v1/scoring/profiles/{pid}/activate", json={"version": 1})
        assert _standard(api)["active_version"] == 1
        with engine.connect() as conn:
            count = conn.execute(text("SELECT count(*) FROM scoring.profile_activation"))
            assert count.scalar_one() == 3

    def test_unknown_version_is_404(self, api):
        pid = _standard(api)["id"]
        response = api.post(f"/api/v1/scoring/profiles/{pid}/activate", json={"version": 7})
        assert response.status_code == 404


class TestPreview:
    def test_active_params_change_nothing(self, api):
        response = api.post("/api/v1/scoring/preview", json=_v1_params(api))
        assert response.status_code == 200
        body = response.json()
        assert body["active"]["version"] == 1
        assert len(body["rows"]) == 90
        assert all(r["rank"] == r["rank_active"] for r in body["rows"])
        assert (body["entered"], body["left"], body["trap_changed"]) == ([], [], [])

    def test_other_weight_moves_ranks(self, api):
        response = api.post(
            "/api/v1/scoring/preview", json={**_v1_params(api), "value_weight": 0.1}
        )
        assert response.status_code == 200
        rows = response.json()["rows"]
        assert any(r["rank"] != r["rank_active"] for r in rows)

    def test_stores_nothing(self, api, engine):
        def counts() -> tuple[int, int]:
            with engine.connect() as conn:
                runs = conn.execute(text("SELECT count(*) FROM scoring.scoring_run")).scalar_one()
                versions = conn.execute(
                    text("SELECT count(*) FROM scoring.profile_version")
                ).scalar_one()
            return runs, versions

        before = counts()
        api.post("/api/v1/scoring/preview", json={**_v1_params(api), "value_weight": 0.1})
        assert counts() == before

    def test_one_factor_is_422(self, api):
        params = {**_v1_params(api), "quality_factors": ["roic"]}
        assert api.post("/api/v1/scoring/preview", json=params).status_code == 422


def test_preview_without_any_run_is_404(db_url):
    with _client(db_url) as client:
        assert client.post("/api/v1/scoring/preview", json={}).status_code == 404
