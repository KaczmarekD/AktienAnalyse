"""Tageskurse im Schema ``market_data`` (D2.3, Port ``PriceStore``).

Ein Abruf ist eine Transaktion: ``price_run`` mit Ende und Ergebnis, dazu Kurse und
Waehrungskurse. Ein Kurs je ISIN, Quelle und Tag, ein Waehrungskurs je Waehrung, Tag und Quelle;
ein zweiter Abruf desselben Tages fuegt nichts mehr an (``ON CONFLICT DO NOTHING``).
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from typing import TYPE_CHECKING

from sqlalchemy import insert, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.dialects.postgresql import insert as pg_insert

from ...domain.prices import DailyClose, FxDaily
from .models import DailyClose as DailyCloseRow
from .models import FxDaily as FxDailyRow
from .models import PriceRun

if TYPE_CHECKING:
    from datetime import datetime

    from sqlalchemy import Engine


class PostgresPriceStore:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def write_prices(
        self,
        *,
        source: str,
        started_at: datetime,
        finished_at: datetime,
        status: str,
        closes: Sequence[DailyClose],
        fx: Sequence[FxDaily],
    ) -> int:
        with self._engine.begin() as conn:
            run_id = conn.execute(
                insert(PriceRun)
                .values(
                    source=source, started_at=started_at, finished_at=finished_at, status=status
                )
                .returning(PriceRun.id)
            ).scalar_one()
            for close in closes:
                conn.execute(
                    pg_insert(DailyCloseRow)
                    .values(
                        isin=close.isin,
                        symbol=close.symbol,
                        source=source,
                        trade_date=close.trade_date,
                        close=close.close,
                        currency=close.currency,
                        quote_currency=close.quote_currency,
                        price_run_id=run_id,
                    )
                    .on_conflict_do_nothing(index_elements=["isin", "source", "trade_date"])
                )
            for rate in fx:
                conn.execute(
                    pg_insert(FxDailyRow)
                    .values(
                        currency=rate.currency,
                        trade_date=rate.trade_date,
                        rate_to_eur=rate.rate_to_eur,
                        source=source,
                        price_run_id=run_id,
                    )
                    .on_conflict_do_nothing(index_elements=["currency", "trade_date", "source"])
                )
        return int(run_id)

    def known_currencies(self, symbols: Collection[str]) -> dict[str, str]:
        """Die Notierung der juengsten Kurse je Symbol (spart den Abruf bei Yahoo). Nicht die
        gespeicherte Hauptwaehrung: Ein Kurs in Pence bliebe sonst ab dem zweiten Tag ungeteilt."""
        if not symbols:
            return {}
        stmt = (
            select(DailyCloseRow.symbol, DailyCloseRow.quote_currency)
            .where(
                DailyCloseRow.symbol.in_(list(symbols)), DailyCloseRow.quote_currency.is_not(None)
            )
            .order_by(DailyCloseRow.symbol, DailyCloseRow.trade_date.desc())
            .ext(distinct_on(DailyCloseRow.symbol))
        )
        with self._engine.connect() as conn:
            return {
                symbol: currency for symbol, currency in conn.execute(stmt) if symbol and currency
            }

    def latest_closes(self, isins: Collection[str]) -> dict[str, DailyClose]:
        """Der juengste Kurs je ISIN, ueber alle Quellen."""
        if not isins:
            return {}
        stmt = (
            select(
                DailyCloseRow.isin,
                DailyCloseRow.symbol,
                DailyCloseRow.trade_date,
                DailyCloseRow.close,
                DailyCloseRow.currency,
                DailyCloseRow.quote_currency,
            )
            .where(DailyCloseRow.isin.in_(list(isins)))
            .order_by(DailyCloseRow.isin, DailyCloseRow.trade_date.desc(), DailyCloseRow.id.desc())
            .ext(distinct_on(DailyCloseRow.isin))
        )
        with self._engine.connect() as conn:
            return {
                row.isin: DailyClose(
                    row.isin,
                    row.symbol,
                    row.trade_date,
                    row.close,
                    row.currency,
                    row.quote_currency,
                )
                for row in conn.execute(stmt)
            }
