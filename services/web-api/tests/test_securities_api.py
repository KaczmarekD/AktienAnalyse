"""``/securities`` (D2.1, WP-02, WP-03): Wertpapiere suchen und aufloesen ueber market-data.

Ohne Datenbank und ohne NATS, mit einem Fake fuer das Request/Reply. Ohne market-data antworten
die Endpunkte mit 503, eine unbekannte ISIN mit 404, eine ungueltige mit 422.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from va_contracts.securities import BondTermsV1, ListingV1, SecurityHitV1, SecurityV1
from va_web_api.main import create_app
from va_web_api.ports import RemoteUnavailable
from va_web_api.settings import WebApiSettings

# Die Tests pruefen die Endpunkte, nicht die Anmeldung (die prueft test_authz.py)
SETTINGS = WebApiSettings(
    database_url=SecretStr("postgresql+psycopg://x:x@127.0.0.1:1/none"),
    auth_required=False,
)

APPLE = "US0378331005"
BOND = "DE000A383J95"


@dataclass
class FakeSecurities:
    down: bool = False
    searches: list[str] = field(default_factory=list)
    resolves: list[tuple[str, str | None]] = field(default_factory=list)

    def search(self, query: str) -> list[SecurityHitV1]:
        if self.down:
            raise RemoteUnavailable("market-data")
        self.searches.append(query)
        return [
            SecurityHitV1(
                isin=APPLE,
                name="APPLE INC",
                asset_class="equity",
                listings=[ListingV1(symbol="APC.DE", ticker="APC", exchange="GY")],
                source="openfigi",
            )
        ]

    def resolve(self, isin: str, symbol: str | None = None) -> SecurityV1 | None:
        if self.down:
            raise RemoteUnavailable("market-data")
        self.resolves.append((isin, symbol))
        if isin != BOND:
            return None
        return SecurityV1(
            isin=BOND,
            name="DB 4.000 7/12/28",
            asset_class="bond",
            currency="EUR",
            lei="7LTWFZYICNSX8D621K86",
            cfi="DTVUGB",
            bond=BondTermsV1(coupon=4.0, maturity=date(2028, 7, 12), floating=True),
            listings=[],
            listing=None,
        )


@pytest.fixture
def securities() -> FakeSecurities:
    return FakeSecurities()


@pytest.fixture
def client(securities: FakeSecurities):
    with TestClient(create_app(SETTINGS)) as c:
        c.app.state.securities = securities  # type: ignore[attr-defined]
        yield c


class TestSearch:
    def test_finds(self, client, securities):
        response = client.get("/api/v1/securities/search", params={"q": "Apple"})
        assert response.status_code == 200
        [hit] = response.json()
        assert (hit["isin"], hit["name"], hit["asset_class"]) == (APPLE, "APPLE INC", "equity")
        assert hit["listings"][0]["symbol"] == "APC.DE"
        assert securities.searches == ["Apple"]

    def test_at_least_three_characters(self, client, securities):
        assert client.get("/api/v1/securities/search", params={"q": "ap"}).status_code == 422
        assert securities.searches == []

    def test_market_data_down(self, client, securities):
        securities.down = True
        response = client.get("/api/v1/securities/search", params={"q": "Apple"})
        assert response.status_code == 503


class TestResolve:
    def test_a_bond(self, client, securities):
        response = client.get(f"/api/v1/securities/{BOND}")
        assert response.status_code == 200
        body = response.json()
        assert (body["asset_class"], body["bond"]["coupon"], body["listing"]) == ("bond", 4.0, None)
        assert body["bond"]["maturity"] == "2028-07-12"

    def test_a_chosen_listing_is_passed_on(self, client, securities):
        client.get(f"/api/v1/securities/{BOND}", params={"symbol": "DB.F"})
        assert securities.resolves == [(BOND, "DB.F")]

    def test_lower_case_is_fine(self, client, securities):
        assert client.get(f"/api/v1/securities/{BOND.lower()}").status_code == 200
        assert securities.resolves == [(BOND, None)]

    def test_unknown(self, client):
        assert client.get(f"/api/v1/securities/{APPLE}").status_code == 404

    def test_invalid_isin(self, client, securities):
        assert client.get("/api/v1/securities/DE0007164601").status_code == 422
        assert securities.resolves == []

    def test_market_data_down(self, client, securities):
        securities.down = True
        assert client.get(f"/api/v1/securities/{BOND}").status_code == 503


def test_without_nats_there_is_no_directory():
    with TestClient(create_app(SETTINGS)) as c:
        assert c.get("/api/v1/securities/search", params={"q": "Apple"}).status_code == 503
