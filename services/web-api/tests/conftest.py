"""NATS fuer die Tests des web-api (P4.8): Request/Reply an scoring.

``nats_url`` ueberspringt den Test ohne ``TEST_NATS_URL`` (lokal ``make test-nats-up``, in der
CI ein Container mit JetStream). Den Stream braucht Request/Reply nicht, er bleibt deshalb stehen.
"""

from __future__ import annotations

import os

import pytest

TEST_NATS_URL = os.environ.get("TEST_NATS_URL", "").strip()


@pytest.fixture
def nats_url() -> str:
    if not TEST_NATS_URL:
        pytest.skip("TEST_NATS_URL nicht gesetzt (make test-nats-up)")
    return TEST_NATS_URL
