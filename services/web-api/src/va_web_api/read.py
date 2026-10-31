"""Lesende Abfragen des web-api (P3.2).

Eigenes SQL statt der Repositories der Fach-Services: Das web-api ist ein Service fuer sich und
importiert keinen anderen (import-linter). Ab Phase 4 loesen Projektionen diese Abfragen ab, die
REST-Antworten bleiben gleich (web-api-realtime.md). Die Verbindung ist schreibgeschuetzt.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import text

from .models import (
    Instrument,
    Ranking,
    RankingRow,
    Report,
    RunDetail,
    RunSummary,
    ScorePoint,
    Snapshot,
)

if TYPE_CHECKING:
    from sqlalchemy import Connection

_RUN_COLUMNS = """
    r.id, r.kind, r.status, r.started_at, r.finished_at, r.dry_run, r.force_refresh,
    r.universe_mode, r.universe_size, r.scored_count, r.failed_count, r.exit_code
"""

_RANKING_ROWS = text("""
    SELECT res.rank_overall AS rank, i.symbol, fs.name, fs.index_name AS index, fs.sector,
           res.passed_filter, res.composite_score, res.value_score, res.quality_score,
           res.value_trap_flag, fs.market_cap, fs.currency, fs.ev_ebit, fs.pb_ratio, fs.p_fcf,
           fs.shareholder_yield, fs.roic, fs.fcf_margin, fs.operating_margin,
           fs.net_debt_ebitda, fs.earnings_stability
    FROM scoring.score_result res
    JOIN market_data.instrument i ON i.id = res.instrument_id
    LEFT JOIN market_data.fundamental_snapshot fs
           ON fs.instrument_id = res.instrument_id AND fs.fetch_run_id = :fetch_run_id
    WHERE res.scoring_run_id = :scoring_run_id
    ORDER BY res.rank_overall ASC NULLS LAST, i.symbol
""")

_SNAPSHOT_COLUMNS = """
    fs.fetch_run_id, fs.fetch_ok, fs.price, fs.currency, fs.market_cap, fs.ev_ebit, fs.pe_ratio,
    fs.pb_ratio, fs.p_fcf, fs.dividend_yield, fs.shareholder_yield, fs.roic, fs.fcf_margin,
    fs.operating_margin, fs.net_debt_ebitda, fs.earnings_stability, fs.revenue_growth_5y,
    fs.eps_growth_5y, fs.errors
