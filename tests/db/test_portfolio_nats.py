"""Der Dienst portfolio ueber NATS (D3.1): Datenbank und NATS sind echt.

portfolio laeuft wie in seinem Image: eigene Settings, Rolle ``va_portfolio``, Einstieg
``va_portfolio.entrypoints.service.setup``, ``run_service`` aus ``va_platform``. Ein Client fragt
per Request/Reply; jede Aenderung kommt als ``portfolio.depot.changed`` in den Stream, ohne Namen
und Mengen. Ohne ``TEST_DATABASE_URL`` oder ``TEST_NATS_URL`` uebersprungen.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from decimal import Decimal
from functools import partial

from pydantic import SecretStr
from sqlalchemy.engine import make_url

from tests.db.conftest import ROLE_PASSWORDS, _url_for
from va_contracts.portfolio import HoldingLineV1
from va_contracts.rpc.v1 import (
    DEPOTS_CREATE,
    DEPOTS_LIST,
    HOLDINGS_SAVE,
    DepotCreateRequestV1,
    DepotListRequestV1,
    HoldingsSaveRequestV1,
)
from va_platform.nats import NatsBus, RpcUnavailable
from va_platform.service import run_service
from va_portfolio.entrypoints import service as portfolio
from va_portfolio.entrypoints.settings import PortfolioSettings

ANNA = 1


def _events(nats_url: str, subject: str) -> list[dict]:
    async def fetch() -> list[dict]:
        import nats

        nc = await nats.connect(nats_url)
        try:
            js = nc.jetstream()
            sub = await js.subscribe(subject, ordered_consumer=True)
            found: list[dict] = []
            while True:
                try:
                    message = await sub.next_msg(timeout=1.0)
                except Exception:
                    return found
                found.append(json.loads(message.data))
        finally:
            await nc.close()

    return asyncio.run(fetch())


def test_depots_over_nats(db_url, nats_url):
    database = make_url(db_url).database
    assert database
    settings = PortfolioSettings(
        database_url=SecretStr(_url_for(database, "va_portfolio", ROLE_PASSWORDS["va_portfolio"])),
        nats_url=nats_url,
    )
    stop = threading.Event()
    service = threading.Thread(
        target=run_service,
        kwargs={
            "name": "portfolio",
            "settings": settings,
            "setup": partial(portfolio.setup, settings=settings),
            "stop": stop,
        },
        daemon=True,
    )
    service.start()
    client = NatsBus(nats_url, consumers=())
    client.start()
    try:
        deadline = time.monotonic() + 30
        while True:
            try:
                listed = client.call(DEPOTS_LIST, DepotListRequestV1(user_id=ANNA))
                break
            except RpcUnavailable:
                assert time.monotonic() < deadline, "portfolio antwortet nicht"
                time.sleep(0.2)
        assert listed.depots == []
        created = client.call(
            DEPOTS_CREATE, DepotCreateRequestV1(user_id=ANNA, name="Geheimes Depot")
        ).depot
        assert created is not None
        saved = client.call(
            HOLDINGS_SAVE,
            HoldingsSaveRequestV1(
                user_id=ANNA,
                depot_id=created.id,
                base_version=0,
                lines=[HoldingLineV1(isin="DE0007164600", quantity=Decimal("12.5"))],
            ),
        ).holdings
        assert saved is not None
        assert saved.version == 1
        foreign = client.call(DEPOTS_LIST, DepotListRequestV1(user_id=2))
        assert foreign.depots == []
    finally:
        client.close()
        stop.set()
        service.join(timeout=30)

    events = _events(nats_url, "va.portfolio.depot.changed")
    assert [(e["data"]["change"], e["data"]["version"]) for e in events] == [
        ("created", 0),
        ("holdings", 1),
    ]
    raw = json.dumps(events)
    assert "Geheimes Depot" not in raw
    assert "12.5" not in raw
