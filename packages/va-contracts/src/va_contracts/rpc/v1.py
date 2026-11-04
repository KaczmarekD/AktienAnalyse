"""Request/Reply v1 (P4.8): Vorschau und Profil-Befehle zwischen web-api und scoring.

Subjects ``rpc.va.<name>`` liegen auf Core-NATS, ausserhalb des Streams (events.md). Jede Antwort
traegt ein optionales ``error``: Fehler gehen als Antwort zurueck, nicht als Ausnahme im Transport.
Die Felder spiegeln die Ports des web-api (``va_web_api.ports``), damit die REST-API gleich bleibt.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Literal

from pydantic import Field

from ..base import Contract, PositiveId
from ..profile import ProfileParamsV1

# no_data: noch kein Bewertungslauf fuer die Vorschau; invalid: Anfrage passt nicht zum Modell;
# internal: Exception beim Antwortenden (Details nur im Log des Workers)
RpcErrorCode = Literal[
    "no_data", "unknown_profile", "unknown_version", "conflict", "invalid", "internal"
]


class RpcErrorV1(Contract):
    code: RpcErrorCode
    message: str
    newest: int | None = None  # bei conflict: die neueste Version des Profils


class RpcReplyV1(Contract):
    """Basis jeder Antwort: Ohne ``error`` ist sie ein Erfolg."""

    error: RpcErrorV1 | None = None


# -- scoring.factors ----------------------------------------------------------------------


class FactorsRequestV1(Contract):
    pass


class FactorV1(Contract):
    key: str
    group: Literal["value", "quality"]
    label: str
    better: Literal["low", "high"]
    hint: str


class FactorsReplyV1(RpcReplyV1):
    factors: list[FactorV1] = Field(default_factory=list)


# -- scoring.preview ----------------------------------------------------------------------


class PreviewRequestV1(Contract):
    params: ProfileParamsV1


class RankedTitleV1(Contract):
    """Ein Titel im Ranking der Vorschau; ohne Rang am Groessenfilter gescheitert oder ohne
    Composite."""

    symbol: str
    name: str | None
    index: str | None
    passed_filter: bool
    rank: int | None
    composite_score: float | None
    value_score: float | None
    quality_score: float | None
    value_trap_flag: bool | None


class PreviewBasisV1(Contract):
    """Dieselben Daten zweimal bewertet: mit dem aktiven Profil und mit den neuen Parametern."""

    scoring_run_id: PositiveId
    fetch_run_id: PositiveId
    fetched_on: date | None
    active_profile_id: int | None
    active_name: str | None
    active_version: int | None
    current: list[RankedTitleV1]
    preview: list[RankedTitleV1]


class PreviewReplyV1(RpcReplyV1):
    basis: PreviewBasisV1 | None = None


# -- scoring.profiles.save / .activate ----------------------------------------------------


class SaveVersionRequestV1(Contract):
    profile_id: PositiveId
    params: ProfileParamsV1
    based_on: int = Field(ge=0)  # Version, auf der die Aenderung beruht
    comment: str | None = None


class SaveVersionReplyV1(RpcReplyV1):
    version: int | None = None


class ActivateRequestV1(Contract):
    profile_id: PositiveId
    version: int = Field(ge=1)


class ActivateReplyV1(RpcReplyV1):
    pass


# -- Katalog ------------------------------------------------------------------------------


@dataclass(frozen=True)
class RpcSpec[Q: Contract, R: RpcReplyV1]:
    """Ein Befehl: Name, Subject und die Modelle von Anfrage und Antwort."""

    name: str
    request: type[Q]
    reply: type[R]

    @property
    def subject(self) -> str:
        return f"rpc.va.{self.name}"


SCORING_FACTORS = RpcSpec("scoring.factors", FactorsRequestV1, FactorsReplyV1)
SCORING_PREVIEW = RpcSpec("scoring.preview", PreviewRequestV1, PreviewReplyV1)
PROFILE_SAVE = RpcSpec("scoring.profiles.save", SaveVersionRequestV1, SaveVersionReplyV1)
PROFILE_ACTIVATE = RpcSpec("scoring.profiles.activate", ActivateRequestV1, ActivateReplyV1)

RPCS: dict[str, RpcSpec[Any, Any]] = {
    spec.name: spec for spec in (SCORING_FACTORS, SCORING_PREVIEW, PROFILE_SAVE, PROFILE_ACTIVATE)
}

__all__ = [
    "PROFILE_ACTIVATE",
    "PROFILE_SAVE",
    "RPCS",
    "SCORING_FACTORS",
    "SCORING_PREVIEW",
    "ActivateReplyV1",
    "ActivateRequestV1",
    "FactorV1",
    "FactorsReplyV1",
    "FactorsRequestV1",
    "PreviewBasisV1",
    "PreviewReplyV1",
    "PreviewRequestV1",
    "RankedTitleV1",
    "RpcErrorCode",
    "RpcErrorV1",
    "RpcReplyV1",
    "RpcSpec",
    "SaveVersionReplyV1",
    "SaveVersionRequestV1",
]
