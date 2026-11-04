"""Ports des web-api zum Code von scoring (P3.3) und zur Run-Verwaltung (P4.7).

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

    from .models import Factor


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


class ScoringUnavailable(Exception):
    """scoring antwortet nicht: keine NATS-Verbindung oder kein Worker (P4.8, 503)."""


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
