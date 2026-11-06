"""Lesemodelle der REST-Endpunkte (P4.9): aus den Tabellen oder aus den Projektionen.

- ``TableReadModel``: die Abfragen aus P3.2 (``va_web_api.read``) mit der Rolle ``va_read``.
  Gilt ohne NATS, so wie heute auf der NAS und im E2E-Stack.
- ``ProjectionReadModel``: liest nur, was dem web-api gehoert: das Schema ``web`` und
  ``batch.run`` (Rolle ``va_web``). Profile und Reports kommen per Request/Reply
  (``rpc.RemoteReads``). Die Antworten sind dieselben; die Lese-Tests aus P3.2 laufen gegen beide.

Am Groessenfilter gescheiterte Titel stehen nicht in ``ranking_row`` (das Event traegt nur das
Ranking). Sie ergeben sich aus den Titeln des Abrufs (``snapshot_row``) ohne Zeile im Ranking.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import text

from va_contracts.profile import ProfileParamsV1

from . import read
from .models import (
    FactorRanks,
    Instrument,
    Ranking,
    RankingRow,
    RunDetail,
    ScorePoint,
    Snapshot,
)

if TYPE_CHECKING:
    from sqlalchemy import Engine

    from .models import ProfileDetail, ProfileSummary, Report, RunSummary
    from .rpc import RemoteReads


class TableReadModel:
    """Aus den Tabellen der Fach-Services, je Aufruf eine schreibgeschuetzte Verbindung."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def list_runs(self, *, limit: int, offset: int) -> list[RunSummary]:
        with self._engine.connect() as conn:
            return read.list_runs(conn, limit=limit, offset=offset)

    def get_run(self, run_id: int) -> RunDetail | None:
        with self._engine.connect() as conn:
            return read.get_run(conn, run_id)

    def latest_scoring_run_id(self) -> int | None:
        with self._engine.connect() as conn:
            return read.latest_scoring_run_id(conn)

    def get_ranking(self, scoring_run_id: int) -> Ranking | None:
        with self._engine.connect() as conn:
            return read.get_ranking(conn, scoring_run_id)

    def get_instrument(self, symbol: str) -> Instrument | None:
        with self._engine.connect() as conn:
            return read.get_instrument(conn, symbol)

    def get_report(self, report_id: int) -> Report | None:
        with self._engine.connect() as conn:
            return read.get_report(conn, report_id)

    def get_report_csv(self, report_id: int) -> tuple[str, bytes] | None:
        with self._engine.connect() as conn:
            return read.get_report_csv(conn, report_id)

    def list_profiles(self) -> list[ProfileSummary]:
        with self._engine.connect() as conn:
            return read.list_profiles(conn)

    def get_profile(self, profile_id: int) -> ProfileDetail | None:
        with self._engine.connect() as conn:
            return read.get_profile(conn, profile_id)


_RUN = text(f"""
    SELECT {read.RUN_COLUMNS}, r.app_version, r.error, r.fetch_run_id, r.scoring_run_id,
           COALESCE(r.report_id, rs.report_id) AS report_id
    FROM batch.run r
    LEFT JOIN web.run_status rs ON rs.run_id = r.id
    WHERE r.id = :run_id
""")

_LATEST = text("""
    SELECT scoring_run_id FROM web.ranking_run WHERE origin <> 'rescore'
    ORDER BY created_at DESC, scoring_run_id DESC LIMIT 1
""")

_HEAD = text("""
    SELECT scoring_run_id, fetch_run_id, origin, created_at, as_of, universe_source,
           value_weight, quality_weight
    FROM web.ranking_run WHERE scoring_run_id = :scoring_run_id
""")

# Track G (G3): Profil und Parameter des Bewertungslaufs
_PROFILE = text("""
    SELECT profile_id, profile_version, profile_name, params
    FROM web.ranking_profile WHERE scoring_run_id = :scoring_run_id
""")

# G3: Perzentile je Faktor eines Titels in einem Bewertungslauf
_FACTORS = text("""
    SELECT ranks FROM web.ranking_factor
    WHERE scoring_run_id = :scoring_run_id AND symbol = :symbol
""")

# Wie _RANKING_ROWS in read.py: erst die bewerteten Titel, dann die gefilterten des Abrufs
_ROWS = text("""
    SELECT r.rank_overall AS rank, COALESCE(r.symbol, s.symbol) AS symbol, s.name,
           s.index_name AS index, s.sector, r.symbol IS NOT NULL AS passed_filter,
           r.composite_score, r.value_score, r.quality_score,
           CASE WHEN r.symbol IS NULL THEN NULL ELSE r.value_trap END AS value_trap_flag,
           s.market_cap, s.currency, s.ev_ebit, s.pb_ratio, s.p_fcf, s.shareholder_yield, s.roic,
           s.fcf_margin, s.operating_margin, s.net_debt_ebitda, s.earnings_stability
    FROM (SELECT * FROM web.ranking_row WHERE scoring_run_id = :scoring_run_id) r
    FULL JOIN (SELECT * FROM web.snapshot_row WHERE fetch_run_id = :fetch_run_id) s
           ON s.symbol = r.symbol
    ORDER BY rank ASC NULLS LAST, symbol
""")