"""


def list_runs(conn: Connection, *, limit: int, offset: int) -> list[RunSummary]:
    rows = conn.execute(
        text(f"""
            SELECT {_RUN_COLUMNS} FROM batch.run r
            ORDER BY r.started_at DESC, r.id DESC LIMIT :limit OFFSET :offset
        """),
        {"limit": limit, "offset": offset},
    ).mappings()
    return [RunSummary.model_validate(dict(row)) for row in rows]


def get_run(conn: Connection, run_id: int) -> RunDetail | None:
    # report_id steht im Lauf, sobald er abgeschlossen ist; sonst der juengste Report des Laufs
    row = (
        conn.execute(
            text(f"""
                SELECT {_RUN_COLUMNS}, r.app_version, r.error, r.fetch_run_id, r.scoring_run_id,
                       COALESCE(r.report_id, (SELECT max(rep.id) FROM reporting.report rep
                                              WHERE rep.run_id = r.id)) AS report_id
                FROM batch.run r WHERE r.id = :run_id
            """),
            {"run_id": run_id},
        )
        .mappings()
        .first()
    )
    return None if row is None else RunDetail.model_validate(dict(row))


def latest_scoring_run_id(conn: Connection) -> int | None:
    """Juengster Bewertungslauf ausser Rescores (die bewerten absichtlich anders)."""
    return conn.execute(
        text("""
            SELECT id FROM scoring.scoring_run WHERE origin <> 'rescore'
            ORDER BY created_at DESC, id DESC LIMIT 1
        """)
    ).scalar()


def get_ranking(conn: Connection, scoring_run_id: int) -> Ranking | None:
    head = (
        conn.execute(
            text("""
                SELECT sr.id, sr.fetch_run_id, sr.origin, sr.created_at, sr.config,
                       fr.started_at AS fetched_at, fr.universe_source
                FROM scoring.scoring_run sr
                LEFT JOIN market_data.fetch_run fr ON fr.id = sr.fetch_run_id
                WHERE sr.id = :scoring_run_id
            """),
            {"scoring_run_id": scoring_run_id},
        )
        .mappings()
        .first()
    )
    if head is None:
        return None
    rows = conn.execute(
        _RANKING_ROWS, {"scoring_run_id": scoring_run_id, "fetch_run_id": head["fetch_run_id"]}
    ).mappings()
    config: dict[str, Any] = head["config"] or {}
    return Ranking(
        scoring_run_id=head["id"],
        fetch_run_id=head["fetch_run_id"],
        origin=head["origin"],
        created_at=head["created_at"],
        fetched_on=_day(head["fetched_at"]),
        universe_source=head["universe_source"],
        value_weight=config.get("value_weight"),
        quality_weight=config.get("quality_weight"),
        rows=[RankingRow.model_validate(dict(row)) for row in rows],
    )


def get_instrument(conn: Connection, symbol: str) -> Instrument | None:
    instrument = (
        conn.execute(
            text("SELECT id, symbol, isin FROM market_data.instrument WHERE symbol = :symbol"),
            {"symbol": symbol},
        )
        .mappings()
        .first()
    )
    if instrument is None:
        return None
    # Neuester Abruf, gueltige zuerst: Ein gescheiterter Abruf hat kaum Kennzahlen
    snapshot = (
        conn.execute(
            text(f"""
                SELECT {_SNAPSHOT_COLUMNS}, fs.name, fs.index_name, fs.sector, fs.industry,
                       fr.started_at AS fetched_at
                FROM market_data.fundamental_snapshot fs
                JOIN market_data.fetch_run fr ON fr.id = fs.fetch_run_id
                WHERE fs.instrument_id = :instrument_id
                ORDER BY fs.fetch_ok DESC, fr.started_at DESC, fr.id DESC LIMIT 1
            """),
            {"instrument_id": instrument["id"]},
        )
        .mappings()
        .first()
    )
    history = conn.execute(
        text("""
            SELECT sr.id AS scoring_run_id, sr.created_at, sr.origin, res.rank_overall AS rank,
                   res.passed_filter, res.composite_score, res.value_score, res.quality_score,
                   res.value_trap_flag
            FROM scoring.score_result res
            JOIN scoring.scoring_run sr ON sr.id = res.scoring_run_id
            WHERE res.instrument_id = :instrument_id
            ORDER BY sr.created_at, sr.id
        """),
        {"instrument_id": instrument["id"]},
    ).mappings()
    latest = None
    identity: dict[str, Any] = {"name": None, "index": None, "sector": None, "industry": None}
    if snapshot is not None:
        values = dict(snapshot)
        identity = {
            "name": values.pop("name"),
            "index": values.pop("index_name"),
            "sector": values.pop("sector"),
            "industry": values.pop("industry"),
        }
        values["fetched_on"] = _day(values.pop("fetched_at"))
        values["errors"] = list(values["errors"] or [])
        latest = Snapshot.model_validate(values)
    return Instrument(
        symbol=instrument["symbol"],
        isin=instrument["isin"],
        **identity,
        latest=latest,
        score_history=[ScorePoint.model_validate(dict(row)) for row in history],
    )


def get_report(conn: Connection, report_id: int) -> Report | None:
    row = (
        conn.execute(
            text("""
                SELECT id, run_id, scoring_run_id, subject, generated_at, csv_filename, html
                FROM reporting.report WHERE id = :report_id
            """),
            {"report_id": report_id},
        )
        .mappings()
        .first()
    )
    return None if row is None else Report.model_validate(dict(row))


def get_report_csv(conn: Connection, report_id: int) -> tuple[str, bytes] | None:
    row = conn.execute(
        text("SELECT csv_filename, csv_bytes FROM reporting.report WHERE id = :report_id"),
        {"report_id": report_id},
    ).first()
    return None if row is None else (str(row[0]), bytes(row[1]))


def _day(moment: datetime | None) -> date | None:
    """Tag in lokaler Zeit (Container: TZ=Europe/Berlin), wie im Batch."""
    return None if moment is None else moment.astimezone().date()
