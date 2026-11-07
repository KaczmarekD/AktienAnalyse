"""Wertpapiere zwischen market-data und web-api (D2.1, docs/architecture/depot/wertpapiere.md).

Ein Wertpapier ist ueber die ISIN eindeutig (WP-01), ein Listing ist sein Handel an einem
Boersenplatz mit Symbol. Die Modelle nutzen Request/Reply (``rpc.va.marketdata.securities.*``)
und spaeter das Event ``marketdata.securities.updated``. Aenderungen nur additiv.

``valid_isin`` prueft die Pruefziffer; die Muster der Modelle pruefen nur die Form, damit
market-data eine falsche Pruefziffer als Fehler ``invalid`` beantworten kann.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from pydantic import Field

from .base import Contract

AssetClass = Literal["equity", "etf", "bond", "other"]
ISIN_PATTERN = r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$"
IsinStr = Annotated[str, Field(pattern=ISIN_PATTERN)]


def valid_isin(value: str) -> bool:
    """Form und Pruefziffer (ISO 6166): Buchstaben als Zahlen 10 bis 35, dann Luhn."""
    if len(value) != 12 or not value[:2].isalpha() or not value[:2].isupper():
        return False
    if not value[-1].isdigit() or not all(c.isdigit() or ("A" <= c <= "Z") for c in value):
        return False
    digits = "".join(str(int(c, 36)) for c in value[:-1])
    total = 0
    for position, char in enumerate(reversed(digits)):
        n = int(char)
        if position % 2 == 0:  # von rechts jede zweite Stelle verdoppeln, beginnend mit der ersten
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return (10 - total % 10) % 10 == int(value[-1])


class ListingV1(Contract):
    """Handel an einem Boersenplatz. ``symbol`` ist das Yahoo-Symbol, falls es eines gibt."""

    symbol: str | None = None
    ticker: str | None = None
    exchange: str | None = None  # OpenFIGI-Code (GY = Xetra) oder Boerse bei Yahoo
    currency: str | None = None


class SecurityHitV1(Contract):
    """Ein Treffer der Suche. Treffer der Yahoo-Suche haben keine ISIN."""

    isin: str | None
    name: str
    asset_class: AssetClass
    listings: list[ListingV1] = Field(default_factory=list)
    source: str  # catalog, openfigi oder yahoo


class BondTermsV1(Contract):
    """Ausstattung einer Anleihe aus ESMA FIRDS; Kupontermine und Zinsmethode fehlen dort."""

    coupon: float | None = None  # in Prozent
    maturity: date | None = None
    denomination: float | None = None  # Stueckelung
    seniority: str | None = None  # FIRDS-Code, z. B. SNDB (nachrangig nicht)
    floating: bool = False  # variable Verzinsung laut CFI-Code


class SecurityV1(Contract):
    """Ein aufgeloestes Wertpapier mit Stammdaten, Listings und dem gewaehlten Listing."""

    isin: IsinStr
    name: str
    asset_class: AssetClass
    currency: str | None = None
    lei: str | None = None
    cfi: str | None = None
    bond: BondTermsV1 | None = None
    listings: list[ListingV1] = Field(default_factory=list)
    # Fuer den Datenabruf: gewaehlt, sonst Xetra, sonst Heimatboerse
    listing: ListingV1 | None = None


__all__ = [
    "ISIN_PATTERN",
    "AssetClass",
    "BondTermsV1",
    "IsinStr",
    "ListingV1",
    "SecurityHitV1",
    "SecurityV1",
    "valid_isin",
]
