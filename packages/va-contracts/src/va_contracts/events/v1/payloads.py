"""Payloads der Events v1 (Katalog in docs/architecture/events.md)."""

from __future__ import annotations

from datetime import date
from typing import Literal, Self

from pydantic import Field, model_validator

from ...base import Contract
from .fundamentals import FundamentalsV1
from .ranking import RankingRowV1

# Wer einen Run ausgeloest hat. "rescore": Neubewertung nach einer Profil-Aktivierung,
# ohne Abruf, ohne Mail und ohne Healthcheck-Ping.
RunTrigger = Literal["scheduled", "manual"]
ScoringTrigger = Literal["scheduled", "manual", "rescore"]
# Stufe, an der ein Run gescheitert ist; der Watchdog meldet haengende Runs
Stage = Literal["market-data", "scoring", "notification", "watchdog"]


class ScreeningRunRequestedV1(Contract):
    """web-api -> market-data: einen Run starten."""

    run_id: int  # batch.run.id
    trigger: RunTrigger
    force_refresh: bool = False  # Snapshot vom selben Tag nicht wiederverwenden
    dry_run: bool = False  # Mail rendern und speichern, nicht verschicken
    notify: bool = True  # False: kein Mailversand, z. B. fuer Test-Runs


class FetchProgressedV1(Contract):
    """market-data -> web-api: Fortschritt des Abrufs (fluechtig, ausserhalb des Streams)."""

    run_id: int
    done: int = Field(ge=0)
    total: int = Field(ge=0)
    symbol: str
    ok: bool

    @model_validator(mode="after")
    def _done_within_total(self) -> Self:
        if self.done > self.total:
            msg = f"done ({self.done}) groesser als total ({self.total})"
            raise ValueError(msg)
        return self


class SnapshotCompletedV1(Contract):
    """market-data -> scoring, web-api: alle Fundamentaldaten eines Abrufs."""

    run_id: int
    fetch_run_id: int  # market_data.fetch_run.id
    as_of: date  # Tag des Abrufs
    success_share: float = Field(ge=0, le=1)  # Anteil der Titel mit Marktkapitalisierung
    universe_source: str  # iShares / Deka / Fallback-CSV
    fundamentals: list[FundamentalsV1]


class ProfileRefV1(Contract):
    """Ein Scoring-Profil in einer bestimmten Version (Phase 2b)."""

    profile_id: int
    version: int = Field(ge=1)


class ScoringRunCompletedV1(Contract):
    """scoring -> notification, web-api: das Ranking eines Bewertungslaufs."""

    run_id: int | None  # leer bei einem Rescore
    scoring_run_id: int  # scoring.scoring_run.id
    trigger: ScoringTrigger
    profile: ProfileRefV1 | None = None  # bis Phase 2b ohne Profil
    ranking: list[RankingRowV1] = Field(default_factory=list)


class ProfileSavedV1(Contract):
    """scoring -> web-api: eine neue Profil-Version wurde gespeichert."""

    profile_id: int
    version: int = Field(ge=1)


class ProfileActivatedV1(Contract):
    """scoring -> web-api: eine Profil-Version ist jetzt aktiv."""

    profile_id: int
    version: int = Field(ge=1)


class ReportSentV1(Contract):
    """notification -> web-api: der Report ist verschickt (bei ``dry_run`` nur gespeichert)."""

    run_id: int
    report_id: int  # reporting.report.id
    subject: str
    dry_run: bool


class RunFailedV1(Contract):
    """jede Stufe, Watchdog -> notification, web-api: ein Run ist gescheitert."""

    run_id: int
    stage: Stage
    reason: str  # z. B. "timeout" vom Watchdog oder die Fehlermeldung der Stufe
