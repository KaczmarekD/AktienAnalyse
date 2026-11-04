"""Projektionen des web-api aus den Tabellen nachfuellen (P4.9): ``python -m src.db.backfill``.

Der Stream haelt Events nur 30 Tage, die Historie liegt in ``market_data`` und ``scoring``. Ohne
Nachfuellen saehe das web-api mit Projektionen nur die Laeufe seit dem Umstieg auf NATS. Gefuellt
werden ``web.snapshot_row``, ``web.ranking_run`` und ``web.ranking_row``, mit denselben Werten wie
aus den Events. Nur Anfuegen, was fehlt (``ON CONFLICT DO NOTHING``): Ein zweiter Aufruf aendert
nichts, und was die Events schon geschrieben haben, bleibt. Seit P5.1a auch
``scoring.input_snapshot``: die Eingangsdaten, aus denen scoring die Vorschau rechnet.

Laeuft mit der Owner-Rolle, denn es liest fremde Schemas und schreibt in ``web``.
``python -m src.db.migrate`` ruft es nach jeder Migration auf. So kommen auch Laeufe im Prozess
(etwa vor dem Umstieg oder mit ``make run``) in die Projektionen.
"""

from __future__ import annotations

import logging
import sys
from typing import TYPE_CHECKING, Any

from sqlalchemy import create_engine, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from va_market_data.adapters.postgres.repository import MarketDataRepository
from va_platform.db import normalize_url
from va_scoring.adapters.postgres.models import InputSnapshot
from va_scoring.adapters.postgres.store import input_rows
from va_web_api.adapters.postgres.models import RankingRow, RankingRun, SnapshotRow

if TYPE_CHECKING:
    from datetime import date, datetime

    from sqlalchemy import Connection, Engine

log = logging.getLogger(__name__)

_METRICS = (
    "price",
    "market_cap",
    "ev_ebit",
    "pe_ratio",
    "pb_ratio",
    "p_fcf",
    "dividend_yield",
    "shareholder_yield",
    "roic",
    "fcf_margin",
    "operating_margin",
    "net_debt_ebitda",
    "earnings_stability",
    "revenue_growth_5y",
    "eps_growth_5y",
)

_SNAPSHOTS = text(f"""
    SELECT fs.fetch_run_id, i.symbol, i.isin, fr.started_at, fs.fetch_ok, fs.name,
           fs.index_name, fs.sector, fs.industry, fs.currency,
           {", ".join(f"fs.{m}" for m in _METRICS)}, fs.errors
    FROM market_data.fundamental_snapshot fs
    JOIN market_data.instrument i ON i.id = fs.instrument_id
    JOIN market_data.fetch_run fr ON fr.id = fs.fetch_run_id
    WHERE NOT EXISTS (SELECT 1 FROM web.snapshot_row s
                      WHERE s.fetch_run_id = fs.fetch_run_id AND s.symbol = i.symbol)
""")

_RUNS = text("""
    SELECT sr.id, sr.fetch_run_id, sr.origin, sr.created_at, sr.config, fr.started_at,
           fr.universe_source,
           (SELECT max(b.id) FROM batch.run b WHERE b.scoring_run_id = sr.id) AS run_id
    FROM scoring.scoring_run sr
    LEFT JOIN market_data.fetch_run fr ON fr.id = sr.fetch_run_id
    WHERE NOT EXISTS (SELECT 1 FROM web.ranking_run r WHERE r.scoring_run_id = sr.id)
""")

_ROWS = text("""
    SELECT res.scoring_run_id, i.symbol, fs.name, fs.index_name, res.rank_overall,
           res.composite_score, res.value_score, res.quality_score, res.value_trap_flag,
           fr.started_at, sr.created_at,
           (SELECT max(b.id) FROM batch.run b WHERE b.scoring_run_id = sr.id) AS run_id
    FROM scoring.score_result res
    JOIN scoring.scoring_run sr ON sr.id = res.scoring_run_id
    JOIN market_data.instrument i ON i.id = res.instrument_id
    LEFT JOIN market_data.fetch_run fr ON fr.id = sr.fetch_run_id
    LEFT JOIN market_data.fundamental_snapshot fs
           ON fs.instrument_id = res.instrument_id AND fs.fetch_run_id = sr.fetch_run_id
    WHERE res.passed_filter
      AND NOT EXISTS (SELECT 1 FROM web.ranking_row r
                      WHERE r.scoring_run_id = res.scoring_run_id AND r.symbol = i.symbol)
""")


