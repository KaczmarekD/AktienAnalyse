"""Brücke zwischen Batch-Pipeline und Repositories.

Jede Methode ist eine eigene, sofort committete Transaktion: Ein Absturz nach
Titel 80 verliert nichts von dem, was bis dahin abgerufen wurde.
"""

from __future__ import annotations

import logging
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import asdict
from datetime import date
from typing import TYPE_CHECKING, Any

import pandas as pd
from sqlalchemy.exc import InterfaceError, OperationalError
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from .. import __version__
from ..data_fetcher import PROVIDER, provider_version, success_share
from .engine import session_scope
from .repositories.market_data import SNAPSHOT_COLUMNS, MarketDataRepository, UniverseMember
from .repositories.reporting import ReportingRepository
from .repositories.runs import RunRepository
from .repositories.scoring import FactorScoreRow, ScoreRow, ScoringRepository
from .serialization import to_python

if TYPE_CHECKING:
    from sqlalchemy import Engine

    from ..fundamentals import Fundamentals
    from ..reporting import ReportArtifacts
    from ..scoring import ScoringConfig
    from ..universe import Ticker
    from .log_handler import LogEntry

log = logging.getLogger(__name__)

# Ein Abruf vom selben Tag wird nur wiederverwendet, wenn mindestens dieser Anteil
# der Ticker eine Marktkapitalisierung hat - sonst liefert ein Re-Run nach einem
# yfinance-Ausfall weiter die kaputten Daten.
MIN_REUSE_SUCCESS_SHARE = 0.8

# Voruebergehende DB-Stoerungen (Verbindungsabbruch, NAS-I/O) - kein Retry bei Datenfehlern
_TRANSIENT_DB_ERRORS = (OperationalError, InterfaceError)


def snapshot_row(
    flat: Mapping[Any, Any], errors: Iterable[str], *, drop_unknown: bool = False
) -> dict[str, Any]:
    """Flaches Dict (``to_flat_dict``/Altdatei-Zeile) -> Spalten von ``fundamental_snapshot``.

    ``drop_unknown`` nur fuer Altdateien: im Live-Pfad soll eine neue Kennzahl ohne
    Migration auffallen (``write_snapshot`` lehnt sie ab).
    """
    row = {str(k): v for k, v in flat.items() if k not in {"symbol", "errors"}}
    row["index_name"] = row.pop("index", None)
    row["errors"] = [e for e in errors if e]
    row["fetch_ok"] = to_python(row.get("market_cap")) is not None
    if drop_unknown:
        row = {k: v for k, v in row.items() if k in SNAPSHOT_COLUMNS}
    return row


def snapshot_values(fund: Fundamentals) -> dict[str, Any]:
    """``Fundamentals`` -> Spalten von ``market_data.fundamental_snapshot``."""
    return snapshot_row(fund.to_flat_dict(), fund.errors)


def scoring_config_dict(cfg: ScoringConfig) -> dict[str, Any]:
    return asdict(cfg)


