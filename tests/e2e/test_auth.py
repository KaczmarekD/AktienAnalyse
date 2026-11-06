"""Anmeldung ueber nginx (D1.4): Sitzungspflicht, Cookie und Abmelden im ganzen Stack.

Nur mit ``E2E_USERNAME`` und ``E2E_PASSWORD`` (der E2E-Stack setzt beide und legt das Konto an);
ohne sie laeuft der Stack womoeglich ohne Sitzungspflicht.
"""

from __future__ import annotations

import httpx
import pytest
from websockets.exceptions import InvalidStatus
from websockets.sync.client import connect
from websockets.typing import Origin, Subprotocol

from .conftest import credentials, login


@pytest.fixture
def account() -> tuple[str, str]:
    found = credentials()
    if found is None:
        pytest.skip("ohne E2E_USERNAME/E2E_PASSWORD (make local-e2e setzt beide)")
    return found


@pytest.mark.usefixtures("account")
def test_the_stack_requires_a_login(base_url):
    health = httpx.get(f"{base_url}/api/v1/health", timeout=10).json()
    assert health["auth_required"] is True
    assert httpx.get(f"{base_url}/api/v1/runs", timeout=10).status_code == 401


@pytest.mark.usefixtures("account")
def test_without_session_no_websocket(base_url):
    url = base_url.replace("http://", "ws://", 1) + "/ws"
    with pytest.raises(InvalidStatus) as rejected:
        connect(url, origin=Origin(base_url), subprotocols=[Subprotocol("va.v1")], open_timeout=10)
    assert rejected.value.response.status_code == 403


def test_login_me_and_logout(base_url, account):
    with httpx.Client(base_url=base_url, timeout=30) as client:
        login(client)
        cookie = client.cookies.get("va_session")
        assert cookie, "nginx reicht das Sitzungs-Cookie durch"
        me = client.get("/api/v1/me").json()
        assert (me["username"], me["role"]) == (account[0], "admin")
        assert client.get("/api/v1/runs").status_code == 200
        assert client.post("/api/v1/auth/logout", json={}).status_code == 204
        # Auch wer das alte Cookie noch hat, ist abgemeldet
        client.cookies.set("va_session", cookie)
        assert client.get("/api/v1/runs").status_code == 401
