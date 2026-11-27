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
- D3.5: Datei im eigenen Format als JSON mit Base64: Abgleich, Uebernahme mit ``If-Match``,
  413 ueber 640 KiB, 422 ohne Base64 oder mit abgelehnten Zeilen; Download als CSV mit
  sicherem Dateinamen.
"""

from __future__ import annotations

import base64
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
from va_portfolio.domain.valuation import Quote, Score
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


def test_a_new_analysis_goes_to_its_owner_only():
    """D5.2: ``portfolio.analysis.completed`` wie ``depot.changed`` nur an ``user:<id>``."""
    from va_contracts.events.v1 import ANALYSIS_COMPLETED, AnalysisCompletedV1

    data = AnalysisCompletedV1(depot_id=3, owner_user_id=7, analysis_run_id=12, warning=1)
    envelope = new_envelope(ANALYSIS_COMPLETED, data, source="va/portfolio")
    assert topics_for(envelope) == ("user:7",)


class TestValuation:
    """D3.4: Bewertung aus den Kopien der Marktdaten in portfolio."""

    @pytest.fixture
    def valued(self, identity, store) -> Iterator[TestClient]:
        market = MemoryMarketStore()
        quote = Quote(SAP, date(2026, 11, 20), Decimal("231.5"), "EUR", source="yahoo")
        market.record_prices([quote], [], at=None)  # type: ignore[arg-type]
        # D4.2: Scores aus einem Bewertungslauf
        score = Score(
            isin=SAP,
            scoring_run_id=8,
            as_of=date(2026, 11, 20),
            symbol="SAP.DE",
            reference="universe",
            rank=12,
            value_score=0.41,
            quality_score=0.83,
            composite_score=0.578,
            composite_percentile=0.71,
        )
        market.record_scores([score], at=None)  # type: ignore[arg-type]
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

    def test_a_stock_carries_its_scores(self, valued):
        """D4.2: Scores aus dem juengsten Bewertungslauf; die Anleihe hat keine."""
        depot_id = self._depot(valued)
        sap, bund = valued.get(f"/api/v1/depots/{depot_id}").json()["valuation"]["positions"]
        assert sap["score"] == {
            "scoring_run_id": 8,
            "as_of": "2026-11-20",
            "symbol": "SAP.DE",
            "reference": "universe",
            "rank": 12,
            "value_score": 0.41,
            "quality_score": 0.83,
            "composite_score": 0.578,
            "composite_percentile": 0.71,
            "value_trap_flag": False,
            "value_trap_reason": None,
            "industry_rule": False,
            "reason": None,
        }
        assert bund["score"] is None

    def test_the_analysis_of_the_own_depot(self, valued):
        """D4.4: Analyse ueber RPC bei portfolio; die Anleihe hat ohne Stammdaten keine Rendite."""
        depot_id = self._depot(valued)
        response = valued.get(f"/api/v1/depots/{depot_id}/analysis")
        assert response.status_code == 200, response.text
        analysis = response.json()
        assert analysis["value_eur"] == "2415.00"
        assert set(analysis) == {
            "value_eur",
            "allocation",
            "concentration",
            "quality",
            "costs",
            "bonds",
            "data",
        }
        assert analysis["concentration"]["largest"]["isin"] == SAP
        assert analysis["quality"]["composite"] == 0.578  # nur SAP hat Scores
        assert (analysis["data"]["positions"], analysis["data"]["valued"]) == (2, 1)

    def test_the_analysis_of_a_foreign_depot_is_404(self, valued, identity, store):
        depot_id = self._depot(valued)
        other = _client(identity, store, "ben", MemoryMarketStore())
        try:
            assert other.get(f"/api/v1/depots/{depot_id}/analysis").status_code == 404
        finally:
            other.__exit__(None, None, None)

    def test_the_hints_of_the_own_depot(self, valued):
        """D5.2: Hinweise mit Status und Texten; ein fremdes Depot ist 404."""
        depot_id = self._depot(valued)
        response = valued.get(f"/api/v1/depots/{depot_id}/hints")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["analysis_run_id"] is not None
        rules = {h["rule"]: h for h in body["hints"]}
        assert rules["HIN-K01"]["severity"] == "critical"  # SAP 2315 von 2415
        assert rules["HIN-K01"]["status"] == "new"
        # Beide Wertpapiere ohne Stammdaten
        assert {h["subject"] for h in body["hints"] if h["rule"] == "HIN-D03"} == {SAP, BUND}
        assert rules["HIN-K01"]["approach"]

    def test_the_hints_of_a_foreign_depot_are_404(self, valued, identity, store):
        depot_id = self._depot(valued)
        other = _client(identity, store, "ben", MemoryMarketStore())
        try:
            assert other.get(f"/api/v1/depots/{depot_id}/hints").status_code == 404
        finally:
            other.__exit__(None, None, None)

    def test_thresholds_with_if_match(self, valued):
        """D5.3: Version 0 sind die Standardwerte; Speichern nur auf die neueste Version."""
        depot_id = self._depot(valued)
        url = f"/api/v1/depots/{depot_id}/hint-params"
        got = valued.get(url)
        assert (got.status_code, got.headers["ETag"]) == (200, '"0"')
        assert got.json()["params"]["k01_warning"] == 0.1
        body = {**got.json()["params"], "k01_warning": 0.97, "k01_critical": 0.99}
        assert _write(valued, "PUT", url, json=body).status_code == 428
        saved = _write(valued, "PUT", url, json=body, headers={"If-Match": '"0"'})
        assert (saved.status_code, saved.headers["ETag"]) == (200, '"1"')
        stale = _write(valued, "PUT", url, json=body, headers={"If-Match": '"0"'})
        assert stale.status_code == 409
        hints = valued.get(f"/api/v1/depots/{depot_id}/hints").json()["hints"]
        assert {h["status"] for h in hints if h["rule"] == "HIN-K01"} == {"resolved"}

    def test_target_allocation_brings_a01(self, valued):
        depot_id = self._depot(valued)
        url = f"/api/v1/depots/{depot_id}/target-allocation"
        assert valued.get(url).json() == {"version": 0, "shares": {}}
        bad = _write(
            valued, "PUT", url, json={"shares": {"equity": 0.5}}, headers={"If-Match": '"0"'}
        )
        assert bad.status_code == 422
        body = {"shares": {"equity": 0.5, "cash": 0.5}}
        saved = _write(valued, "PUT", url, json=body, headers={"If-Match": '"0"'})
        assert saved.json()["version"] == 1
        hints = valued.get(f"/api/v1/depots/{depot_id}/hints").json()["hints"]
        assert "HIN-A01:equity" in {h["key"] for h in hints}

    def test_acknowledge_a_hint(self, valued):
        depot_id = self._depot(valued)
        key = f"HIN-K01:{SAP}"
        acked = _write(valued, "POST", f"/api/v1/depots/{depot_id}/hints/{key}/ack", json={})
        assert acked.status_code == 200, acked.text
        [k01] = [h for h in acked.json()["hints"] if h["key"] == key]
        assert k01["acknowledged"] is True
        unknown = _write(valued, "POST", f"/api/v1/depots/{depot_id}/hints/HIN-K01:X/ack", json={})
        assert unknown.status_code == 404
        long = _write(valued, "POST", f"/api/v1/depots/{depot_id}/hints/{'x' * 201}/ack", json={})
        assert long.status_code == 422
        [depot] = valued.get("/api/v1/me/export").json()["depots"]
        assert [a["key"] for a in depot["acks"]] == [key]
        assert (depot["hint_params"], depot["targets"]) == ([], [])

    def test_the_catalog_of_the_hints(self, valued):
        response = valued.get("/api/v1/hints/catalog")
        assert response.status_code == 200
        rules = response.json()
        assert len(rules) == 25
        k01 = next(r for r in rules if r["rule"] == "HIN-K01")
        assert (k01["group"], k01["available"]) == ("Konzentration", True)
        assert next(r for r in rules if r["rule"] == "HIN-N01")["available"] is False

    def test_settings_of_a_foreign_depot_are_404(self, valued, identity, store):
        depot_id = self._depot(valued)
        other = _client(identity, store, "ben", MemoryMarketStore())
        try:
            assert other.get(f"/api/v1/depots/{depot_id}/hint-params").status_code == 404
            assert other.get(f"/api/v1/depots/{depot_id}/target-allocation").status_code == 404
        finally:
            other.__exit__(None, None, None)

    def test_without_market_data_no_analysis(self, anna):
        depot_id = _create(anna)
        assert anna.get(f"/api/v1/depots/{depot_id}/analysis").status_code == 503

    def test_without_market_data_no_valuation(self, anna):
        depot_id = _create(anna)
        assert anna.get(f"/api/v1/depots/{depot_id}").json()["valuation"] is None


def _b64(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode()


class TestFile:
    """D3.5: Datei im eigenen Format."""

    def _depot(self, client: TestClient) -> int:
        depot_id = _create(client)
        response = _write(
            client,
            "PUT",
            f"/api/v1/depots/{depot_id}/holdings",
            json={"lines": [{"isin": SAP, "quantity": "10"}]},
            headers={"If-Match": '"0"'},
        )
        assert response.status_code == 200
        return depot_id

    def test_preview_then_import(self, anna):
        depot_id = self._depot(anna)
        body = {
            "filename": "depot.csv",
            "content_base64": _b64(f"{SAP};12,5\n{BUND};5000;;;nennwert\n"),
        }
        preview = _write(anna, "POST", f"/api/v1/depots/{depot_id}/import/preview", json=body)
        assert preview.status_code == 200, preview.text
        data = preview.json()
        assert data["base_version"] == 1
        assert [(e["isin"], e["status"]) for e in data["entries"]] == [
            (SAP, "changed"),
            (BUND, "new"),
        ]
        imported = _write(
            anna,
            "POST",
            f"/api/v1/depots/{depot_id}/import",
            json=body,
            headers={"If-Match": '"1"'},
        )
        assert imported.status_code == 200, imported.text
        assert (imported.json()["version"], imported.json()["source"]) == (2, "import")
        assert imported.headers["ETag"] == '"2"'

    def test_import_needs_if_match(self, anna):
        depot_id = self._depot(anna)
        body = {"content_base64": _b64(f"{SAP};1\n")}
        response = _write(anna, "POST", f"/api/v1/depots/{depot_id}/import", json=body)
        assert response.status_code == 428

    def test_rejected_rows_are_422_on_import(self, anna):
        depot_id = self._depot(anna)
        body = {"content_base64": _b64(f"{SAP};zehn\n")}
        preview = _write(anna, "POST", f"/api/v1/depots/{depot_id}/import/preview", json=body)
        assert preview.json()["rejected"][0]["line"] == 1
        response = _write(
            anna,
            "POST",
            f"/api/v1/depots/{depot_id}/import",
            json=body,
            headers={"If-Match": '"1"'},
        )
        assert response.status_code == 422

    def test_not_base64(self, anna):
        depot_id = self._depot(anna)
        body = {"content_base64": "kein base64!"}
        response = _write(anna, "POST", f"/api/v1/depots/{depot_id}/import/preview", json=body)
        assert response.status_code == 422

    def test_too_large(self, anna):
        depot_id = self._depot(anna)
        content = base64.b64encode(b"x" * (640 * 1024 + 1)).decode()
        response = _write(
            anna,
            "POST",
            f"/api/v1/depots/{depot_id}/import/preview",
            json={"content_base64": content},
        )
        assert response.status_code in {413, 422}  # 422: schon die Laenge des Base64 ist zu gross

    def test_just_below_the_limit_passes_the_size_check(self, anna):
        depot_id = self._depot(anna)
        content = base64.b64encode(b"kaputt;1\n" * (640 * 1024 // 9)).decode()
        response = _write(
            anna,
            "POST",
            f"/api/v1/depots/{depot_id}/import/preview",
            json={"content_base64": content},
        )
        assert response.status_code == 422  # portfolio liest sie und lehnt sie ab
        assert "1000 Zeilen" in response.text

    def test_foreign_depot(self, anna, ben):
        depot_id = self._depot(anna)
        body = {"content_base64": _b64(f"{SAP};1\n")}
        response = _write(ben, "POST", f"/api/v1/depots/{depot_id}/import/preview", json=body)
        assert response.status_code == 404
        assert ben.get(f"/api/v1/depots/{depot_id}/holdings/csv").status_code == 404

    def test_download_as_csv(self, anna):
        depot_id = self._depot(anna)
        response = anna.get(f"/api/v1/depots/{depot_id}/holdings/csv")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/csv")
        assert response.headers["content-disposition"] == (
            f'attachment; filename="depot-{depot_id}-v1.csv"'
        )
        assert response.content.decode("utf-8-sig").splitlines()[1] == f"{SAP};10;;;stueck"


class TestComparison:
    """D5.5 (HIN-06): Pruefkandidaten, standardmaessig aus, nur zu Aktien im eigenen Depot."""

    IFX = "DE0006231004"
    AIR = "NL0000235190"

    @pytest.fixture
    def compared(self, identity, store) -> Iterator[TestClient]:
        market = MemoryMarketStore()

        def score(isin: str, composite: float, rank: int, sector: str = "Technology") -> Score:
            return Score(
                isin=isin,
                scoring_run_id=8,
                as_of=date(2026, 11, 20),
                symbol=f"{isin[-4:]}.DE",
                reference="universe",
                rank=rank,
                composite_score=composite,
                composite_percentile=composite,
                sector=sector,
                name=f"Titel {isin[-4:]}",
            )

        market.record_scores(
            [score(SAP, 0.3, 40), score(self.IFX, 0.7, 4), score(self.AIR, 0.9, 1, sector="x")],
            at=None,  # type: ignore[arg-type]
        )
        client = _client(identity, store, "anna", market)
        yield client
        client.__exit__(None, None, None)

    def _depot(self, client: TestClient) -> int:
        depot_id = _create(client)
        response = _write(
            client,
            "PUT",
            f"/api/v1/depots/{depot_id}/holdings",
            json={"lines": [{"isin": SAP, "quantity": "10"}], "cash": [{"amount": "100"}]},
            headers={"If-Match": '"0"'},
        )
        assert response.status_code == 200, response.text
        return depot_id

    def test_off_by_default_then_on(self, compared):
        depot_id = self._depot(compared)
        url = f"/api/v1/depots/{depot_id}/positions/{SAP}/comparison"
        off = compared.get(url)
        assert off.status_code == 200, off.text
        assert (off.json()["enabled"], off.json()["candidates"]) == (False, [])
        assert compared.get(f"/api/v1/depots/{depot_id}/hints").json()["candidates"] is False
        params = compared.get(f"/api/v1/depots/{depot_id}/hint-params").json()["params"]
        saved = _write(
            compared,
            "PUT",
            f"/api/v1/depots/{depot_id}/hint-params",
            json={**params, "candidates": True},
            headers={"If-Match": '"0"'},
        )
        assert saved.status_code == 200, saved.text
        on = compared.get(url).json()
        assert (on["enabled"], on["sector"], on["scoring_run_id"]) == (True, "Technology", 8)
        assert [(c["isin"], c["name"], c["rank"]) for c in on["candidates"]] == [
            (self.IFX, "Titel 1004", 4)
        ]
        assert compared.get(f"/api/v1/depots/{depot_id}/hints").json()["candidates"] is True

    def test_only_stocks_of_the_own_depot(self, compared, identity, store):
        depot_id = self._depot(compared)
        base = f"/api/v1/depots/{depot_id}/positions"
        assert compared.get(f"{base}/{self.IFX}/comparison").status_code == 404
        assert compared.get(f"{base}/keine-isin/comparison").status_code == 422
        other = _client(identity, store, "ben", MemoryMarketStore())
        try:
            assert other.get(f"{base}/{SAP}/comparison").status_code == 404
        finally:
            other.__exit__(None, None, None)
