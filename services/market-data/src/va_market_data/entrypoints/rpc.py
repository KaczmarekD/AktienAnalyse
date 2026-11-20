"""Request/Reply von market-data (D2.1): Wertpapiere suchen und aufloesen fuer das web-api.

Eine unbekannte ISIN ist eine leere Antwort (das web-api macht daraus 404), eine falsche
Pruefziffer der Fehler ``invalid``. Die Suche schreibt nichts, die Aufloesung speichert Wertpapier,
Stammdaten und Listings im Schema ``market_data``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

from va_contracts.rpc.v1 import (
    SECURITIES_RESOLVE,
    SECURITIES_SEARCH,
    RpcErrorV1,
    SecurityResolveReplyV1,
    SecurityResolveRequestV1,
    SecuritySearchReplyV1,
    SecuritySearchRequestV1,
)
from va_contracts.securities import SecurityHitV1

from .mapping import listing_v1, security_v1

if TYPE_CHECKING:
    from collections.abc import Callable

    from va_contracts.rpc.v1 import RpcReplyV1, RpcSpec

    from ..application.securities import ResolvedSecurity
    from ..domain.securities import SecurityHit


class Securities(Protocol):
    def search(self, query: str) -> list[SecurityHit]: ...

    def resolve(self, isin: str, symbol: str | None = None) -> ResolvedSecurity | None: ...


def handlers(securities: Securities) -> dict[RpcSpec[Any, Any], Callable[[Any], RpcReplyV1]]:
    def search(request: SecuritySearchRequestV1) -> SecuritySearchReplyV1:
        return SecuritySearchReplyV1(
            hits=[
                SecurityHitV1(
                    isin=hit.isin,
                    name=hit.name,
                    asset_class=hit.asset_class,
                    listings=[listing_v1(listing) for listing in hit.listings],
                    source=hit.source,
                )
                for hit in securities.search(request.query)
            ]
        )

    def resolve(request: SecurityResolveRequestV1) -> SecurityResolveReplyV1:
        try:
            resolved = securities.resolve(request.isin, request.symbol)
        except ValueError as e:
            return SecurityResolveReplyV1(error=RpcErrorV1(code="invalid", message=str(e)))
        return SecurityResolveReplyV1(security=None if resolved is None else security_v1(resolved))

    return {SECURITIES_SEARCH: search, SECURITIES_RESOLVE: resolve}
