"""Kopien der Marktdaten im Schema ``portfolio`` (D3.4, Port ``MarketStore``).

Nur ``INSERT`` und ``SELECT``. Gelesen wird je ISIN bzw. Waehrung die juengste Zeile
(``DISTINCT ON``): Stammdaten nach ``as_of``, Kurse und Waehrungskurse nach Handelstag, bei
Gleichstand die zuletzt empfangene.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import insert, text

from va_platform.db import session_scope

from ...domain.valuation import Market, Quote, SecurityInfo
from .models import FxView, PriceView, SecurityView

if TYPE_CHECKING:
    from collections.abc import Collection, Sequence
    from datetime import date, datetime

    from sqlalchemy import Engine

    from ...application.market import FxRate, SecurityCopy

_SECURITIES = """
SELECT DISTINCT ON (isin) isin, name, asset_class, currency
FROM portfolio.security_view WHERE isin = ANY(:isins)
ORDER BY isin, as_of DESC, id DESC
"""
_QUOTES = """
SELECT DISTINCT ON (isin) isin, trade_date, close, currency, percent_of_par, source, symbol
FROM portfolio.price_view WHERE isin = ANY(:isins)
ORDER BY isin, trade_date DESC, id DESC
"""
_FX = """
SELECT DISTINCT ON (currency) currency, rate_to_eur
FROM portfolio.fx_view
ORDER BY currency, trade_date DESC, id DESC
"""


class PostgresMarketStore:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def record_securities(
        self, copies: Sequence[SecurityCopy], *, as_of: date, at: datetime
    ) -> None:
        if not copies:
            return
        with session_scope(self._engine) as session:
            session.execute(
                insert(SecurityView),
                [
                    {
                        "isin": copy.info.isin,
                        "as_of": as_of,
                        "name": copy.info.name,
                        "asset_class": copy.info.asset_class,
                        "currency": copy.info.currency,
                        "payload": copy.payload,
                        "received_at": at,
                    }
                    for copy in copies
                ],
            )

    def record_prices(
        self, quotes: Sequence[Quote], rates: Sequence[FxRate], *, at: datetime
    ) -> None:
        with session_scope(self._engine) as session:
            if quotes:
                session.execute(
                    insert(PriceView),
                    [
                        {
                            "isin": q.isin,
                            "trade_date": q.trade_date,
                            "close": q.close,
                            "currency": q.currency,
                            "percent_of_par": q.percent_of_par,
                            "source": q.source,
                            "symbol": q.symbol,
                            "received_at": at,
                        }
                        for q in quotes
                    ],
                )
            if rates:
                session.execute(
                    insert(FxView),
                    [
                        {
                            "currency": r.currency,
                            "trade_date": r.trade_date,
                            "rate_to_eur": r.rate_to_eur,
                            "received_at": at,
                        }
                        for r in rates
                    ],
                )

    def market(self, isins: Collection[str]) -> Market:
        wanted = sorted(set(isins))
        with self._engine.connect() as conn:
            securities = conn.execute(text(_SECURITIES), {"isins": wanted}).all() if wanted else []
            quotes = conn.execute(text(_QUOTES), {"isins": wanted}).all() if wanted else []
            fx = conn.execute(text(_FX)).all()
        return Market(
            securities={
                r.isin: SecurityInfo(r.isin, r.name, r.asset_class, r.currency) for r in securities
            },
            quotes={
                r.isin: Quote(
                    isin=r.isin,
                    trade_date=r.trade_date,
                    close=r.close,
                    currency=r.currency,
                    percent_of_par=r.percent_of_par,
                    source=r.source,
                    symbol=r.symbol,
                )
                for r in quotes
            },
            fx={r.currency: r.rate_to_eur for r in fx},
        )
