"""Payloads der Events v1 (Katalog in docs/architecture/events.md)."""

from __future__ import annotations

from datetime import date
from typing import Literal, Self

from pydantic import Field, model_validator

from ...base import Contract, PositiveId
from .fundamentals import FundamentalsV1
from .ranking import RankingRowV1

# Wer einen Run ausgeloest hat. "rescore": Neubewertung nach einer Profil-Aktivierung,
# ohne Abruf, ohne batch.run, ohne Mail und ohne Healthcheck-Ping.
RunTrigger = Literal["scheduled", "manual"]
ScoringTrigger = Literal["scheduled", "manual", "rescore"]
# Stufe, an der ein Run gescheitert ist; der Watchdog meldet haengende Runs
Stage = Literal["market-data", "scoring", "notification", "watchdog"]


class RunOptionsV1(Contract):
    """Optionen eines Runs. Sie reisen mit, damit jede Stufe allein entscheiden kann."""

    force_refresh: bool = False  # Snapshot vom selben Tag nicht wiederverwenden
    dry_run: bool = False  # Mail rendern und speichern, nicht verschicken
    notify: bool = True  # False: kein Mailversand, z. B. fuer Test-Runs und Rescores


class UniverseMemberV1(Contract):
    """Ein Titel, der in der Indexquelle gegenueber der Fallback-CSV neu ist oder fehlt."""

    symbol: str
    name: str
    index: str  # DAX / MDAX


class UniverseInfoV1(Contract):
    """Woher das Universum kam. Der Report zeigt es, ``size`` zaehlt fuer partial/ok."""

    source: str | None  # iShares / Deka / Fallback-CSV
    as_of: date | None  # Stichtag der Indexquelle (Deka: keiner)
    size: int = Field(ge=0)  # Titel im Universum, vor dem Groessenfilter
    added: list[UniverseMemberV1] = Field(default_factory=list)
    removed: list[UniverseMemberV1] = Field(default_factory=list)


class _RunScoped(Contract):
    """Gemeinsame Regel: Ein Rescore hat keinen Run, jeder andere Trigger braucht einen."""

    run_id: PositiveId | None  # batch.run.id, leer bei einem Rescore
    trigger: ScoringTrigger
    options: RunOptionsV1

    @model_validator(mode="after")
    def _run_matches_trigger(self) -> Self:
        if (self.trigger == "rescore") != (self.run_id is None):
            msg = "run_id ist genau bei trigger=rescore leer"
            raise ValueError(msg)
        return self


class ScreeningRunRequestedV1(Contract):
    """web-api -> market-data: einen Run starten."""

    run_id: PositiveId
    trigger: RunTrigger
    options: RunOptionsV1 = RunOptionsV1()


class FetchProgressedV1(Contract):
    """market-data -> web-api: Fortschritt des Abrufs (fluechtig, ausserhalb des Streams)."""

    run_id: PositiveId
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

    run_id: PositiveId
    trigger: RunTrigger
    options: RunOptionsV1
    fetch_run_id: PositiveId  # market_data.fetch_run.id
    as_of: date  # Tag des Abrufs
    success_share: float = Field(ge=0, le=1)  # Anteil der Titel mit Marktkapitalisierung
    universe: UniverseInfoV1
    fundamentals: list[FundamentalsV1]


class ProfileRefV1(Contract):
    """Ein Scoring-Profil in einer bestimmten Version (Phase 2b)."""

    profile_id: PositiveId
    version: int = Field(ge=1)
    name: str | None = None  # fuer den Footer der Mail, z. B. "Standard"


class ScoringRunCompletedV1(_RunScoped):
    """scoring -> notification, web-api: das Ranking eines Bewertungslaufs.

    Enthaelt alles, was notification fuer Mail und CSV braucht. Keine bewertbaren Daten
    sind kein leeres Ranking, sondern ``screening.run.failed`` mit ``reason="no_data"``.
    """

    scoring_run_id: PositiveId  # scoring.scoring_run.id
    fetch_run_id: PositiveId  # bewerteter Abruf, auch beim Rescore
    as_of: date  # Tag dieses Abrufs
    universe: UniverseInfoV1
    value_weight: float = Field(ge=0, le=1)
    quality_weight: float = Field(ge=0, le=1)
    profile: ProfileRefV1 | None = None  # bis Phase 2b ohne Profil
    ranking: list[RankingRowV1] = Field(min_length=1)


class ProfileSavedV1(Contract):
    """scoring -> web-api: eine neue Profil-Version wurde gespeichert."""

    profile_id: PositiveId
    version: int = Field(ge=1)


class ProfileActivatedV1(Contract):
    """scoring -> web-api: eine Profil-Version ist jetzt aktiv."""

    profile_id: PositiveId
    version: int = Field(ge=1)


class ReportSentV1(Contract):
    """notification -> web-api: der Report ist verschickt (bei ``dry_run`` nur gespeichert)."""

    run_id: PositiveId
    report_id: PositiveId  # reporting.report.id
    subject: str
    dry_run: bool


class RunFailedV1(_RunScoped):
    """jede Stufe, Watchdog -> notification, web-api: ein Run ist gescheitert.

    ``options`` entscheidet ueber die Fehlermail (nicht bei ``dry_run`` oder ohne
    ``notify``), ``trigger`` ueber den Healthcheck-Ping (nur bei ``scheduled``).
    """

    stage: Stage
    reason: str  # z. B. "timeout" (Watchdog), "no_data" oder die Fehlermeldung der Stufe
    scoring_run_id: PositiveId | None = None  # bei einem gescheiterten Rescore
