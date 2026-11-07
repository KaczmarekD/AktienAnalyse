"""``/securities``: Wertpapiere suchen und aufloesen (D2.1, WP-02, WP-03).

Beides beantwortet market-data per Request/Reply. Ohne NATS oder ohne market-data antworten die
Endpunkte mit 503. ``GET /securities/{isin}`` speichert bei market-data Stammdaten und Listings
(keine Daten eines Nutzers); ein zweiter Aufruf aendert nichts mehr.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request

from va_contracts.securities import valid_isin

from ..models import Security, SecurityHit
from ..ports import MarketDataUnavailable, SecurityDirectory
from .deps import NOT_FOUND, not_found

router = APIRouter(tags=["securities"])

UNAVAILABLE: dict[int | str, dict[str, Any]] = {
    503: {"description": "market-data nicht erreichbar"}
}


def _directory(request: Request) -> SecurityDirectory:
    directory = getattr(request.app.state, "securities", None)
    if directory is None:
        raise MarketDataUnavailable("market-data")
    return directory


Directory = Annotated[SecurityDirectory, Depends(_directory)]


@router.get("/securities/search", responses=UNAVAILABLE)
def search_securities(
    directory: Directory,
    q: Annotated[str, Query(min_length=3, max_length=100, description="ISIN, WKN, Name, Symbol")],
) -> list[SecurityHit]:
    """Sucht in den eigenen Wertpapieren, bei OpenFIGI (ISIN, WKN) und bei Yahoo (Text)."""
    return [SecurityHit.model_validate(hit.model_dump()) for hit in directory.search(q)]


@router.get("/securities/{isin}", responses={**NOT_FOUND, **UNAVAILABLE})
def get_security(
    directory: Directory,
    isin: Annotated[str, Path(min_length=12, max_length=12)],
    symbol: Annotated[str | None, Query(max_length=40)] = None,
) -> Security:
    """Stammdaten und Listings; ``symbol`` waehlt ein anderes Listing als Xetra."""
    isin = isin.upper()
    if not valid_isin(isin):
        raise HTTPException(status_code=422, detail="Keine gueltige ISIN (Form oder Pruefziffer).")
    security = directory.resolve(isin, symbol)
    if security is None:
        raise not_found("Wertpapier")
    return Security.model_validate(security.model_dump())
