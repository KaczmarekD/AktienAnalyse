"""NATS fuer die Tests von va-platform (P4.1, P4.3).

``nats_url`` ueberspringt den Test ohne ``TEST_NATS_URL`` (lokal ``make test-nats-up``, in der
CI ein Container mit JetStream) und loescht vorher den Stream: Jeder Test beginnt auf einem
Wegwerf-Server ohne Events.
"""

from __future__ import annotations

import asyncio
import contextlib
import os

import pytest

TEST_NATS_URL = os.environ.get("TEST_NATS_URL", "").strip()


def wipe_stream(url: str) -> None:
    async def wipe() -> None:
        import nats
        from nats.js.errors import NotFoundError

        nc = await nats.connect(url)
        try:
            with contextlib.suppress(NotFoundError):
                await nc.jsm().delete_stream("VA_EVENTS")
        finally:
            await nc.close()

    asyncio.run(wipe())


@pytest.fixture
def nats_url() -> str:
    if not TEST_NATS_URL:
        pytest.skip("TEST_NATS_URL nicht gesetzt (make test-nats-up)")
    wipe_stream(TEST_NATS_URL)
    return TEST_NATS_URL
