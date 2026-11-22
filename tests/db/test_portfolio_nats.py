"""Der Dienst portfolio ueber NATS (D3.1): Datenbank und NATS sind echt.

portfolio laeuft wie in seinem Image: eigene Settings, Rolle ``va_portfolio``, Einstieg
``va_portfolio.entrypoints.service.setup``, ``run_service`` aus ``va_platform``. Ein Client fragt
per Request/Reply; jede Aenderung kommt als ``portfolio.depot.changed`` in den Stream, ohne Namen
und Mengen. Seit D3.3 dazu die Abdeckung (``portfolio.coverage.changed``), beim Start und nach
der Aenderung; market-data uebernimmt sie als neue Fassung. Ohne ``TEST_DATABASE_URL`` oder
``TEST_NATS_URL`` uebersprungen.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from decimal import Decimal
from functools import partial
from unittest.mock import Mock

from pydantic import SecretStr
from sqlalchemy.engine import make_url

from tests.db.conftest import ROLE_PASSWORDS, _url_for
from tests.db.test_services_nats import _settings
from va_contracts.portfolio import HoldingLineV1
from va_contracts.rpc.v1 import (
    DEPOTS_CREATE,
    DEPOTS_LIST,
    HOLDINGS_SAVE,
    DepotCreateRequestV1,
    DepotListRequestV1,
    HoldingsSaveRequestV1,
)
from va_market_data.adapters.postgres.store import PostgresSnapshotStore
from va_market_data.application.coverage import follow_portfolio
from va_market_data.domain.securities import Listing, SecurityHit
from va_market_data.entrypoints import service as market_data
from va_market_data.entrypoints.settings import MarketDataSettings
from va_platform.db import create_db_engine
from va_platform.nats import NatsBus, RpcUnavailable
from va_platform.service import run_service
from va_portfolio.entrypoints import service as portfolio
from va_portfolio.entrypoints.settings import PortfolioSettings

ANNA = 1
SAP = "DE0007164600"


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


def _portfolio(db_url: str, nats_url: str, stop: threading.Event) -> threading.Thread:
    database = make_url(db_url).database
    assert database
    settings = PortfolioSettings(
        database_url=SecretStr(_url_for(database, "va_portfolio", ROLE_PASSWORDS["va_portfolio"])),
        nats_url=nats_url,
    )
    return threading.Thread(
        target=run_service,
        kwargs={
            "name": "portfolio",
            "settings": settings,
            "setup": partial(portfolio.setup, settings=settings),
            "stop": stop,
        },
        daemon=True,
    )


def _wait_for_portfolio(client: NatsBus) -> None:
    deadline = time.monotonic() + 30
    while True:
        try:
            listed = client.call(DEPOTS_LIST, DepotListRequestV1(user_id=ANNA))
            break
        except RpcUnavailable:
            assert time.monotonic() < deadline, "portfolio antwortet nicht"
            time.sleep(0.2)
    assert listed.depots == []


def test_depots_over_nats(db_url, nats_url):
    stop = threading.Event()
    service = _portfolio(db_url, nats_url, stop)
    service.start()
    client = NatsBus(nats_url, consumers=())
    client.start()
    try:
        _wait_for_portfolio(client)
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
    coverage = _events(nats_url, "va.portfolio.coverage.changed")
    assert [e["data"] for e in coverage][-2:] == [{"isins": []}, {"isins": ["DE0007164600"]}]
    raw = json.dumps(events + coverage)
    assert "Geheimes Depot" not in raw
    assert "12.5" not in raw


def test_holdings_reach_the_coverage_of_market_data(db_url, db_settings, nats_url):
    """D3.3: portfolio meldet die Menge, market-data speichert sie als neue Fassung (ohne Netz:
    die eigenen Wertpapiere kennen SAP, die Aufloesung ist ein Fake)."""
    md = _settings(MarketDataSettings, db_settings, "va_market_data", nats_url=nats_url)
    md_engine = create_db_engine(md.database_url.get_secret_value())
    store = PostgresSnapshotStore(md_engine, provider="test", provider_version=None)
    sap = SecurityHit(SAP, "SAP SE", "equity", (Listing("SAP.DE", exchange="GY"),), "catalog")

    def follow(isins, at):
        return follow_portfolio(
            isins,
            as_of=at,
            store=store,
            known=lambda isin: sap if isin == SAP else None,
            resolve=lambda isin: None,
        )

    adapters = market_data.MarketDataAdapters(
        store=store, load_universe=Mock(), fetch=Mock(), follow_coverage=follow
    )
    stop = threading.Event()
    services = [
        _portfolio(db_url, nats_url, stop),
        threading.Thread(
            target=run_service,
            kwargs={
                "name": "market-data",
                "settings": md,
                "setup": partial(
                    market_data.setup, settings=md, adapters=adapters, securities_service=Mock()
                ),
                "stop": stop,
            },
            daemon=True,
        ),
    ]
    for service in services:
        service.start()
    client = NatsBus(nats_url, consumers=())
    client.start()
    try:
        _wait_for_portfolio(client)
        depot = client.call(
            DEPOTS_CREATE, DepotCreateRequestV1(user_id=ANNA, kind="watchlist", name="Ideen")
        ).depot
        assert depot is not None
        client.call(
            HOLDINGS_SAVE,
            HoldingsSaveRequestV1(
                user_id=ANNA,
                depot_id=depot.id,
                base_version=0,
                lines=[HoldingLineV1(isin=SAP, quantity=None)],
            ),
        )
        deadline = time.monotonic() + 60
        while [item.isin for item in store.coverage()] != [SAP]:
            assert time.monotonic() < deadline, "Abdeckung nicht angekommen"
            time.sleep(0.5)
        [item] = store.coverage()
        assert (item.fundamentals_symbol, item.price_symbol) == ("SAP.DE", "SAP.DE")
    finally:
        client.close()
        stop.set()
        for service in services:
            service.join(timeout=30)
        md_engine.dispose()
