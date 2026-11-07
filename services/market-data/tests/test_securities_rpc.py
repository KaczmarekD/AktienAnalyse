"""Request/Reply von market-data (D2.1): Suche und Aufloesung fuer das web-api.

Die Handler bilden den Anwendungsfall auf die Contracts ab. Eine unbekannte ISIN ist eine leere
Antwort, eine ungueltige ein Fehler ``invalid``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from va_contracts.rpc.v1 import (
    SECURITIES_RESOLVE,
    SECURITIES_SEARCH,
    SecurityResolveReplyV1,
    SecurityResolveRequestV1,
    SecuritySearchReplyV1,
    SecuritySearchRequestV1,
)
from va_market_data.application.securities import ResolvedSecurity
from va_market_data.domain.securities import Listing, SecurityHit, SecurityMaster
from va_market_data.entrypoints.rpc import handlers

APPLE = "US0378331005"


@dataclass
class FakeService:
    resolved: ResolvedSecurity | None = None
    error: Exception | None = None
    calls: list[tuple[str, str | None]] = field(default_factory=list)

    def search(self, query: str) -> list[SecurityHit]:
        return [
            SecurityHit(
                isin=APPLE,
                name="APPLE INC",
                asset_class="equity",
                listings=(Listing(symbol="APC.DE", ticker="APC", exchange="GY"),),
                source="openfigi",
            )
        ]

    def resolve(self, isin: str, symbol: str | None = None) -> ResolvedSecurity | None:
        self.calls.append((isin, symbol))
        if self.error:
            raise self.error
        return self.resolved


def test_search():
    reply = handlers(FakeService())[SECURITIES_SEARCH](SecuritySearchRequestV1(query="Apple"))
    assert isinstance(reply, SecuritySearchReplyV1)
    [hit] = reply.hits
    assert (hit.isin, hit.asset_class, hit.listings[0].symbol) == (APPLE, "equity", "APC.DE")


def test_resolve():
    listing = Listing(symbol="APC.DE", ticker="APC", exchange="GY")
    service = FakeService(
        resolved=ResolvedSecurity(
            master=SecurityMaster(isin=APPLE, name="APPLE INC", asset_class="equity"),
            listings=(listing,),
            listing=listing,
        )
    )
    request = SecurityResolveRequestV1(isin=APPLE, symbol="APC.DE")
    reply = handlers(service)[SECURITIES_RESOLVE](request)
    assert isinstance(reply, SecurityResolveReplyV1)
    assert reply.security is not None
    assert (reply.security.name, reply.security.listing.symbol) == ("APPLE INC", "APC.DE")  # type: ignore[union-attr]
    assert service.calls == [(APPLE, "APC.DE")]


def test_unknown_is_empty():
    reply = handlers(FakeService())[SECURITIES_RESOLVE](SecurityResolveRequestV1(isin=APPLE))
    assert isinstance(reply, SecurityResolveReplyV1)
    assert (reply.security, reply.error) == (None, None)


def test_a_wrong_check_digit_is_invalid():
    service = FakeService(error=ValueError("Keine gueltige ISIN"))
    reply = handlers(service)[SECURITIES_RESOLVE](SecurityResolveRequestV1(isin="DE0007164601"))
    assert reply.error is not None
    assert reply.error.code == "invalid"
