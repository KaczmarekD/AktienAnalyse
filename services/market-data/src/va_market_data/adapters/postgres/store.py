"""``SnapshotStore`` ueber PostgreSQL (Schema ``market_data``), vorher Teil des BatchRecorders.

Jede Methode ist eine eigene, sofort committete Transaktion: Ein Absturz nach Titel 80
verliert nichts von dem, was bis dahin abgerufen wurde.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Collection, Sequence
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy.exc import InterfaceError, OperationalError
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from va_contracts.events.v1 import FundamentalsV1
from va_platform.db import session_scope

from ...application.fetch import success_share
from ...domain.history import (
    RECENT_HISTORY_DAYS,
    HistoryState,
    daily_price_bars,
    daily_share_counts,
)
from .repository import MarketDataRepository, UniverseMember, snapshot_values

if TYPE_CHECKING:
    import pandas as pd
    from sqlalchemy import Engine
    from sqlalchemy.orm import Session

    from ...domain.coverage import CoverageItem as Coverage
    from ...domain.fundamentals import Fundamentals
    from ...domain.universe import Ticker

log = logging.getLogger(__name__)

# Ein Abruf vom selben Tag wird nur wiederverwendet, wenn mindestens dieser Anteil
# der Ticker eine Marktkapitalisierung hat - sonst liefert ein Re-Run nach einem
# yfinance-Ausfall weiter die kaputten Daten.
MIN_REUSE_SUCCESS_SHARE = 0.8

# Voruebergehende DB-Stoerungen (Verbindungsabbruch, NAS-I/O) - kein Retry bei Datenfehlern
TRANSIENT_DB_ERRORS = (OperationalError, InterfaceError)


class _OptionalWrites:
    """Schreibt Zusatzdaten eines Titels (ADR-0010) je in einem Savepoint.

    Ein Fehler kostet nur diese Daten: Der Titel bleibt in Report und Datenbank.
    Voruebergehende DB-Stoerungen laufen weiter in den Retry der ganzen Transaktion.
    """

    def __init__(self, session: Session, symbol: str) -> None:
        self._session = session
        self._symbol = symbol

    def write(self, label: str, write: Callable[[], object]) -> None:
        try:
            with self._session.begin_nested():
                write()
        except TRANSIENT_DB_ERRORS:
            raise
        except Exception:
            log.warning(
                "%s fuer %s nicht gespeichert - der Titel bleibt",
                label,
                self._symbol,
                exc_info=True,
            )


class PostgresSnapshotStore:
    def __init__(self, engine: Engine, *, provider: str, provider_version: str | None) -> None:
        self._engine = engine
        self._provider = provider
        self._provider_version = provider_version

    def find_reusable_fetch(self, day: date, symbols: Collection[str]) -> int | None:
        with session_scope(self._engine) as s:
            fetch_run = MarketDataRepository(s).get_reusable_fetch_run(
                day, MIN_REUSE_SUCCESS_SHARE, symbols
            )
            return fetch_run.id if fetch_run else None

    def history_state(self, symbols: Collection[str]) -> dict[str, HistoryState]:
        """Bis wann die Zeitreihen je Titel gespeichert sind; fehlt ein Titel, gilt alles.

        Dazu die Aktienanzahl und die Kurse der letzten ``RECENT_HISTORY_DAYS`` Tage fuer
        Netto-Emission (F2.2) und Momentum (F2.3).
        """
        since = date.today() - timedelta(days=RECENT_HISTORY_DAYS)
        with session_scope(self._engine) as s:
            repo = MarketDataRepository(s)
            last_share = repo.get_last_share_dates(symbols)
            last_price = repo.get_last_price_dates(symbols)
            splits = repo.get_price_split_days(symbols)
            recent_shares = repo.get_share_counts_since(symbols, since)
            recent_prices = repo.get_price_bars_since(symbols, since)
        return {
            symbol: HistoryState(
                last_share_date=last_share.get(symbol),
                last_price_date=last_price.get(symbol),
                price_split_days=splits.get(symbol, frozenset()),
                stored_shares=recent_shares.get(symbol, {}),
                stored_prices=recent_prices.get(symbol, {}),
            )
            for symbol in last_share.keys() | last_price.keys()
        }

    def load_snapshots(self, fetch_run_id: int, symbols: Collection[str]) -> pd.DataFrame:
        with session_scope(self._engine) as s:
            return MarketDataRepository(s).get_snapshots_df(fetch_run_id, symbols)

    def start_fetch(self, tickers: Sequence[Ticker], source: str, as_of: date | None = None) -> int:
        with session_scope(self._engine) as s:
            repo = MarketDataRepository(s)
            fetch_run_id = repo.write_fetch_run_start(
                provider=self._provider,
                provider_version=self._provider_version,
                universe_source=source,
                universe_as_of=as_of,
                universe_size=len(tickers),
            )
            repo.write_universe(
                fetch_run_id,
                [UniverseMember(t.symbol, t.index, t.name, source) for t in tickers],
            )
            repo.write_isins({t.symbol: t.isin for t in tickers if t.isin})
            return fetch_run_id

    @retry(
        retry=retry_if_exception_type(TRANSIENT_DB_ERRORS),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=5),
        reraise=True,
    )
    def record_fundamentals(self, fetch_run_id: int, fund: Fundamentals) -> None:
        """Ein Titel = eine Transaktion; ein Retry wiederholt sie vollstaendig."""
        self._record(fetch_run_id, fund, role="universe", isin=None)

    @retry(
        retry=retry_if_exception_type(TRANSIENT_DB_ERRORS),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=5),
        reraise=True,
    )
    def record_covered(self, fetch_run_id: int, fund: Fundamentals, isin: str | None) -> None:
        """Ein Titel der Abdeckung (D2.2): ``role = 'coverage'``, dazu seine ISIN."""
        self._record(fetch_run_id, fund, role="coverage", isin=isin)

    def coverage(self) -> list[Coverage]:
        with session_scope(self._engine) as s:
            return MarketDataRepository(s).get_coverage()

    def universe_keys(self) -> tuple[set[str], set[str]]:
        """D4.6: Symbole und ISINs des juengsten Universums."""
        with session_scope(self._engine) as s:
            return MarketDataRepository(s).get_latest_universe_keys()

    def record_coverage_fetch(self, fund: Fundamentals, isin: str) -> None:
        """D4.6: ein sofort geholter Titel als ganzes ``FundamentalsV1``."""
        payload = FundamentalsV1.from_flat(fund.to_flat_dict()).model_dump(mode="json")
        with session_scope(self._engine) as s:
            MarketDataRepository(s).write_coverage_fetch(
                isin=isin,
                symbol=fund.symbol,
                fetched_at=fund.provenance.fetched_at or datetime.now(UTC),
                payload=payload,
            )

    def coverage_as_of(self) -> datetime | None:
        with session_scope(self._engine) as s:
            return MarketDataRepository(s).get_coverage_as_of()

    def write_coverage(self, items: Sequence[Coverage], *, source: str, at: datetime) -> bool:
        with session_scope(self._engine) as s:
            return MarketDataRepository(s).write_coverage(items, source=source, at=at)

    def covered_snapshots(self, fetch_run_id: int) -> pd.DataFrame:
        with session_scope(self._engine) as s:
            return MarketDataRepository(s).get_snapshots_df(fetch_run_id, role="coverage")

    def _record(
        self, fetch_run_id: int, fund: Fundamentals, *, role: str, isin: str | None
    ) -> None:
        with session_scope(self._engine) as s:
            repo = MarketDataRepository(s)
            instrument_id = repo.get_or_create_instruments([fund.symbol])[fund.symbol]
            if isin:
                repo.write_isins({fund.symbol: isin})
            repo.write_snapshot(fetch_run_id, instrument_id, snapshot_values(fund), role=role)
            fetched_at = fund.provenance.fetched_at
            if fund.raw is None or fetched_at is None:
                return
            raw = fund.raw
            repo.write_raw_info(fetch_run_id, instrument_id, raw.info, fetched_at)
            repo.write_statements(
                fetch_run_id,
                instrument_id,
                raw.statements,
                currency=fund.identity.financial_currency,
                fetched_at=fetched_at,
            )
            # Zusatzdaten (ADR-0010) je in einem Savepoint
            optional = _OptionalWrites(s, fund.symbol)
            optional.write(
                "Konsens",
                lambda: repo.write_consensus(
                    fetch_run_id, instrument_id, raw.consensus, fetched_at
                ),
            )
            optional.write(
                "Quartale",
                lambda: repo.write_statements(
                    fetch_run_id,
                    instrument_id,
                    raw.quarterly,
                    currency=fund.identity.financial_currency,
                    fetched_at=fetched_at,
                    frequency="quarterly",
                ),
            )
            optional.write(
                "Aktienanzahl",
                lambda: repo.write_share_counts(
                    fetch_run_id,
                    instrument_id,
                    daily_share_counts(raw.shares),
                    fetched_at=fetched_at,
                ),
            )
            optional.write(
                "Kurse",
                lambda: repo.write_price_bars(
                    fetch_run_id,
                    instrument_id,
                    daily_price_bars(raw.prices, fetched_at=fetched_at),
                    fetched_at=fetched_at,
                ),
            )
            reporting_ccy = fund.identity.financial_currency
            trading_ccy = fund.identity.currency
            fx = fund.provenance.statement_fx
            if reporting_ccy and trading_ccy and reporting_ccy != trading_ccy and fx is not None:
                repo.write_fx_rate(fetch_run_id, reporting_ccy, trading_ccy, fx, fetched_at)

    def instrument_ids(self, symbols: Collection[str]) -> dict[str, int]:
        with session_scope(self._engine) as s:
            return MarketDataRepository(s).get_or_create_instruments(symbols)

    def finish_fetch(self, fetch_run_id: int, df: pd.DataFrame) -> None:
        ok_count = int(df["market_cap"].notna().sum()) if "market_cap" in df.columns else 0
        with session_scope(self._engine) as s:
            MarketDataRepository(s).write_fetch_run_finish(
                fetch_run_id, ok_count=ok_count, success_share=success_share(df)
            )
