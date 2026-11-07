"""Eigene Inbox je NATS-Nutzer (D1.5, nutzer.md Regel 11), ohne Server.

Mit ``_INBOX.>`` laese jeder Dienst die Antworten an alle anderen mit (Berichte, Profile). Deshalb
bekommt jeder Nutzer ``_INBOX.<nutzer>``, die Rechte in ``docker/nats/nats.conf`` erlauben nur
diese.
"""

from __future__ import annotations

import pytest

from va_platform.nats import inbox_prefix


@pytest.mark.parametrize(
    ("url", "prefix"),
    [
        ("nats://market-data:geheim@nats:4222", "_INBOX.market-data"),
        ("nats://web-api:a%40b@nats:4222", "_INBOX.web-api"),
        ("nats://nats:4222", "_INBOX"),  # ohne Nutzer: wie bisher (Tests, lokaler Server)
        ("nats://127.0.0.1:14224", "_INBOX"),
    ],
)
def test_the_inbox_follows_the_user(url, prefix):
    assert inbox_prefix(url) == prefix
