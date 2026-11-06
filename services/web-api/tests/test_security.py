"""Sicherheitsgrundlagen des web-api (P3.4, ADR-0007).

Nur im LAN und ohne Login, aber nicht schutzlos: Eine fremde Webseite im Browser kann Anfragen an
Adressen im Heimnetz schicken. Schreibende Anfragen muessen deshalb JSON sein. Fuer JSON prueft
der Browser bei fremden Seiten vorab (Preflight), und ohne CORS scheitert die Vorabpruefung.
Formulare, ``text/plain`` und ein ``fetch`` ohne Body kaemen sonst ohne Vorabpruefung durch.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from va_web_api.main import create_app
from va_web_api.settings import WebApiSettings

# D1.2: Die Tests pruefen die Endpunkte, nicht die Anmeldung (Uebergang bis D1.4)
SETTINGS = WebApiSettings(
    database_url=SecretStr("postgresql+psycopg://va_read:x@127.0.0.1:1/x"),
    auth_required=False,
)
FOREIGN = "http://boese.example"


@pytest.fixture
def client():
    with TestClient(create_app(SETTINGS)) as c:
        yield c


class TestMutationsOnlyWithJson:
    @pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
    @pytest.mark.parametrize(
        "content_type",
        ["text/plain", "application/x-www-form-urlencoded", "multipart/form-data; boundary=x"],
    )
    def test_form_like_bodies_are_rejected(self, client, method, content_type):
        response = client.request(
            method, "/api/v1/runs", content=b"x", headers={"Content-Type": content_type}
        )
        assert response.status_code == 415

    @pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
    def test_without_content_type_is_rejected(self, client, method):
        # fetch(url, {method: "POST"}) ohne Body kaeme ohne Vorabpruefung durch
        assert client.request(method, "/api/v1/runs").status_code == 415

    @pytest.mark.parametrize(
        "content_type", ["application/json", "application/json; charset=utf-8"]
    )
    def test_json_passes_the_check(self, client, content_type):
        response = client.post(
            "/api/v1/runs", content=b"{}", headers={"Content-Type": content_type}
        )
        # Durch die Pruefung; Runs starten kann dieses web-api nicht (ohne NATS, P4.7)
        assert response.status_code == 503

    def test_reads_are_not_affected(self, client):
        response = client.get("/api/v1/health", headers={"Content-Type": "text/plain"})
        assert response.status_code == 200


class TestNoCors:
    def test_foreign_origin_gets_no_cors_headers(self, client):
        response = client.get("/api/v1/health", headers={"Origin": FOREIGN})
        assert response.status_code == 200
        assert not [h for h in response.headers if h.lower().startswith("access-control-")]

    def test_preflight_is_not_allowed(self, client):
        response = client.options(
            "/api/v1/runs",
            headers={
                "Origin": FOREIGN,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )
        assert "access-control-allow-origin" not in response.headers
        assert response.status_code != 200


class TestNoSecrets:
    def test_api_description_mentions_no_secrets(self, client):
        schema = client.get("/api/v1/openapi.json").json()
        # D1.1: Nur die Anmeldung nimmt ein Passwort entgegen; keine Antwort enthaelt eins
        schema["paths"].pop("/api/v1/auth/login")
        schema["components"]["schemas"].pop("LoginRequest")
        description = json.dumps(schema, ensure_ascii=False).lower()
        for word in ("password", "passwort", "secret", "database_url", "smtp", "settings"):
            assert word not in description, word

    def test_the_password_is_only_part_of_the_login_request(self, client):
        schemas = client.get("/api/v1/openapi.json").json()["components"]["schemas"]
        with_password = sorted(
            n for n, s in schemas.items() if "password" in s.get("properties", {})
        )
        assert with_password == ["LoginRequest"]
