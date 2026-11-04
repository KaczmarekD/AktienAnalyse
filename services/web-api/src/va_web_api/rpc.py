"""Vorschau, Profil-Befehle (P4.8), Profile und Reports lesen (P4.9) ueber Request/Reply.

Die Befehle sind die entfernte Form der Ports ``ScoringPreview`` und ``ProfileCommands``. Beide
Richtungen liegen deshalb hier, das Format steht neutral in ``va_contracts.rpc.v1``:

- ``RemoteScoring`` setzt die Ports im web-api um: Anfrage senden, Antwort zurueck in die Typen und
  Exceptions der Ports. Ohne Verbindung oder ohne Antwort gibt es ``ScoringUnavailable`` (503).
- ``scoring_handlers`` ist die Gegenseite: Aus beliebigen Umsetzungen der Ports werden die Handler
  fuer ``NatsBus.serve``. Der Worker (``src.worker``) bedient sie mit dem Code aus P3.3, die Tests
  mit ihren Fakes. Nach Speichern und Aktivieren meldet ``notify`` das Profil-Event.
- ``RemoteReads`` (P4.9): Profile und Reports fuer das ``ReadModel`` aus den Projektionen. Die
  Gegenseite steht seit P5.1a bei ihren Besitzern (``va_scoring``, ``va_notification``).
- Den Server fuer scoring stellt seit P5.1a scoring selbst (``va_scoring.entrypoints.rpc``).
  ``scoring_handlers`` bleibt als Server fuer beliebige Umsetzungen der Ports, etwa die Fakes
  der API-Tests.
"""

from __future__ import annotations

import logging
from dataclasses import asdict
from typing import TYPE_CHECKING, Any, Protocol

from va_contracts import new_envelope
from va_contracts.events.v1 import (
    PROFILE_ACTIVATED,
    PROFILE_SAVED,
    ProfileActivatedV1,
    ProfileSavedV1,
)
from va_contracts.rpc.v1 import (
    PROFILE_ACTIVATE,
    PROFILE_GET,
    PROFILE_LIST,
    PROFILE_SAVE,
    REPORT_CSV,
    REPORT_GET,
    SCORING_FACTORS,
    SCORING_PREVIEW,
    ActivateReplyV1,
    ActivateRequestV1,
    FactorsReplyV1,
    FactorsRequestV1,
    FactorV1,
    PreviewBasisV1,
    PreviewReplyV1,
    PreviewRequestV1,
    ProfileGetRequestV1,
    ProfilesRequestV1,
    ReportRequestV1,
    RpcErrorV1,
    RpcReplyV1,
    SaveVersionReplyV1,
    SaveVersionRequestV1,
)
from va_platform.nats import RpcUnavailable

