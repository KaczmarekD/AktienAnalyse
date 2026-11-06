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


# D1.4: Nur diese Anfragen nehmen ein Passwort entgegen (Anmelden, Passwort aendern, Nutzer
# anlegen, Einmal-Passwort setzen). Keine Antwort enthaelt eins.
# D1.6: dazu das Token aus dem Bestaetigungslink
PASSWORD_REQUESTS = {
    "LoginRequest",
    "PasswordChange",
    "NewAccount",
    "PasswordReset",
    "EmailConfirmation",
}
SECRET_WORDS = ("password", "secret", "token")


def _secret_fields(schema: dict) -> list[str]:
    """Felder, deren Name nach Geheimnis klingt; ein Schalter wie ``must_change_password`` nicht."""
    return [
        name
        for name, prop in schema.get("properties", {}).items()
        if any(word in name for word in SECRET_WORDS) and prop.get("type") != "boolean"
    ]


def _refs(node: object) -> set[str]:
    if isinstance(node, dict):
        found = {node["$ref"].rsplit("/", 1)[-1]} if "$ref" in node else set()
        return found.union(*(_refs(value) for value in node.values()))
    if isinstance(node, list):
        return set().union(*(_refs(value) for value in node))
    return set()


class TestNoSecrets:
    def test_api_description_mentions_no_settings(self, client):
        description = json.dumps(client.get("/api/v1/openapi.json").json()).lower()
        for word in ("secret", "database_url", "smtp", "settings"):
            assert word not in description, word

    def test_only_these_requests_take_a_password(self, client):
        schemas = client.get("/api/v1/openapi.json").json()["components"]["schemas"]
        assert {name for name, schema in schemas.items() if _secret_fields(schema)} == (
            PASSWORD_REQUESTS
        )

    def test_no_response_contains_a_secret(self, client):
        schema = client.get("/api/v1/openapi.json").json()
        schemas = schema["components"]["schemas"]
        responses = _refs(
            [op.get("responses", {}) for ops in schema["paths"].values() for op in ops.values()]
        )
        # Auch, was die Antworten ueber weitere Verweise enthalten
        seen: set[str] = set()
        while responses - seen:
            name = (responses - seen).pop()
            seen.add(name)
            responses |= _refs(schemas[name])
        assert not seen & PASSWORD_REQUESTS
        assert {
            name: _secret_fields(schemas[name]) for name in seen if _secret_fields(schemas[name])
        } == {}