_SNAPSHOT = text("""
    SELECT fetch_run_id, fetched_on, fetch_ok, price, currency, market_cap, ev_ebit, pe_ratio,
           pb_ratio, p_fcf, dividend_yield, shareholder_yield, roic, fcf_margin,
           operating_margin, net_debt_ebitda, earnings_stability, revenue_growth_5y,
           eps_growth_5y, errors, name, index_name, sector, industry
    FROM web.snapshot_row WHERE symbol = :symbol
    ORDER BY fetch_ok DESC, fetched_on DESC, fetch_run_id DESC LIMIT 1
""")

_ISIN = text("""
    SELECT isin FROM web.snapshot_row WHERE symbol = :symbol AND isin IS NOT NULL
    ORDER BY fetch_run_id DESC LIMIT 1
""")

_HISTORY = text("""
    SELECT rr.scoring_run_id, rr.created_at, rr.origin, r.rank_overall AS rank,
           r.symbol IS NOT NULL AS passed_filter, r.composite_score, r.value_score,
           r.quality_score,
           CASE WHEN r.symbol IS NULL THEN NULL ELSE r.value_trap END AS value_trap_flag,
           (SELECT count(*) FROM web.ranking_row c
            WHERE c.scoring_run_id = rr.scoring_run_id AND c.rank_overall IS NOT NULL)
               AS ranked_count
    FROM web.ranking_run rr
    LEFT JOIN web.ranking_row r ON r.scoring_run_id = rr.scoring_run_id AND r.symbol = :symbol
    WHERE r.symbol IS NOT NULL
       OR EXISTS (SELECT 1 FROM web.snapshot_row s
                  WHERE s.fetch_run_id = rr.fetch_run_id AND s.symbol = :symbol)
    ORDER BY rr.created_at, rr.scoring_run_id
""")


class ProjectionReadModel:
    """Aus ``web`` und ``batch.run`` (``engine``: Rolle ``va_web``), Profile und Reports ueber
    ``remote``."""

    def __init__(self, engine: Engine, remote: RemoteReads) -> None:
        self._engine = engine
        self._remote = remote

    def list_runs(self, *, limit: int, offset: int) -> list[RunSummary]:
        with self._engine.connect() as conn:
            return read.list_runs(conn, limit=limit, offset=offset)

    def get_run(self, run_id: int) -> RunDetail | None:
        # Die Report-ID eines laufenden Runs steht in run_status, nicht in reporting.report
        with self._engine.connect() as conn:
            row = conn.execute(_RUN, {"run_id": run_id}).mappings().first()
        return None if row is None else RunDetail.model_validate(dict(row))

    def latest_scoring_run_id(self) -> int | None:
        with self._engine.connect() as conn:
            return conn.execute(_LATEST).scalar()

    def get_ranking(self, scoring_run_id: int) -> Ranking | None:
        with self._engine.connect() as conn:
            head = conn.execute(_HEAD, {"scoring_run_id": scoring_run_id}).mappings().first()
            if head is None:
                return None
            rows = (
                conn.execute(
                    _ROWS, {"scoring_run_id": scoring_run_id, "fetch_run_id": head["fetch_run_id"]}
                )
                .mappings()
                .all()
            )
            profile = conn.execute(_PROFILE, {"scoring_run_id": scoring_run_id}).mappings().first()
            return Ranking(
                scoring_run_id=head["scoring_run_id"],
                fetch_run_id=head["fetch_run_id"],
                origin=head["origin"],
                created_at=head["created_at"],
                fetched_on=head["as_of"],
                universe_source=head["universe_source"],
                value_weight=head["value_weight"],
                quality_weight=head["quality_weight"],
                profile=None
                if profile is None
                else read.run_profile(
                    profile["profile_id"], profile["profile_version"], profile["profile_name"]
                ),
                params=None
                if profile is None or profile["params"] is None
                else ProfileParamsV1.model_validate(profile["params"]),
                rows=[RankingRow.model_validate(dict(row)) for row in rows],
            )

    def get_instrument(self, symbol: str) -> Instrument | None:
        with self._engine.connect() as conn:
            snapshot = conn.execute(_SNAPSHOT, {"symbol": symbol}).mappings().first()
            if snapshot is None:
                return None
            isin = conn.execute(_ISIN, {"symbol": symbol}).scalar()
            history = conn.execute(_HISTORY, {"symbol": symbol}).mappings().all()
            # G3: aus dem juengsten Bewertungslauf; ohne Bewertung dort keine Perzentile
            latest = conn.execute(_LATEST).scalar()
            ranks = (
                None
                if latest is None
                else conn.execute(_FACTORS, {"scoring_run_id": latest, "symbol": symbol}).scalar()
            )
        values: dict[str, Any] = dict(snapshot)
        identity = {
            "name": values.pop("name"),
            "index": values.pop("index_name"),
            "sector": values.pop("sector"),
            "industry": values.pop("industry"),
        }
        values["errors"] = list(values["errors"] or [])
        return Instrument(
            symbol=symbol,
            isin=isin,
            **identity,
            latest=Snapshot.model_validate(values),
            score_history=[ScorePoint.model_validate(dict(row)) for row in history],
            factor_ranks=None
            if latest is None or ranks is None
            else FactorRanks(scoring_run_id=int(latest), ranks=ranks),
        )

    def get_report(self, report_id: int) -> Report | None:
        return self._remote.get_report(report_id)

    def get_report_csv(self, report_id: int) -> tuple[str, bytes] | None:
        return self._remote.get_report_csv(report_id)

    def list_profiles(self) -> list[ProfileSummary]:
        return self._remote.list_profiles()

    def get_profile(self, profile_id: int) -> ProfileDetail | None:
        return self._remote.get_profile(profile_id)
