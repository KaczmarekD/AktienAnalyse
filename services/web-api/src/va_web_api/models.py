"""Antwortmodelle der REST-API v1 (P3.2).

Sie sind der Vertrag mit dem Frontend: Der OpenAPI-Snapshot und der daraus generierte Client
(P3.5) leiten sich von ihnen ab. Aenderungen nur additiv (frontend.md).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from va_contracts.profile import ProfileParamsV1


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


class RunStart(_Model):
    """Ein Run aus dem UI (P4.7); die Optionen wie ``RunOptionsV1`` im Event."""

    force_refresh: bool = Field(
        default=False, description="Snapshot vom selben Tag nicht wiederverwenden"
    )
    dry_run: bool = Field(default=False, description="Mail rendern und speichern, nicht senden")
    notify: bool = Field(default=True, description="Mail verschicken; aus fuer Test-Runs")


class RunStarted(_Model):
    id: int  # batch.run.id; Fortschritt und Ergebnis kommen ueber den WebSocket


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


# --- Scoring-Profile (P3.3, ADR-0009) -------------------------------------------------------


class Factor(_Model):
    """Ein Faktor des Katalogs. Welche aktiv sind, steht im Profil; die Richtung ist fest."""

    key: str
    group: Literal["value", "quality"]
    label: str
    better: Literal["low", "high"]  # niedriger oder hoeher Wert ist besser
    hint: str  # Methodik-Hinweis fuer das UI


class ProfileVersion(_Model):
    version: int
    params: ProfileParamsV1
    parent_version: int | None  # die Version, auf der diese beruht
    comment: str | None
    created_at: datetime
    active: bool


class ProfileSummary(_Model):
    id: int
    name: str
    created_at: datetime
    latest_version: int | None
    active_version: int | None  # leer, wenn ein anderes Profil aktiv ist


class ProfileDetail(ProfileSummary):
    versions: list[ProfileVersion]  # neueste zuerst


class SaveProfileVersion(_Model):
    params: ProfileParamsV1
    comment: str | None = Field(default=None, max_length=500)


class SavedProfileVersion(_Model):
    profile_id: int
    version: int
    parent_version: int


class ActivateProfileVersion(_Model):
    version: int = Field(ge=1)


class ActivatedProfile(_Model):
    profile_id: int
    version: int


class ActiveProfileRef(_Model):
    profile_id: int
    name: str
    version: int


class PreviewRow(_Model):
    """Ein Titel mit den neuen params und, zum Vergleich, mit dem aktiven Profil."""

    symbol: str
    name: str | None
    index: str | None
    passed_filter: bool
    rank: int | None
    rank_active: int | None
    composite_score: float | None
    value_score: float | None
    quality_score: float | None
    value_trap_flag: bool | None
    value_trap_flag_active: bool | None


class Preview(_Model):
    scoring_run_id: int  # dessen Abruf ist die Grundlage
    fetch_run_id: int
    fetched_on: date | None
    active: ActiveProfileRef | None
    top: int
    entered: list[str]  # neu in den Top ``top``, nach neuem Rang
    left: list[str]  # nicht mehr in den Top ``top``, nach altem Rang
    trap_changed: list[str]  # Value-Trap-Markierung geaendert
    rows: list[PreviewRow]  # nach neuem Rang


# D1.1: Anmeldung (docs/architecture/depot/nutzer.md)
class LoginRequest(_Model):
    username: str = Field(min_length=1, max_length=64)
    # Obergrenze gegen sehr lange Eingaben vor dem teuren Hash
    password: str = Field(min_length=1, max_length=1024)


class Me(_Model):
    """Das eigene Konto, ohne Anmeldedaten."""

    id: int
    username: str
    role: Literal["admin", "user"]
    display_name: str | None
    email: str | None
