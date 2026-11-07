"""Die eigenen Wertpapiere im Schema ``market_data`` (D2.1, Port ``SecurityCatalog``).

Nur ``INSERT`` und ``SELECT``: Stammdaten aendern sich als neue Zeile je Quelle, und nur, wenn sich
ihr Inhalt aendert. Gueltig ist die juengste. Ein Listing, dessen Symbol schon einem anderen
Wertpapier gehoert, wird nicht angelegt (``ON CONFLICT DO NOTHING``).
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Any

from sqlalchemy import text as sql
from sqlalchemy.dialects.postgresql import insert

from ...domain.securities import BondTerms, Listing, SecurityHit, SecurityMaster
from .models import Listing as ListingRow
from .models import Security, SecurityMasterVersion

if TYPE_CHECKING:
    from datetime import datetime

    from sqlalchemy import Connection, Engine

_LATEST_MASTER = """
SELECT payload FROM market_data.security_master
WHERE isin = :isin ORDER BY id DESC LIMIT 1
"""

_LATEST_OF_SOURCE = """
SELECT payload FROM market_data.security_master
WHERE isin = :isin AND source = :source ORDER BY id DESC LIMIT 1
"""

_LISTINGS = """
SELECT symbol, ticker, exchange, currency FROM market_data.listing
WHERE isin = :isin ORDER BY id
"""

# Name aus den juengsten Stammdaten, Symbol oder Ticker eines Listings, Anfang der ISIN
_FIND = r"""
SELECT s.isin FROM market_data.security s
WHERE s.isin ILIKE :prefix ESCAPE '\'
   OR EXISTS (
        SELECT 1 FROM market_data.listing l
        WHERE l.isin = s.isin
          AND (l.symbol ILIKE :pattern ESCAPE '\' OR l.ticker ILIKE :pattern ESCAPE '\'))
   OR (SELECT m.payload ->> 'name' FROM market_data.security_master m
       WHERE m.isin = s.isin ORDER BY m.id DESC LIMIT 1) ILIKE :pattern ESCAPE '\'
ORDER BY s.id
LIMIT :limit
"""


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def master_payload(master: SecurityMaster) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "name": master.name,
        "asset_class": master.asset_class,
        "currency": master.currency,
        "lei": master.lei,
        "cfi": master.cfi,
    }
    if master.bond is not None:
        bond = master.bond
        payload["bond"] = {
            "coupon": bond.coupon,
            "maturity": bond.maturity.isoformat() if bond.maturity else None,
            "denomination": bond.denomination,
            "seniority": bond.seniority,
            "floating": bond.floating,
        }
    return payload


def master_from_payload(isin: str, source: str, payload: dict[str, Any]) -> SecurityMaster:
    bond = payload.get("bond")
    terms = None
    if isinstance(bond, dict):
        maturity = bond.get("maturity")
        terms = BondTerms(
            coupon=bond.get("coupon"),
            maturity=date.fromisoformat(maturity) if maturity else None,
            denomination=bond.get("denomination"),
            seniority=bond.get("seniority"),
            floating=bool(bond.get("floating")),
        )
    return SecurityMaster(
        isin=isin,
        name=payload.get("name") or isin,
        asset_class=payload.get("asset_class") or "other",
        currency=payload.get("currency"),
        lei=payload.get("lei"),
        cfi=payload.get("cfi"),
        bond=terms,
        source=source,
    )


class PostgresSecurityCatalog:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def save(self, master: SecurityMaster, listings: tuple[Listing, ...], *, at: datetime) -> None:
        payload = master_payload(master)
        with self._engine.begin() as conn:
            conn.execute(
                insert(Security)
                .values(isin=master.isin, asset_class=master.asset_class, first_seen_at=at)
                .on_conflict_do_nothing(index_elements=["isin"])
            )
            latest = conn.execute(
                sql(_LATEST_OF_SOURCE), {"isin": master.isin, "source": master.source}
            ).scalar()
            if latest != payload:
                conn.execute(
                    insert(SecurityMasterVersion).values(
                        isin=master.isin, source=master.source, payload=payload, fetched_at=at
                    )
                )
            for listing in listings:
                conn.execute(
                    insert(ListingRow)
                    .values(
                        isin=master.isin,
                        symbol=listing.symbol,
                        ticker=listing.ticker,
                        exchange=listing.exchange,
                        currency=listing.currency,
                        first_seen_at=at,
                    )
                    .on_conflict_do_nothing()
                )

    def get(self, isin: str) -> SecurityHit | None:
        with self._engine.connect() as conn:
            return self._hit(conn, isin)

    def master(self, isin: str) -> SecurityMaster | None:
        with self._engine.connect() as conn:
            row = conn.execute(
                sql(
                    "SELECT source, payload FROM market_data.security_master"
                    " WHERE isin = :isin ORDER BY id DESC LIMIT 1"
                ),
                {"isin": isin},
            ).first()
        return None if row is None else master_from_payload(isin, row.source, row.payload)

    def find(self, text: str, limit: int) -> list[SecurityHit]:
        needle = _escape_like(text.strip())
        if not needle:
            return []
        with self._engine.connect() as conn:
            isins = conn.execute(
                sql(_FIND),
                {"prefix": f"{needle}%", "pattern": f"%{needle}%", "limit": limit},
            ).scalars()
            return [hit for isin in list(isins) if (hit := self._hit(conn, isin)) is not None]

    @staticmethod
    def _hit(conn: Connection, isin: str) -> SecurityHit | None:
        asset_class = conn.execute(
            sql("SELECT asset_class FROM market_data.security WHERE isin = :isin"),
            {"isin": isin},
        ).scalar()
        if asset_class is None:
            return None
        payload = conn.execute(sql(_LATEST_MASTER), {"isin": isin}).scalar() or {}
        listings = tuple(
            Listing(symbol=r.symbol, ticker=r.ticker, exchange=r.exchange, currency=r.currency)
            for r in conn.execute(sql(_LISTINGS), {"isin": isin})
        )
        return SecurityHit(
            isin=isin,
            name=payload.get("name") or isin,
            # Die juengsten Stammdaten gelten; security haelt nur die Klasse der ersten Speicherung
            asset_class=payload.get("asset_class") or asset_class,
            listings=listings,
            source="catalog",
        )
