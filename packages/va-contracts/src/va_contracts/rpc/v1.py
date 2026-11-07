"""Request/Reply v1: Vorschau und Profil-Befehle (P4.8), Profile und Reports lesen (P4.9).

Subjects ``rpc.va.<name>`` liegen auf Core-NATS, ausserhalb des Streams (events.md). Jede Antwort
traegt ein optionales ``error``: Fehler gehen als Antwort zurueck, nicht als Ausnahme im Transport.
Die Felder spiegeln die Ports des web-api (``va_web_api.ports``), damit die REST-API gleich bleibt.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Literal

from pydantic import ConfigDict, Field

from ..base import Contract, PositiveId
from ..profile import ProfileParamsV1
from ..securities import IsinStr, SecurityHitV1, SecurityV1

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


# -- scoring.profiles.list / .get (P4.9) --------------------------------------------------


class ProfilesRequestV1(Contract):
    pass


class ProfileSummaryV1(Contract):
    id: PositiveId
    name: str
    created_at: datetime
    latest_version: int | None
    active_version: int | None  # leer, wenn ein anderes Profil aktiv ist


class ProfileVersionV1(Contract):
    version: int = Field(ge=1)
    params: ProfileParamsV1
    parent_version: int | None
    comment: str | None
    created_at: datetime
    active: bool


class ProfileDetailV1(ProfileSummaryV1):
    versions: list[ProfileVersionV1]  # neueste zuerst


class ProfilesReplyV1(RpcReplyV1):
    profiles: list[ProfileSummaryV1] = Field(default_factory=list)


class ProfileGetRequestV1(Contract):
    profile_id: PositiveId


class ProfileReplyV1(RpcReplyV1):
    profile: ProfileDetailV1 | None = None  # leer: unbekanntes Profil


# -- notification.report / .report.csv (P4.9) ---------------------------------------------


class ReportRequestV1(Contract):
    report_id: PositiveId


class ReportV1(Contract):
    id: PositiveId
    run_id: int | None
    scoring_run_id: int | None
    subject: str
    generated_at: datetime
    csv_filename: str
    html: str


class ReportReplyV1(RpcReplyV1):
    report: ReportV1 | None = None  # leer: unbekannter Report


class ReportCsvReplyV1(RpcReplyV1):
    # Bytes im JSON als Base64; in Python bleiben es die rohen Bytes der Datei
    model_config = ConfigDict(ser_json_bytes="base64", val_json_bytes="base64")

    filename: str | None = None  # beides leer: unbekannter Report
    content: bytes | None = None  # die CSV-Datei mit BOM


# -- marketdata.securities.search / .resolve (D2.1) -------------------------------------


class SecuritySearchRequestV1(Contract):
    """ISIN, WKN, Name oder Symbol; unter drei Zeichen sucht market-data nicht."""

    query: str = Field(min_length=1, max_length=100)


class SecuritySearchReplyV1(RpcReplyV1):
    hits: list[SecurityHitV1] = Field(default_factory=list)


class SecurityResolveRequestV1(Contract):
    """``symbol``: ein vom Nutzer gewaehltes Listing statt Xetra oder Heimatboerse (WP-03)."""

    isin: IsinStr
    symbol: str | None = Field(default=None, max_length=40)


class SecurityResolveReplyV1(RpcReplyV1):
    security: SecurityV1 | None = None  # leer: unbekannte ISIN


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

PROFILE_LIST = RpcSpec("scoring.profiles.list", ProfilesRequestV1, ProfilesReplyV1)
PROFILE_GET = RpcSpec("scoring.profiles.get", ProfileGetRequestV1, ProfileReplyV1)
REPORT_GET = RpcSpec("notification.report", ReportRequestV1, ReportReplyV1)
REPORT_CSV = RpcSpec("notification.report.csv", ReportRequestV1, ReportCsvReplyV1)
SECURITIES_SEARCH = RpcSpec(
    "marketdata.securities.search", SecuritySearchRequestV1, SecuritySearchReplyV1
)
SECURITIES_RESOLVE = RpcSpec(
    "marketdata.securities.resolve", SecurityResolveRequestV1, SecurityResolveReplyV1
)

RPCS: dict[str, RpcSpec[Any, Any]] = {
    spec.name: spec
    for spec in (
        SCORING_FACTORS,
        SCORING_PREVIEW,
        PROFILE_SAVE,
        PROFILE_ACTIVATE,
        PROFILE_LIST,
        PROFILE_GET,
        REPORT_GET,
        REPORT_CSV,
        SECURITIES_SEARCH,
        SECURITIES_RESOLVE,
    )
}

__all__ = [
    "PROFILE_ACTIVATE",
    "PROFILE_GET",
    "PROFILE_LIST",
    "PROFILE_SAVE",
    "REPORT_CSV",
    "REPORT_GET",
    "RPCS",
    "SCORING_FACTORS",
    "SCORING_PREVIEW",
    "SECURITIES_RESOLVE",
    "SECURITIES_SEARCH",
    "ActivateReplyV1",
    "ActivateRequestV1",
    "FactorV1",
    "FactorsReplyV1",
    "FactorsRequestV1",
    "PreviewBasisV1",
    "PreviewReplyV1",
    "PreviewRequestV1",
    "ProfileDetailV1",
    "ProfileGetRequestV1",
    "ProfileReplyV1",
    "ProfileSummaryV1",
    "ProfileVersionV1",
    "ProfilesReplyV1",
    "ProfilesRequestV1",
    "RankedTitleV1",
    "ReportCsvReplyV1",
    "ReportReplyV1",
    "ReportRequestV1",
    "ReportV1",
    "RpcErrorCode",
    "RpcErrorV1",
    "RpcReplyV1",
    "RpcSpec",
    "SaveVersionReplyV1",
    "SaveVersionRequestV1",
    "SecurityResolveReplyV1",
    "SecurityResolveRequestV1",
    "SecuritySearchReplyV1",
    "SecuritySearchRequestV1",
]
