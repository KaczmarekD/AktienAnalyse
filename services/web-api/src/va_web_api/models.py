"""Antwortmodelle der REST-API v1 (P3.2).

Sie sind der Vertrag mit dem Frontend: Der OpenAPI-Snapshot und der daraus generierte Client
(P3.5) leiten sich von ihnen ab. Aenderungen nur additiv (frontend.md).
"""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


class _Model(BaseModel):
    # Tippfehler in einer Abfrage sollen auffallen, statt still zu fehlen
    model_config = ConfigDict(extra="forbid")


class RunSummary(_Model):
    id: int
    kind: str  # batch / rescore / import
    status: str  # running / success / partial / no_data / failed
    started_at: datetime
    finished_at: datetime | None
    dry_run: bool
    force_refresh: bool
    universe_mode: str | None
    universe_size: int | None
    scored_count: int | None
    failed_count: int | None
    exit_code: int | None


class RunDetail(RunSummary):
    app_version: str
    error: str | None
    fetch_run_id: int | None
    scoring_run_id: int | None
    report_id: int | None


class RankingRow(_Model):
    rank: int | None  # leer: am Groessenfilter gescheitert
    symbol: str
    name: str | None
    index: str | None
    sector: str | None
    passed_filter: bool
    composite_score: float | None  # leer ohne beide Teilscores (M1)
    value_score: float | None
    quality_score: float | None
    value_trap_flag: bool | None
    market_cap: float | None
    currency: str | None
    ev_ebit: float | None
    pb_ratio: float | None
    p_fcf: float | None
    shareholder_yield: float | None
    roic: float | None
    fcf_margin: float | None
    operating_margin: float | None
    net_debt_ebitda: float | None
    earnings_stability: float | None


class Ranking(_Model):
    scoring_run_id: int
    fetch_run_id: int | None
    origin: str  # live / rescore / import
    created_at: datetime
    fetched_on: date | None  # Tag des Abrufs
    universe_source: str | None
    value_weight: float | None  # Import: keine Konfiguration gespeichert
    quality_weight: float | None
    rows: list[RankingRow]


class Snapshot(_Model):
    fetch_run_id: int
    fetched_on: date
    fetch_ok: bool
    price: float | None
    currency: str | None
    market_cap: float | None
    ev_ebit: float | None
    pe_ratio: float | None
    pb_ratio: float | None
    p_fcf: float | None
    dividend_yield: float | None
    shareholder_yield: float | None
    roic: float | None
    fcf_margin: float | None
    operating_margin: float | None
    net_debt_ebitda: float | None
    earnings_stability: float | None
    revenue_growth_5y: float | None
    eps_growth_5y: float | None
    errors: list[str]


class ScorePoint(_Model):
    scoring_run_id: int
    created_at: datetime
    origin: str
    rank: int | None
    passed_filter: bool
    composite_score: float | None
    value_score: float | None
    quality_score: float | None
    value_trap_flag: bool | None


class Instrument(_Model):
    symbol: str
    isin: str | None
    name: str | None
    index: str | None
    sector: str | None
    industry: str | None
    latest: Snapshot | None  # neuester gueltiger Abruf
    score_history: list[ScorePoint]  # aeltester zuerst


class Report(_Model):
    id: int
    run_id: int | None
    scoring_run_id: int | None
    subject: str
    generated_at: datetime
    csv_filename: str
    html: str