class BatchRecorder:
    def __init__(self, engine: Engine, app_version: str = __version__) -> None:
        self._engine = engine
        self._app_version = app_version

    # --- Lauf -----------------------------------------------------------------

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1.5, min=2, max=15),
        reraise=True,
    )
    def start_run(
        self,
        *,
        kind: str,
        dry_run: bool,
        force_refresh: bool,
        universe_mode: str | None,
        settings: dict[str, Any] | None,
    ) -> int:
        with session_scope(self._engine) as s:
            return RunRepository(s).write_run_start(
                kind=kind,
                app_version=self._app_version,
                dry_run=dry_run,
                force_refresh=force_refresh,
                universe_mode=universe_mode,
                settings=settings,
            )

    def finish_run(self, run_id: int, **kwargs: Any) -> None:
        with session_scope(self._engine) as s:
            RunRepository(s).write_run_finish(run_id, **kwargs)

    def record_logs(self, run_id: int, entries: Sequence[LogEntry]) -> None:
        with session_scope(self._engine) as s:
            RunRepository(s).write_logs(run_id, entries)

    # --- Abruf ----------------------------------------------------------------

    def find_reusable_fetch(self, day: date, symbols: Collection[str]) -> int | None:
        with session_scope(self._engine) as s:
            fetch_run = MarketDataRepository(s).get_reusable_fetch_run(
                day, MIN_REUSE_SUCCESS_SHARE, symbols
            )
            return fetch_run.id if fetch_run else None

    def load_snapshots(self, fetch_run_id: int, symbols: Collection[str]) -> pd.DataFrame:
        with session_scope(self._engine) as s:
            return MarketDataRepository(s).get_snapshots_df(fetch_run_id, symbols)

    def start_fetch(self, tickers: Sequence[Ticker], source: str, as_of: date | None = None) -> int:
        with session_scope(self._engine) as s:
            repo = MarketDataRepository(s)
            fetch_run_id = repo.write_fetch_run_start(
                provider=PROVIDER,
                provider_version=provider_version(),
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
        retry=retry_if_exception_type(_TRANSIENT_DB_ERRORS),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=5),
        reraise=True,
    )
    def record_fundamentals(self, fetch_run_id: int, fund: Fundamentals) -> None:
        """Ein Titel = eine Transaktion; ein Retry wiederholt sie vollstaendig."""
        with session_scope(self._engine) as s:
            repo = MarketDataRepository(s)
            instrument_id = repo.get_or_create_instruments([fund.symbol])[fund.symbol]
            repo.write_snapshot(fetch_run_id, instrument_id, snapshot_values(fund))
            fetched_at = fund.provenance.fetched_at
            if fund.raw is None or fetched_at is None:
                return
            repo.write_raw_info(fetch_run_id, instrument_id, fund.raw.info, fetched_at)
            repo.write_consensus(fetch_run_id, instrument_id, fund.raw.consensus, fetched_at)
            repo.write_statements(
                fetch_run_id,
                instrument_id,
                fund.raw.statements,
                currency=fund.identity.financial_currency,
                fetched_at=fetched_at,
            )
            reporting_ccy = fund.identity.financial_currency
            trading_ccy = fund.identity.currency
            fx = fund.provenance.statement_fx
            if reporting_ccy and trading_ccy and reporting_ccy != trading_ccy and fx is not None:
                repo.write_fx_rate(fetch_run_id, reporting_ccy, trading_ccy, fx, fetched_at)

    def finish_fetch(self, fetch_run_id: int, df: pd.DataFrame) -> None:
        ok_count = int(df["market_cap"].notna().sum()) if "market_cap" in df.columns else 0
        with session_scope(self._engine) as s:
            MarketDataRepository(s).write_fetch_run_finish(
                fetch_run_id, ok_count=ok_count, success_share=success_share(df)
            )

    # --- Scoring / Report / Versand -----------------------------------------------

    def record_scoring(
        self, fetch_run_id: int, df_all: pd.DataFrame, scored: pd.DataFrame, cfg: ScoringConfig
    ) -> int:
        """Speichert Scores fuer *alle* Titel - gefilterte mit ``passed_filter=False``."""
        symbols = [str(s) for s in df_all.get("symbol", pd.Series(dtype=str)).dropna()]
        scored_symbols = [str(s) for s in scored.get("symbol", pd.Series(dtype=str)).dropna()]
        with session_scope(self._engine) as s:
            ids = MarketDataRepository(s).get_or_create_instruments([*symbols, *scored_symbols])
            repo = ScoringRepository(s)
            scoring_run_id = repo.write_scoring_run(
                fetch_run_id=fetch_run_id,
                config=scoring_config_dict(cfg),
                app_version=self._app_version,
            )
            results = [_score_row(ids[str(r["symbol"])], r) for r in scored.to_dict("records")]
            passed = set(scored_symbols)
            results += [
                ScoreRow(ids[sym], False, None, None, None, None, None)
                for sym in dict.fromkeys(symbols)
                if sym not in passed
            ]
            repo.write_score_results(scoring_run_id, results)
            repo.write_factor_scores(scoring_run_id, _factor_rows(scored, ids, cfg))
            return scoring_run_id

    def record_report(
        self, run_id: int, scoring_run_id: int | None, report: ReportArtifacts
    ) -> int:
        with session_scope(self._engine) as s:
            return ReportingRepository(s).write_report(
                run_id=run_id,
                scoring_run_id=scoring_run_id,
                subject=report.subject,
                html=report.html,
                csv_bytes=report.csv_bytes,
                csv_filename=report.csv_filename,
                top_n=report.top_count,
                bottom_n=report.bottom_count,
            )

    def record_delivery(self, **kwargs: Any) -> None:
        with session_scope(self._engine) as s:
            ReportingRepository(s).write_delivery(**kwargs)


def _score_row(instrument_id: int, row: Mapping[Any, Any]) -> ScoreRow:
    flag = to_python(row.get("value_trap_flag"))
    rank = to_python(row.get("rank_overall"))
    return ScoreRow(
        instrument_id=instrument_id,
        passed_filter=True,
        value_score=to_python(row.get("value_score")),
        quality_score=to_python(row.get("quality_score")),
        composite_score=to_python(row.get("composite_score")),
        value_trap_flag=None if flag is None else bool(flag),
        rank_overall=None if rank is None else int(rank),
    )


def _factor_rows(
    scored: pd.DataFrame, ids: dict[str, int], cfg: ScoringConfig
) -> list[FactorScoreRow]:
    factors = [("value", k, v) for k, v in cfg.value_factors.items()]
    factors += [("quality", k, v) for k, v in cfg.quality_factors.items()]
    rows: list[FactorScoreRow] = []
    for record in scored.to_dict("records"):
        for category, key, (column, direction) in factors:
            raw = to_python(record.get(column))
            rank = to_python(record.get(f"rank_{key}"))
            if raw is None and rank is None:
                continue
            rows.append(
                FactorScoreRow(
                    ids[str(record["symbol"])], key, category, column, direction, raw, rank
                )
            )
    return rows