# P5.1a: Abrufe mit Bewertungslauf, deren Eingangsdaten scoring noch nicht hat
_INPUT_FETCHES = text("""
    SELECT DISTINCT sr.fetch_run_id FROM scoring.scoring_run sr
    WHERE sr.fetch_run_id IS NOT NULL
      AND NOT EXISTS (SELECT 1 FROM scoring.input_snapshot i
                      WHERE i.fetch_run_id = sr.fetch_run_id)
    ORDER BY sr.fetch_run_id
""")


def _day(moment: datetime | None) -> date | None:
    """Wie ``va_web_api.read``: Tag in lokaler Zeit (Container: TZ=Europe/Berlin)."""
    return None if moment is None else moment.astimezone().date()


def _snapshot_rows(conn: Connection) -> list[dict[str, Any]]:
    rows = []
    for row in conn.execute(_SNAPSHOTS).mappings():
        values = dict(row)
        values["fetched_on"] = _day(values.pop("started_at"))
        values["errors"] = list(values["errors"] or [])
        rows.append(values)
    return rows


def _ranking_runs(conn: Connection) -> list[dict[str, Any]]:
    rows = []
    for row in conn.execute(_RUNS).mappings():
        config: dict[str, Any] = row["config"] or {}
        rows.append(
            {
                "scoring_run_id": row["id"],
                "run_id": row["run_id"],
                "fetch_run_id": row["fetch_run_id"],
                "origin": row["origin"],
                "as_of": _day(row["started_at"]),
                "universe_source": row["universe_source"],
                "value_weight": config.get("value_weight"),
                "quality_weight": config.get("quality_weight"),
                "created_at": row["created_at"],
            }
        )
    return rows


def _ranking_rows(conn: Connection) -> list[dict[str, Any]]:
    rows = []
    for row in conn.execute(_ROWS).mappings():
        rows.append(
            {
                "scoring_run_id": row["scoring_run_id"],
                "symbol": row["symbol"],
                "run_id": row["run_id"],
                # Importierte Altdaten haben keinen Abruf: dann der Tag des Bewertungslaufs
                "as_of": _day(row["started_at"] or row["created_at"]),
                "name": row["name"] or row["symbol"],
                "index": row["index_name"] or "",
                "rank_overall": row["rank_overall"],
                "composite_score": row["composite_score"],
                "value_score": row["value_score"],
                "quality_score": row["quality_score"],
                "value_trap": bool(row["value_trap_flag"]),
            }
        )
    return rows


def _input_snapshots(conn: Connection) -> list[dict[str, Any]]:
    """Die flachen Zeilen alter Abrufe, wie scoring sie seit P5.1a selbst speichert."""
    rows: list[dict[str, Any]] = []
    fetches = list(conn.execute(_INPUT_FETCHES).scalars())
    if not fetches:
        return rows
    with Session(bind=conn) as session:
        market = MarketDataRepository(session)
        for fetch_run_id in fetches:
            frame = market.get_snapshots_df(fetch_run_id)
            rows += [
                {"fetch_run_id": fetch_run_id, "symbol": str(row["symbol"]), "row": row}
                for row in input_rows(frame)
            ]
    return rows


def _insert(conn: Connection, model: Any, rows: list[dict[str, Any]], size: int = 500) -> int:
    key = next(iter(model.__table__.primary_key.columns))
    added = 0
    for start in range(0, len(rows), size):
        statement = (
            insert(model)
            .values(rows[start : start + size])
            .on_conflict_do_nothing()
            .returning(key)  # rowcount ist bei mehreren Zeilen -1: angelegte Zeilen zaehlen
        )
        added += len(conn.execute(statement).all())
    return added


def backfill_projections(engine: Engine) -> dict[str, int]:
    """Fuegt an, was in den Projektionen fehlt; gibt die Anzahl neuer Zeilen je Tabelle zurueck."""
    with engine.begin() as conn:
        added = {
            "snapshot_row": _insert(conn, SnapshotRow, _snapshot_rows(conn)),
            "ranking_run": _insert(conn, RankingRun, _ranking_runs(conn)),
            "ranking_row": _insert(conn, RankingRow, _ranking_rows(conn)),
            # P5.1a: Eingangsdaten fuer die Vorschau von scoring
            "input_snapshot": _insert(conn, InputSnapshot, _input_snapshots(conn)),
        }
    if any(added.values()):
        log.info("Projektionen nachgefuellt: %s", added)
    return added


def main() -> int:
    from ..config import DatabaseSettings  # noqa: PLC0415 - nur fuer den Aufruf von aussen

    settings = DatabaseSettings()
    url = settings.database_owner_url or settings.database_url
    if url is None:
        sys.stderr.write("Keine Datenbank-URL: DATABASE_OWNER_URL oder DATABASE_URL setzen\n")
        return 1
    engine = create_engine(normalize_url(url.get_secret_value()))
    try:
        print(backfill_projections(engine))
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(main())
