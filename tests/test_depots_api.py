"""``/api/v1/depots`` (D3.2): das web-api fragt portfolio, hier im selben Prozess.

Die Kette ist echt bis auf den Transport: ``RemoteDepots`` im web-api, ``LocalCaller`` statt NATS,
die Handler und der Anwendungsfall von portfolio mit ``MemoryDepotStore``. Anmeldung mit einem
Speicher im Speicher, wie in ``services/web-api/tests/test_authz.py``.

- Nur der Besitzer sieht und aendert sein Depot; ein fremdes ist 404, wie ein unbekanntes.
- ``ETag``/``If-Match`` auf den Depotstand: 428 ohne, 409 auf einen veralteten.
- Archiviert: 409 beim Aendern. Ungueltig (ISIN doppelt): 422. Ohne portfolio: 503.
- Mengen im JSON als Zahl im String.
- ``/me/export`` enthaelt die eigenen Depots mit allen Depotstaenden.
- ``portfolio.depot.changed`` geht an das Topic ``user:<id>`` des Besitzers.
- D3.4: Liste und Depot tragen die Bewertung, das Depot dazu jede Position; Betraege als
  Zahl im String, ein fehlender Kurs sichtbar.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from va_contracts import new_envelope
from va_contracts.events.v1 import DEPOT_CHANGED, DepotChangedV1
from va_platform.service import LocalCaller
from va_portfolio.adapters.memory import MemoryDepotStore, MemoryMarketStore
from va_portfolio.application.depots import DepotService
from va_portfolio.domain.valuation import Quote
from va_portfolio.entrypoints.rpc import handlers
from va_web_api.events import topics_for
from va_web_api.identity.domain import PasswordHasher
from va_web_api.identity.memory import MemoryIdentityStore
from va_web_api.identity.service import IdentityService
from va_web_api.main import create_app
from va_web_api.rpc import RemoteDepots
from va_web_api.settings import WebApiSettings

SETTINGS = WebApiSettings(database_url=SecretStr("postgresql+psycopg://x:x@127.0.0.1:1/none"))
PASSWORD = "Kiefer-Wolke-Rhein-42"
ORIGIN = "https://testserver"
SAP = "DE0007164600"
BUND = "DE0001102580"


@pytest.fixture
def identity() -> IdentityService:
    service = IdentityService(MemoryIdentityStore(), hasher=PasswordHasher(n=2**10))
    service.create_user("anna", PASSWORD)
    service.create_user("ben", PASSWORD)
    return service


@pytest.fixture
def store() -> MemoryDepotStore:
    return MemoryDepotStore()


def _client(
    identity: IdentityService,
    store: MemoryDepotStore | None,
    user: str,
    market: MemoryMarketStore | None = None,
) -> TestClient:
    client = TestClient(create_app(SETTINGS), base_url="https://testserver")
    client.__enter__()
    client.app.state.identity = identity  # type: ignore[attr-defined]
    client.app.state.depots = (  # type: ignore[attr-defined]
        None
        if store is None
        else RemoteDepots(lambda: LocalCaller(handlers(DepotService(store, market=market))))
    )
    response = client.post(
        "/api/v1/auth/login",
        json={"username": user, "password": PASSWORD},
        headers={"Origin": ORIGIN},
    )
    assert response.status_code == 204
    return client


@pytest.fixture
def anna(identity, store) -> Iterator[TestClient]:
    client = _client(identity, store, "anna")
    yield client
    client.__exit__(None, None, None)


@pytest.fixture
def ben(identity, store) -> Iterator[TestClient]:
    client = _client(identity, store, "ben")
    yield client
    client.__exit__(None, None, None)


def _write(client: TestClient, method: str, path: str, **kwargs):
    headers = {"Origin": ORIGIN, **kwargs.pop("headers", {})}
    return client.request(method, path, headers=headers, **kwargs)


def _create(client: TestClient, name: str = "DKB", kind: str = "depot") -> int:
    response = _write(client, "POST", "/api/v1/depots", json={"name": name, "kind": kind})
    assert response.status_code == 201, response.text
    return response.json()["id"]


class TestDepots:
    def test_create_list_get(self, anna):
        depot_id = _create(anna)
        [listed] = anna.get("/api/v1/depots").json()
        assert (listed["id"], listed["name"], listed["version"], listed["status"]) == (
            depot_id,
            "DKB",
            0,
            "active",
        )
        assert anna.get(f"/api/v1/depots/{depot_id}").json() == listed

    def test_foreign_depots_are_invisible(self, anna, ben):
        bens = _create(ben, "Bens Depot")
        assert anna.get("/api/v1/depots").json() == []
        for method, path, body in (
            ("GET", f"/api/v1/depots/{bens}", None),
            ("PUT", f"/api/v1/depots/{bens}", {"name": "Meins"}),
            ("POST", f"/api/v1/depots/{bens}/archive", {}),
            ("GET", f"/api/v1/depots/{bens}/holdings", None),
            ("GET", f"/api/v1/depots/{bens}/history", None),
        ):
            response = _write(anna, method, path, json=body)
            assert response.status_code == 404, (method, path)
        response = _write(
            anna, "PUT", f"/api/v1/depots/{bens}/holdings", json={}, headers={"If-Match": '"0"'}
        )
        assert response.status_code == 404
        assert ben.get(f"/api/v1/depots/{bens}").status_code == 200

    def test_rename_archive_restore(self, anna):
        depot_id = _create(anna)
        renamed = _write(anna, "PUT", f"/api/v1/depots/{depot_id}", json={"name": "Rente"})
        assert renamed.json()["name"] == "Rente"
        archived = _write(anna, "POST", f"/api/v1/depots/{depot_id}/archive", json={})
        assert archived.json()["status"] == "archived"
        assert anna.get("/api/v1/depots").json() == []
        assert len(anna.get("/api/v1/depots", params={"include_archived": True}).json()) == 1
        again = _write(anna, "PUT", f"/api/v1/depots/{depot_id}", json={"name": "Neu"})
        assert again.status_code == 409
        restored = _write(anna, "POST", f"/api/v1/depots/{depot_id}/restore", json={})
        assert restored.json()["status"] == "active"

    def test_a_blank_name_is_unprocessable(self, anna):
        response = _write(anna, "POST", "/api/v1/depots", json={"name": "   "})
        assert response.status_code == 422


class TestHoldings:
    def test_save_with_if_match_and_read_back(self, anna):
        depot_id = _create(anna)
        empty = anna.get(f"/api/v1/depots/{depot_id}/holdings")
        assert empty.headers["ETag"] == '"0"'
        body = {
            "lines": [
                {"isin": SAP, "quantity": "12.5", "cost_basis_eur": 1500, "note": "Kauf"},
                {"isin": BUND, "quantity": 10000, "unit": "nominal"},
            ],
            "cash": [{"amount": "250.10"}],
        }
        saved = _write(
            anna,
            "PUT",
            f"/api/v1/depots/{depot_id}/holdings",
            json=body,
            headers={"If-Match": empty.headers["ETag"]},
        )
        assert saved.status_code == 200, saved.text
        assert saved.headers["ETag"] == '"1"'
        current = anna.get(f"/api/v1/depots/{depot_id}/holdings").json()
        assert current["version"] == 1
        assert current["lines"][0]["quantity"] == "12.5"  # Zahl im String, nie float
        assert current["cash"][0]["amount"] == "250.10"
        assert anna.get(f"/api/v1/depots/{depot_id}").json()["positions"] == 2
        assert (
            anna.get(f"/api/v1/depots/{depot_id}/holdings", params={"version": 0}).json()["lines"]
            == []
        )

    def test_without_if_match_428(self, anna):
        depot_id = _create(anna)
        response = _write(anna, "PUT", f"/api/v1/depots/{depot_id}/holdings", json={})
        assert response.status_code == 428

    def test_a_stale_base_is_a_conflict(self, anna):
        depot_id = _create(anna)
        path = f"/api/v1/depots/{depot_id}/holdings"
        first = _write(anna, "PUT", path, json={}, headers={"If-Match": '"0"'})
        assert first.status_code == 200
        second = _write(anna, "PUT", path, json={}, headers={"If-Match": '"0"'})
        assert second.status_code == 409
        assert "aktuell: 1" in second.json()["detail"]

    def test_invalid_lines(self, anna):
        depot_id = _create(anna)
        path = f"/api/v1/depots/{depot_id}/holdings"
        duplicate = {"lines": [{"isin": SAP, "quantity": 1}, {"isin": SAP, "quantity": 2}]}
        response = _write(anna, "PUT", path, json=duplicate, headers={"If-Match": '"0"'})
        assert response.status_code == 422
        assert "doppelt" in response.json()["detail"]
        wrong = {"lines": [{"isin": "DE000716460", "quantity": 1}]}
        assert _write(anna, "PUT", path, json=wrong, headers={"If-Match": '"0"'}).status_code == 422

    def test_history(self, anna):
        depot_id = _create(anna)
        path = f"/api/v1/depots/{depot_id}/holdings"
        _write(
            anna,
            "PUT",
            path,
            json={"lines": [{"isin": SAP, "quantity": 1}]},
            headers={"If-Match": '"0"'},
        )
        _write(
            anna,
            "PUT",
            path,
            json={"lines": [{"isin": SAP, "quantity": 2}]},
            headers={"If-Match": '"1"'},
        )
        history = anna.get(f"/api/v1/depots/{depot_id}/history").json()
        assert [(h["version"], h["changed"], h["added"]) for h in history] == [(2, 1, 0), (1, 0, 1)]

    def test_a_watchlist_has_no_quantities(self, anna):
        depot_id = _create(anna, "Ideen", kind="watchlist")
        path = f"/api/v1/depots/{depot_id}/holdings"
        ok = _write(anna, "PUT", path, json={"lines": [{"isin": SAP}]}, headers={"If-Match": '"0"'})
        assert ok.status_code == 200
        with_quantity = {"lines": [{"isin": SAP, "quantity": 3}]}
        response = _write(anna, "PUT", path, json=with_quantity, headers={"If-Match": '"1"'})
        assert response.status_code == 422


class TestWithoutPortfolio:
    def test_503(self, identity):
        client = _client(identity, None, "anna")
        try:
            assert client.get("/api/v1/depots").status_code == 503
            # Der Export geht ohne eingerichtetes portfolio, nur ohne Depots
            assert client.get("/api/v1/me/export").json()["depots"] == []
        finally:
            client.__exit__(None, None, None)


def test_the_export_contains_the_own_depots(anna, ben):
    depot_id = _create(anna)
    _write(
        anna,
        "PUT",
        f"/api/v1/depots/{depot_id}/holdings",
        json={"lines": [{"isin": SAP, "quantity": "3"}]},
        headers={"If-Match": '"0"'},
    )
    _create(ben, "Bens")
    export = anna.get("/api/v1/me/export").json()
    [depot] = export["depots"]
    assert depot["depot"]["name"] == "DKB"
    assert [v["version"] for v in depot["versions"]] == [1]
    assert depot["versions"][0]["lines"][0]["quantity"] == "3"


def test_a_depot_change_goes_to_its_owner_only():
    data = DepotChangedV1(depot_id=3, owner_user_id=7, change="holdings", version=2)
    envelope = new_envelope(DEPOT_CHANGED, data, source="va/portfolio")
    assert topics_for(envelope) == ("user:7",)


class TestValuation:
    """D3.4: Bewertung aus den Kopien der Marktdaten in portfolio."""

    @pytest.fixture
    def valued(self, identity, store) -> Iterator[TestClient]:
        market = MemoryMarketStore()
        quote = Quote(SAP, date(2026, 11, 20), Decimal("231.5"), "EUR", source="yahoo")
        market.record_prices([quote], [], at=None)  # type: ignore[arg-type]
        client = _client(identity, store, "anna", market)
        yield client
        client.__exit__(None, None, None)

    def _depot(self, client: TestClient) -> int:
        depot_id = _create(client)
        response = _write(
            client,
            "PUT",
            f"/api/v1/depots/{depot_id}/holdings",
            json={
                "lines": [
                    {"isin": SAP, "quantity": "10", "cost_basis_eur": "2000"},
                    {"isin": BUND, "quantity": "5000", "unit": "nominal"},
                ],
                "cash": [{"amount": "100"}],
            },
            headers={"If-Match": '"0"'},
        )
        assert response.status_code == 200, response.text
        return depot_id

    def test_the_list_carries_the_value(self, valued):
        self._depot(valued)
        [depot] = valued.get("/api/v1/depots").json()
        valuation = depot["valuation"]
        assert valuation["value_eur"] == "2415.00"  # SAP plus Kasse; die Anleihe ohne Kurs
        assert (valuation["complete"], valuation["unvalued"]) == (False, 1)
        assert valuation["positions"] == []

    def test_the_depot_carries_each_position(self, valued):
        depot_id = self._depot(valued)
        valuation = valued.get(f"/api/v1/depots/{depot_id}").json()["valuation"]
        sap, bund = valuation["positions"]
        assert (sap["price"], sap["price_date"], sap["price_source"]) == (
            "231.5",
            "2026-11-20",
            "yahoo",
        )
        assert (sap["value_eur"], sap["difference_eur"]) == ("2315.00", "315.00")
        assert (bund["value_eur"], bund["missing"], bund["pending"]) == (None, "price", True)
        assert (valuation["cost_basis_eur"], valuation["difference_eur"]) == ("2000.00", "315.00")

    def test_without_market_data_no_valuation(self, anna):
        depot_id = _create(anna)
        assert anna.get(f"/api/v1/depots/{depot_id}").json()["valuation"] is None
