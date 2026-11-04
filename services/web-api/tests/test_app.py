"""Geruest des web-api (P3.1): App-Fabrik, Health, Swagger - ohne Datenbank."""

from __future__ import annotations

from importlib.metadata import version

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError

from va_web_api import main
from va_web_api.main import create_app
from va_web_api.settings import WebApiSettings

# Port 1: Es darf keine Verbindung noetig sein, weder fuer Health noch fuer die Doku
SETTINGS = WebApiSettings(database_url=SecretStr("postgresql+psycopg://va_read:x@127.0.0.1:1/none"))


@pytest.fixture
def client():
    with TestClient(create_app(SETTINGS)) as c:
        yield c


class TestHealth:
    def test_is_ok_without_a_database(self, client):
        response = client.get("/api/v1/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok", "version": version("va-web-api")}

    def test_unknown_path_is_404(self, client):
        assert client.get("/api/v1/gibt-es-nicht").status_code == 404


class TestDatabaseDown:
    def test_read_endpoint_answers_503(self):
        # connect_timeout: unter Windows wartet libpq sonst lange auf den abgelehnten Port
        url = SecretStr("postgresql+psycopg://va_read:x@127.0.0.1:1/none?connect_timeout=2")
        with TestClient(create_app(WebApiSettings(database_url=url))) as c:
            response = c.get("/api/v1/runs")
        assert response.status_code == 503
        assert response.json() == {"detail": "Datenbank nicht erreichbar"}


class TestDocs:
    """Unter /api, damit nginx (P3.6) sie mit /api/* weiterreicht."""

    def test_swagger_ui(self, client):
        response = client.get("/api/docs")
        assert response.status_code == 200
        assert "swagger" in response.text.lower()

    def test_operation_ids_are_the_function_names(self, client):
        # Daraus entstehen die Namen im generierten Client des Frontends (P3.5)
        schema = client.get("/api/v1/openapi.json").json()
        ids = {op["operationId"] for path in schema["paths"].values() for op in path.values()}
        assert {"health", "list_runs", "latest_ranking", "get_report_csv"} <= ids

    def test_openapi_lists_only_versioned_paths(self, client):
        schema = client.get("/api/v1/openapi.json").json()
        assert schema["info"]["version"] == version("va-web-api")
        assert all(path.startswith("/api/v1/") for path in schema["paths"])
        assert "/api/v1/health" in schema["paths"]


class TestSettings:
    def test_database_url_comes_from_web_api_prefix(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)  # keine .env aus dem Repo
        monkeypatch.setenv("WEB_API_DATABASE_URL", "postgresql+psycopg://va_read:geheim@db/x")
        monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://va_app:batch@db/x")
        settings = WebApiSettings()  # type: ignore[call-arg]
        url = settings.database_url.get_secret_value()
        assert url.startswith("postgresql+psycopg://va_read:")  # nie die URL des Batches
        assert "geheim" not in repr(settings)

    def test_database_url_is_required(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("WEB_API_DATABASE_URL", raising=False)
        with pytest.raises(ValidationError):
            WebApiSettings()  # type: ignore[call-arg]

    def test_lifespan_opens_a_read_only_engine_for_the_read_role(self, monkeypatch):
        calls: list[bool] = []
        real = main.create_db_engine

        def spy(url: str, *, read_only: bool = False):
            calls.append(read_only)
            return real(url, read_only=read_only)

        monkeypatch.setattr(main, "create_db_engine", spy)
        app = create_app(SETTINGS)
        with TestClient(app):
            assert app.state.engine.url.username == "va_read"
        assert calls == [True]


class TestEventConsumer:
    """P4.4: Projektionen nur mit NATS und eigener Rolle; sonst startet die App ohne."""

    def test_without_nats_there_is_no_consumer(self, client):
        assert client.app.state.events is None  # type: ignore[attr-defined]

    def test_unreachable_nats_does_not_stop_the_app(self):
        settings = SETTINGS.model_copy(
            update={
                "nats_url": "nats://127.0.0.1:1",
                "projections_database_url": SecretStr(
                    "postgresql+psycopg://va_web:x@127.0.0.1:1/none"
                ),
            }
        )
        with TestClient(create_app(settings)) as c:
            assert c.get("/api/v1/health").status_code == 200
            assert c.app.state.events is None  # type: ignore[attr-defined]

    def test_settings_know_nats_and_the_projection_role(self):
        assert SETTINGS.nats_url is None
        assert SETTINGS.projections_database_url is None
