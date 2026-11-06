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


def test_the_lock_counts_per_device_behind_the_proxy(base_url, account):
    """D1.5: nginx uebernimmt die Adresse vom Proxy davor (hier der Test, auf der NAS der
    DSM-Proxy), uvicorn die von nginx. Fuenf Fehlversuche von einem Geraet sperren nur dieses."""
    with httpx.Client(base_url=base_url, timeout=30) as client:
        for n in range(5):
            response = client.post(
                "/api/v1/auth/login",
                json={"username": f"niemand-{n}", "password": "Falsch-Falsch-Falsch-1"},
                headers={"X-Forwarded-For": "10.77.0.1"},
            )
            assert response.status_code == 401
        locked = client.post(
            "/api/v1/auth/login",
            json={"username": account[0], "password": account[1]},
            headers={"X-Forwarded-For": "10.77.0.1"},
        )
        assert locked.status_code == 429
        other = client.post(
            "/api/v1/auth/login",
            json={"username": account[0], "password": account[1]},
            headers={"X-Forwarded-For": "10.77.0.2"},
        )
        assert other.status_code == 204


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


def test_a_new_mail_address_counts_after_the_link_in_the_mail(base_url, mailpit, account):
    """D1.6 (NUT-10): web-api → VA_PRIVATE → notification → Mailpit; der Link bestaetigt."""
    import re
    import time
    from urllib.parse import parse_qs, urlsplit

    new = f"e2e-{int(time.time())}@example.com"
    with httpx.Client(base_url=base_url, timeout=30) as client:
        login(client)
        response = client.put(
            "/api/v1/me/profile",
            json={"display_name": "E2E", "email": new},
            headers={"Origin": base_url},
        )
        assert response.status_code == 200
        assert response.json()["pending_email"] == new

        link = None
        deadline = time.monotonic() + 60
        while link is None and time.monotonic() < deadline:
            messages = mailpit.get("/api/v1/messages", params={"limit": 50}).json()["messages"]
            for message in messages:
                if any(to["Address"] == new for to in message["To"]):
                    body = mailpit.get(f"/api/v1/message/{message['ID']}").json()["Text"]
                    found = re.search(r"https?://\S+/confirm-email\?token=\S+", body)
                    link = found.group(0) if found else None
            if link is None:
                time.sleep(1)
        assert link is not None, "keine Bestaetigungsmail in Mailpit"
        assert link.startswith(base_url)
        token = parse_qs(urlsplit(link).query)["token"][0]

        # Ohne Sitzung, wie ein Klick auf den Link in einem anderen Browser
        confirmed = httpx.post(
            f"{base_url}/api/v1/auth/confirm-email", json={"token": token}, timeout=10
        )
        assert confirmed.status_code == 204
        me = client.get("/api/v1/me").json()
        assert (me["email"], me["pending_email"]) == (new, None)
