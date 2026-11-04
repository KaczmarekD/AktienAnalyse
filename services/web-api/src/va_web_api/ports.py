"""Ports des web-api: Code von scoring (P3.3), Run-Verwaltung (P4.7), Lesemodell (P4.9).

Phase 3: umgesetzt im selben Prozess (Composition Root ``src.web``), weil das web-api
``va_scoring`` nicht importieren darf. Ab Phase 4 per Request/Reply ueber NATS (P4.8). Die
REST-API bleibt dabei gleich.

``RunStarter`` setzt ``va_web_api.runs.RunManager`` um; die API-Tests nehmen einen Fake.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from datetime import date

    from va_contracts.events.v1 import RunOptionsV1
    from va_contracts.profile import ProfileParamsV1

    from .models import (
        Factor,
        Instrument,
        ProfileDetail,
        ProfileSummary,
        Ranking,
        Report,
        RunDetail,
        RunSummary,
    )


@dataclass(frozen=True)
class RankedTitle:
    """Ein Titel in einem Ranking der Vorschau; ohne Rang, wenn er am Groessenfilter scheitert
    oder keinen Composite hat."""

    symbol: str
    name: str | None
    index: str | None
    passed_filter: bool
    rank: int | None
    composite_score: float | None
    value_score: float | None
    quality_score: float | None
    value_trap_flag: bool | None


@dataclass(frozen=True)
class PreviewBasis:
    """Dieselben Daten zweimal bewertet: mit dem aktiven Profil und mit den neuen params."""

    scoring_run_id: int  # juengster Bewertungslauf, sein Abruf ist die Grundlage
    fetch_run_id: int
    fetched_on: date | None
    active_profile_id: int | None  # alle drei leer, wenn noch kein Profil aktiv ist
    active_name: str | None
    active_version: int | None
    current: list[RankedTitle]  # Rangfolge
    preview: list[RankedTitle]  # Rangfolge


class NoPreviewData(LookupError):
    """Noch kein Bewertungslauf, auf dessen Daten sich vergleichen liesse."""


class UnknownProfile(LookupError):
    pass


class UnknownVersion(LookupError):
    pass


class RemoteUnavailable(Exception):
    """Ein anderer Service antwortet nicht: keine NATS-Verbindung oder kein Worker (503)."""

    service = "Service"

    def __init__(self, what: str = "") -> None:
        super().__init__(what or self.service)


class ScoringUnavailable(RemoteUnavailable):
    """Vorschau und Profile (P4.8, P4.9)."""

    service = "Scoring"


class NotificationUnavailable(RemoteUnavailable):
    """Reports (P4.9)."""

    service = "Notification"


class ProfileConflict(Exception):
    """Die Version, auf der die Aenderung beruht, ist nicht mehr die neueste."""

    def __init__(self, newest: int) -> None:
        super().__init__(newest)
        self.newest = newest


class ScoringPreview(Protocol):
    """Der lesende Teil von scoring: Faktor-Katalog und Vorschau, ohne zu speichern."""

    def factors(self) -> list[Factor]: ...

    def preview(self, params: ProfileParamsV1) -> PreviewBasis: ...


class ProfileCommands(Protocol):
    """Der schreibende Teil: neue Version, Aktivierung (Rolle ``va_profiles``)."""

    def save_version(
        self, profile_id: int, params: ProfileParamsV1, *, based_on: int, comment: str | None
    ) -> int:
        """Legt die Version nach ``based_on`` an und liefert ihre Nummer.

        Wirft ``ProfileConflict``, wenn ``based_on`` nicht mehr die neueste Version ist.
        """
        ...

    def activate(self, profile_id: int, version: int) -> None: ...


class RunActive(Exception):
    """Ein Run laeuft noch; ein manueller Start wartet, bis er fertig ist (P4.7)."""

    def __init__(self, run_id: int) -> None:
        super().__init__(run_id)
        self.run_id = run_id


class RunStarter(Protocol):
    def start(self, options: RunOptionsV1) -> int:
        """Legt einen manuellen Run an und gibt seine ID zurueck; ``RunActive``, wenn einer laeuft."""
        ...


class ReadModel(Protocol):
    """Was die lesenden REST-Endpunkte brauchen (P4.9). ``None``: nicht gefunden (404).

    Umgesetzt aus den Tabellen (``read_models.TableReadModel``, Rolle ``va_read``) und aus den
    Projektionen mit Request/Reply (``read_models.ProjectionReadModel``, Rolle ``va_web``).
    """

    def list_runs(self, *, limit: int, offset: int) -> list[RunSummary]: ...

    def get_run(self, run_id: int) -> RunDetail | None: ...

    def latest_scoring_run_id(self) -> int | None: ...

    def get_ranking(self, scoring_run_id: int) -> Ranking | None: ...

    def get_instrument(self, symbol: str) -> Instrument | None: ...

    def get_report(self, report_id: int) -> Report | None: ...

    def get_report_csv(self, report_id: int) -> tuple[str, bytes] | None: ...

    def list_profiles(self) -> list[ProfileSummary]: ...

    def get_profile(self, profile_id: int) -> ProfileDetail | None: ...
