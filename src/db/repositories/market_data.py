"""Zugriffe auf ``market_data``: Stammdaten, Universum, Rohdaten, Kennzahlen."""

from __future__ import annotations

import math
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import TYPE_CHECKING, Any

import pandas as pd
from sqlalchemy import insert, select, update
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.dialects.postgresql import insert as pg_insert

from ...fundamentals import join_errors
from ..models import (
    FetchRun,
    FundamentalSnapshot,
    FxRate,
    Instrument,
    RawInfo,
    StatementValue,
)
from ..models import UniverseMember as UniverseMemberRow
from ..serialization import json_safe, to_python

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

# Spalten, die write_snapshot annimmt (alles ausser den Schluesseln)
SNAPSHOT_COLUMNS: tuple[str, ...] = tuple(
    c.name
    for c in FundamentalSnapshot.__table__.columns
    if c.name not in {"fetch_run_id", "instrument_id"}
)
# Numerische Kennzahlen, fuer die es Zeitreihen gibt
SNAPSHOT_METRICS: frozenset[str] = frozenset(
    c.name
    for c in FundamentalSnapshot.__table__.columns
    if c.type.python_type is float and c.name not in {"fetch_run_id", "instrument_id"}
)


@dataclass(frozen=True)
class UniverseMember:
    """Ein Titel des Universums, wie ihn Wikipedia/Fallback-CSV geliefert hat."""

    symbol: str
    index_name: str
    name: str | None
    source: str | None


class MarketDataRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    # --- Instrumente ------------------------------------------------------

    def get_or_create_instruments(self, symbols: Iterable[str]) -> dict[str, int]:
        wanted = sorted(set(symbols))
        if not wanted:
            return {}
        self.session.execute(
            pg_insert(Instrument)
            .values([{"symbol": s} for s in wanted])
            .on_conflict_do_nothing(index_elements=["symbol"])
        )
        rows = self.session.execute(
            select(Instrument.symbol, Instrument.id).where(Instrument.symbol.in_(wanted))
        )
        return {symbol: iid for symbol, iid in rows.all()}  # noqa: C416 - Row ist kein Paar-Typ

    def write_isins(self, isins: Mapping[str, str]) -> int:
        """Traegt fehlende ISINs nach. Nie ueberschreiben (die DB verbietet es ohnehin),
        nie eine ISIN doppelt vergeben (z.B. Tickerwechsel) - dann bleibt sie leer."""
        written = 0
        for symbol, isin in isins.items():
            taken = select(Instrument.id).where(Instrument.isin == isin).exists()
            result = self.session.execute(
                update(Instrument)
                .where(Instrument.symbol == symbol, Instrument.isin.is_(None), ~taken)
                .values(isin=isin)
            )
            written += result.rowcount or 0  # type: ignore[attr-defined]
        return written

    def get_instrument(self, symbol: str) -> Instrument | None:
        return self.session.scalars(select(Instrument).where(Instrument.symbol == symbol)).first()

    # --- Abrufe -------------------------------------------------------------

    def write_fetch_run_start(
        self,
        *,
        provider: str,
        provider_version: str | None,
        universe_source: str | None,
        universe_size: int | None,
        universe_as_of: date | None = None,
        origin: str = "live",
        started_at: datetime | None = None,
        note: str | None = None,
    ) -> int:
        values: dict[str, Any] = {
            "origin": origin,
            "provider": provider,
            "provider_version": provider_version,
            "universe_source": universe_source,
            "universe_as_of": universe_as_of,
            "universe_size": universe_size,
            "note": note,
        }
        if started_at is not None:
            values["started_at"] = started_at
        stmt = insert(FetchRun).values(**values).returning(FetchRun.id)
        return self.session.execute(stmt).scalar_one()

    def write_fetch_run_finish(
        self,
        fetch_run_id: int,
        *,
        ok_count: int,
        success_share: float,
        finished_at: datetime | None = None,
    ) -> None:
        values: dict[str, Any] = {"ok_count": ok_count, "success_share": success_share}
        values["finished_at"] = finished_at or datetime.now().astimezone()
        self.session.execute(update(FetchRun).where(FetchRun.id == fetch_run_id).values(**values))

    def get_fetch_run(self, fetch_run_id: int) -> FetchRun | None:
        return self.session.get(FetchRun, fetch_run_id)

    def get_reusable_fetch_run(
        self, day: date, min_success_share: float, symbols: Collection[str]
    ) -> FetchRun | None:
        """Juengster abgeschlossener Live-Abruf vom ``day`` (lokale Zeit) mit ausreichender
        Quote, dessen Universum alle ``symbols`` enthaelt (sonst fehlten z.B. nach einem
        DAX_ONLY-Abruf die MDAX-Titel)."""
        wanted = set(symbols)
        start = datetime.combine(day, time.min).astimezone()
        stmt = (
            select(FetchRun)
            .where(
                FetchRun.origin == "live",
                FetchRun.finished_at.is_not(None),
                FetchRun.started_at >= start,
                FetchRun.started_at < start + timedelta(days=1),
                FetchRun.success_share >= min_success_share,
            )
            .order_by(FetchRun.started_at.desc(), FetchRun.id.desc())
        )
        for fetch_run in self.session.scalars(stmt):
            members = self.session.scalars(
                select(Instrument.symbol)
                .join(UniverseMemberRow, UniverseMemberRow.instrument_id == Instrument.id)
                .where(UniverseMemberRow.fetch_run_id == fetch_run.id)
            )
            if wanted <= set(members):
                return fetch_run
        return None

    # --- Universum -----------------------------------------------------------

    def write_universe(self, fetch_run_id: int, members: Sequence[UniverseMember]) -> None:
        if not members:
            return
        ids = self.get_or_create_instruments(m.symbol for m in members)
        self.session.execute(
            insert(UniverseMemberRow),
            [
                {
                    "fetch_run_id": fetch_run_id,
                    "instrument_id": ids[m.symbol],
                    "index_name": m.index_name,
                    "name": m.name,
                    "source": m.source,
                }
                for m in members
            ],
        )

    def get_universe(self, fetch_run_id: int) -> pd.DataFrame:
        stmt = (
            select(
                Instrument.symbol,
                UniverseMemberRow.index_name,
                UniverseMemberRow.name,
                UniverseMemberRow.source,
            )
            .join(Instrument, Instrument.id == UniverseMemberRow.instrument_id)
            .where(UniverseMemberRow.fetch_run_id == fetch_run_id)
            .order_by(UniverseMemberRow.index_name, Instrument.symbol)
        )
        return self._frame(stmt, ["symbol", "index_name", "name", "source"])

    def get_membership_history(self, symbol: str) -> pd.DataFrame:
        stmt = (
            select(
                FetchRun.id,
                FetchRun.started_at,
                UniverseMemberRow.index_name,
                UniverseMemberRow.source,
            )
            .join(UniverseMemberRow, UniverseMemberRow.fetch_run_id == FetchRun.id)
            .join(Instrument, Instrument.id == UniverseMemberRow.instrument_id)
            .where(Instrument.symbol == symbol)
            .order_by(FetchRun.started_at, FetchRun.id)
        )
        return self._frame(stmt, ["fetch_run_id", "started_at", "index_name", "source"])

    # --- Rohdaten ----------------------------------------------------------------

    def write_raw_info(
        self,
        fetch_run_id: int,
        instrument_id: int,
        payload: Mapping[str, Any],
        fetched_at: datetime,
    ) -> None:
        self.session.execute(
            insert(RawInfo).values(
                fetch_run_id=fetch_run_id,
                instrument_id=instrument_id,
                fetched_at=fetched_at,
                payload=json_safe(dict(payload)),
            )
        )

    def get_raw_info(self, fetch_run_id: int, symbol: str) -> dict[str, Any] | None:
        stmt = (
            select(RawInfo.payload)
            .join(Instrument, Instrument.id == RawInfo.instrument_id)
            .where(RawInfo.fetch_run_id == fetch_run_id, Instrument.symbol == symbol)
        )
        return self.session.scalars(stmt).first()

    def write_statements(
        self,
        fetch_run_id: int,
        instrument_id: int,
        statements: Mapping[str, pd.DataFrame | None],
        *,
        currency: str | None,
        fetched_at: datetime,
        frequency: str = "annual",
    ) -> int:
        """Speichert nur neue oder geaenderte Werte. Liefert die Anzahl neuer Versionen."""
        incoming = _statement_rows(statements)
        if not incoming:
            return 0
        current = self._current_statement_values(instrument_id, frequency)
        new_rows = [
            {
                "instrument_id": instrument_id,
                "statement": statement,
                "frequency": frequency,
                "line_item": line_item,
                "period_end": period_end,
                "value": value,
                "currency": currency,
                "first_seen_fetch_run_id": fetch_run_id,
                "first_seen_at": fetched_at,
            }
            for (statement, line_item, period_end), value in incoming.items()
            if current.get((statement, line_item, period_end)) != value
        ]
        if new_rows:
            self.session.execute(insert(StatementValue), new_rows)
        return len(new_rows)

    def _current_statement_values(
        self, instrument_id: int, frequency: str, as_of: datetime | None = None
    ) -> dict[tuple[str, str, date], float]:
        stmt = self._latest_statements_stmt(frequency, as_of).where(
            StatementValue.instrument_id == instrument_id
        )
        return {
            (row.statement, row.line_item, row.period_end): row.value
            for row in self.session.execute(stmt)
        }

    @staticmethod
    def _latest_statements_stmt(frequency: str, as_of: datetime | None):
        stmt = (
            select(
                StatementValue.statement,
                StatementValue.line_item,
                StatementValue.period_end,
                StatementValue.value,
                StatementValue.first_seen_at,
            )
            .where(StatementValue.frequency == frequency)
            .ext(
                distinct_on(
                    StatementValue.statement, StatementValue.line_item, StatementValue.period_end
                )
            )
            .order_by(
                StatementValue.statement,
                StatementValue.line_item,
                StatementValue.period_end,
                StatementValue.first_seen_at.desc(),
                StatementValue.id.desc(),
            )
        )
        if as_of is not None:
            stmt = stmt.where(StatementValue.first_seen_at <= as_of)
        return stmt

    def get_statement_history(
        self, symbol: str, line_item: str, statement: str | None = None
    ) -> pd.DataFrame:
        """Alle Versionen eines Postens - Restatements werden als eigene Zeilen sichtbar."""
        stmt = (
            select(
                StatementValue.statement,
                StatementValue.period_end,
                StatementValue.value,
                StatementValue.currency,
                StatementValue.first_seen_at,
                StatementValue.first_seen_fetch_run_id,
            )
            .join(Instrument, Instrument.id == StatementValue.instrument_id)
            .where(Instrument.symbol == symbol, StatementValue.line_item == line_item)
            .order_by(StatementValue.period_end, StatementValue.first_seen_at, StatementValue.id)
        )
        if statement is not None:
            stmt = stmt.where(StatementValue.statement == statement)
        return self._frame(
            stmt,
            [
                "statement",
                "period_end",
                "value",
                "currency",
                "first_seen_at",
                "first_seen_fetch_run_id",
            ],
        )

    def get_statements_as_of(
        self, symbol: str, as_of: datetime, frequency: str = "annual"
    ) -> pd.DataFrame:
        """Abschlusswerte, wie sie zum Zeitpunkt ``as_of`` bekannt waren (point-in-time)."""
        instrument = self.get_instrument(symbol)
        columns = ["statement", "line_item", "period_end", "value", "first_seen_at"]
        if instrument is None:
            return pd.DataFrame(columns=columns)
        stmt = self._latest_statements_stmt(frequency, as_of).where(
            StatementValue.instrument_id == instrument.id
        )
        return self._frame(stmt, columns)

    # --- Wechselkurse -----------------------------------------------------------

    def write_fx_rate(
        self, fetch_run_id: int, from_ccy: str, to_ccy: str, rate: float, fetched_at: datetime
    ) -> None:
        self.session.execute(
            pg_insert(FxRate)
            .values(
                fetch_run_id=fetch_run_id,
                from_ccy=from_ccy,
                to_ccy=to_ccy,
                rate=rate,
                fetched_at=fetched_at,
            )
            .on_conflict_do_nothing(index_elements=["fetch_run_id", "from_ccy", "to_ccy"])
        )

    def get_fx_rates(self, fetch_run_id: int) -> pd.DataFrame:
        stmt = (
            select(FxRate.from_ccy, FxRate.to_ccy, FxRate.rate, FxRate.fetched_at)
            .where(FxRate.fetch_run_id == fetch_run_id)
            .order_by(FxRate.from_ccy, FxRate.to_ccy)
        )
        return self._frame(stmt, ["from_ccy", "to_ccy", "rate", "fetched_at"])

    # --- Kennzahlen-Snapshots ---------------------------------------------------

    def write_snapshot(
        self, fetch_run_id: int, instrument_id: int, values: Mapping[str, Any]
    ) -> None:
        """``values`` = Spalten aus ``SNAPSHOT_COLUMNS``. Unbekannte Spalten -> ValueError,
        damit eine neue Kennzahl nicht still verloren geht (Migration fehlt)."""
        unknown = set(values) - set(SNAPSHOT_COLUMNS)
        if unknown:
            msg = f"Unbekannte Snapshot-Spalten (Migration fehlt?): {sorted(unknown)}"
            raise ValueError(msg)
        row = {k: to_python(v) for k, v in values.items()}
        row["errors"] = [to_python(e) for e in values.get("errors") or []]
        self.session.execute(
            insert(FundamentalSnapshot).values(
                fetch_run_id=fetch_run_id, instrument_id=instrument_id, **row
            )
        )

    def get_snapshots_df(
        self, fetch_run_id: int, symbols: Collection[str] | None = None
    ) -> pd.DataFrame:
        """Gleiche Spalten wie ``Fundamentals.to_flat_dict()`` - direkt fuer ``score()``.

        ``symbols`` beschraenkt auf ein Teiluniversum (z.B. DAX_ONLY auf einem Vollabruf).
        """
        columns = [getattr(FundamentalSnapshot, c) for c in SNAPSHOT_COLUMNS]
        stmt = (
            select(Instrument.symbol, *columns)
            .join(Instrument, Instrument.id == FundamentalSnapshot.instrument_id)
            .where(FundamentalSnapshot.fetch_run_id == fetch_run_id)
            .order_by(Instrument.symbol)
        )
        if symbols is not None:
            stmt = stmt.where(Instrument.symbol.in_(list(symbols)))
        df = self._frame(stmt, ["symbol", *SNAPSHOT_COLUMNS])
        df = df.rename(columns={"index_name": "index"})
        df["errors"] = df["errors"].map(join_errors)
        for metric in SNAPSHOT_METRICS:
            df[metric] = pd.to_numeric(df[metric], errors="coerce").astype(float)
        return df

    def get_metric_history(self, symbol: str, metric: str) -> pd.DataFrame:
        if metric not in SNAPSHOT_METRICS:
            msg = f"Unbekannte Kennzahl: {metric}"
            raise ValueError(msg)
        stmt = (
            select(FetchRun.id, FetchRun.started_at, getattr(FundamentalSnapshot, metric))
            .join(FundamentalSnapshot, FundamentalSnapshot.fetch_run_id == FetchRun.id)
            .join(Instrument, Instrument.id == FundamentalSnapshot.instrument_id)
            .where(Instrument.symbol == symbol)
            .order_by(FetchRun.started_at, FetchRun.id)
        )
        return self._frame(stmt, ["fetch_run_id", "started_at", "value"])

    # --- intern -------------------------------------------------------------------

    def _frame(self, stmt: Any, columns: list[str]) -> pd.DataFrame:
        rows = self.session.execute(stmt).all()
        return pd.DataFrame([tuple(r) for r in rows], columns=columns)


def _statement_rows(
    statements: Mapping[str, pd.DataFrame | None],
) -> dict[tuple[str, str, date], float]:
    """DataFrames (Zeilen = Posten, Spalten = Perioden) -> {(statement, posten, periode): wert}."""
    out: dict[tuple[str, str, date], float] = {}
    for statement, df in statements.items():
        if df is None or df.empty:
            continue
        for period_label in df.columns:
            try:
                period_ts = pd.Timestamp(period_label)
            except TypeError, ValueError:
                continue
            # None, NaN und "NaT" werfen nicht, sondern ergeben NaT - keine Periode
            if pd.isna(period_ts):
                continue
            period_end = period_ts.date()
            for line_item, raw in df[period_label].items():
                value = to_python(raw)
                if not isinstance(value, int | float) or isinstance(value, bool):
                    continue
                if not math.isfinite(value):
                    continue
                out.setdefault((statement, str(line_item), period_end), float(value))
    return out