from .models import Factor, ProfileDetail, ProfileSummary, Report
from .ports import (
    NoPreviewData,
    NotificationUnavailable,
    PreviewBasis,
    ProfileConflict,
    RankedTitle,
    RemoteUnavailable,
    ScoringUnavailable,
    UnknownProfile,
    UnknownVersion,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from va_contracts import Contract, Envelope
    from va_contracts.profile import ProfileParamsV1
    from va_contracts.rpc.v1 import RpcSpec

    from .ports import ProfileCommands, ScoringPreview

log = logging.getLogger(__name__)

SOURCE = "va/scoring"  # Absender der Profil-Events: scoring, auch wenn der Worker sie schickt


class RpcCaller(Protocol):
    """``NatsBus.call``; ``RpcUnavailable`` wird hier zu ``ScoringUnavailable``."""

    def call[Q: Contract, R: RpcReplyV1](self, spec: RpcSpec[Q, R], request: Q) -> R: ...


class RemoteScoring:
    """``ScoringPreview`` und ``ProfileCommands`` ueber NATS. ``bus`` liefert die Verbindung,
    solange keine steht ``None``."""

    def __init__(self, bus: Callable[[], RpcCaller | None]) -> None:
        self._bus = bus

    def factors(self) -> list[Factor]:
        reply = self._call(SCORING_FACTORS, FactorsRequestV1())
        return [Factor.model_validate(f.model_dump()) for f in reply.factors]

    def preview(self, params: ProfileParamsV1) -> PreviewBasis:
        reply = self._call(SCORING_PREVIEW, PreviewRequestV1(params=params))
        if reply.error is not None and reply.error.code == "no_data":
            raise NoPreviewData
        _raise(reply)
        assert reply.basis is not None
        data = reply.basis.model_dump()
        for key in ("current", "preview"):
            data[key] = [RankedTitle(**title) for title in data[key]]
        return PreviewBasis(**data)

    def save_version(
        self, profile_id: int, params: ProfileParamsV1, *, based_on: int, comment: str | None
    ) -> int:
        request = SaveVersionRequestV1(
            profile_id=profile_id, params=params, based_on=based_on, comment=comment
        )
        reply = self._call(PROFILE_SAVE, request)
        error = reply.error
        if error is not None and error.code == "unknown_profile":
            raise UnknownProfile(profile_id)
        if error is not None and error.code == "conflict":
            raise ProfileConflict(error.newest if error.newest is not None else based_on + 1)
        _raise(reply)
        assert reply.version is not None
        return reply.version

    def activate(self, profile_id: int, version: int) -> None:
        reply = self._call(
            PROFILE_ACTIVATE, ActivateRequestV1(profile_id=profile_id, version=version)
        )
        error = reply.error
        if error is not None and error.code == "unknown_profile":
            raise UnknownProfile(profile_id)
        if error is not None and error.code == "unknown_version":
            raise UnknownVersion(version)
        _raise(reply)

    def _call[Q: Contract, R: RpcReplyV1](self, spec: RpcSpec[Q, R], request: Q) -> R:
        return _request(self._bus, spec, request, ScoringUnavailable)


def _request[Q: Contract, R: RpcReplyV1](
    bus_of: Callable[[], RpcCaller | None],
    spec: RpcSpec[Q, R],
    request: Q,
    unavailable: type[RemoteUnavailable],
) -> R:
    bus = bus_of()
    if bus is None:
        raise unavailable(spec.name)
    try:
        return bus.call(spec, request)
    except RpcUnavailable as e:
        raise unavailable(spec.name) from e


class RemoteReads:
    """Profile und Reports per Request/Reply (P4.9): die Teile des ``ReadModel``, die nicht in den
    Projektionen des web-api liegen. Nicht gefunden ist eine leere Antwort (404)."""

    def __init__(self, bus: Callable[[], RpcCaller | None]) -> None:
        self._bus = bus

    def list_profiles(self) -> list[ProfileSummary]:
        reply = _request(self._bus, PROFILE_LIST, ProfilesRequestV1(), ScoringUnavailable)
        _raise(reply)
        return [ProfileSummary.model_validate(p.model_dump()) for p in reply.profiles]

    def get_profile(self, profile_id: int) -> ProfileDetail | None:
        request = ProfileGetRequestV1(profile_id=profile_id)
        reply = _request(self._bus, PROFILE_GET, request, ScoringUnavailable)
        _raise(reply)
        profile = reply.profile
        return None if profile is None else ProfileDetail.model_validate(profile.model_dump())

    def get_report(self, report_id: int) -> Report | None:
        request = ReportRequestV1(report_id=report_id)
        reply = _request(self._bus, REPORT_GET, request, NotificationUnavailable)
        _raise(reply)
        report = reply.report
        return None if report is None else Report.model_validate(report.model_dump())

    def get_report_csv(self, report_id: int) -> tuple[str, bytes] | None:
        request = ReportRequestV1(report_id=report_id)
        reply = _request(self._bus, REPORT_CSV, request, NotificationUnavailable)
        _raise(reply)
        if reply.filename is None or reply.content is None:
            return None
        return reply.filename, reply.content


def _raise(reply: RpcReplyV1) -> None:
    """Uebrige Fehler (``invalid``, ``internal``) sind Bugs: 500 wie im Prozess."""
    if reply.error is not None:
        msg = f"scoring: {reply.error.code}: {reply.error.message}"
        raise RuntimeError(msg)


def scoring_handlers(
    preview: ScoringPreview,
    commands: ProfileCommands,
    *,
    notify: Callable[[Envelope[Any]], None] | None = None,
) -> dict[RpcSpec[Any, Any], Callable[[Any], RpcReplyV1]]:
    """Die Handler fuer ``NatsBus.serve`` (Queue ``scoring``), gebaut aus Umsetzungen der Ports.

    ``notify`` bekommt nach Speichern und Aktivieren das Profil-Event. Es geht ohne Outbox raus:
    Kein Read-Model haengt daran, ein verlorenes Event heisst nur, dass ein anderer Tab die neue
    Version erst beim naechsten Laden sieht.
    """

    def announce(envelope: Envelope[Any]) -> None:
        if notify is None:
            return
        try:
            notify(envelope)
        except Exception:
            log.warning("%s nicht gemeldet", envelope.type, exc_info=True)

    def factors(request: FactorsRequestV1) -> FactorsReplyV1:  # noqa: ARG001 - ohne Felder
        return FactorsReplyV1(
            factors=[FactorV1.model_validate(f.model_dump()) for f in preview.factors()]
        )

    def run_preview(request: PreviewRequestV1) -> PreviewReplyV1:
        try:
            basis = preview.preview(request.params)
        except NoPreviewData:
            return PreviewReplyV1(
                error=RpcErrorV1(code="no_data", message="Noch kein Bewertungslauf")
            )
        return PreviewReplyV1(basis=PreviewBasisV1.model_validate(asdict(basis)))

    def save(request: SaveVersionRequestV1) -> SaveVersionReplyV1:
        try:
            version = commands.save_version(
                request.profile_id,
                request.params,
                based_on=request.based_on,
                comment=request.comment,
            )
        except UnknownProfile:
            error = RpcErrorV1(code="unknown_profile", message=f"Profil {request.profile_id}")
            return SaveVersionReplyV1(error=error)
        except ProfileConflict as e:
            error = RpcErrorV1(code="conflict", message="nicht die neueste", newest=e.newest)
            return SaveVersionReplyV1(error=error)
        saved = ProfileSavedV1(profile_id=request.profile_id, version=version)
        announce(new_envelope(PROFILE_SAVED, saved, source=SOURCE))
        return SaveVersionReplyV1(version=version)

    def activate(request: ActivateRequestV1) -> ActivateReplyV1:
        try:
            commands.activate(request.profile_id, request.version)
        except UnknownProfile:
            error = RpcErrorV1(code="unknown_profile", message=f"Profil {request.profile_id}")
            return ActivateReplyV1(error=error)
        except UnknownVersion:
            error = RpcErrorV1(code="unknown_version", message=f"Version {request.version}")
            return ActivateReplyV1(error=error)
        activated = ProfileActivatedV1(profile_id=request.profile_id, version=request.version)
        announce(new_envelope(PROFILE_ACTIVATED, activated, source=SOURCE))
        return ActivateReplyV1()

    return {
        SCORING_FACTORS: factors,
        SCORING_PREVIEW: run_preview,
        PROFILE_SAVE: save,
        PROFILE_ACTIVATE: activate,
    }
