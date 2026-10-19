"""Event-Katalog v1: Typ, Subject, Payload-Modell und Dataschema je Event."""

from __future__ import annotations

from dataclasses import dataclass

from ...base import Contract
from .payloads import (
    FetchProgressedV1,
    ProfileActivatedV1,
    ProfileSavedV1,
    ReportSentV1,
    RunFailedV1,
    ScoringRunCompletedV1,
    ScreeningRunRequestedV1,
    SnapshotCompletedV1,
)


@dataclass(frozen=True)
class EventSpec:
    """Ein Event des Katalogs.

    ``subject``: dauerhafte Events unter ``va.>`` (Stream ``VA_EVENTS``), fluechtige unter
    ``live.va.``, damit JetStream sie nicht speichert.
    """

    type: str
    model: type[Contract]
    volatile: bool = False

    @property
    def subject(self) -> str:
        return f"live.va.{self.type}" if self.volatile else f"va.{self.type}"

    @property
    def dataschema(self) -> str:
        return f"va-contracts/{self.type}/v1"


RUN_REQUESTED = EventSpec("screening.run.requested", ScreeningRunRequestedV1)
FETCH_PROGRESSED = EventSpec("marketdata.fetch.progressed", FetchProgressedV1, volatile=True)
SNAPSHOT_COMPLETED = EventSpec("marketdata.snapshot.completed", SnapshotCompletedV1)
SCORING_RUN_COMPLETED = EventSpec("scoring.run.completed", ScoringRunCompletedV1)
PROFILE_SAVED = EventSpec("scoring.profile.saved", ProfileSavedV1)
PROFILE_ACTIVATED = EventSpec("scoring.profile.activated", ProfileActivatedV1)
REPORT_SENT = EventSpec("notification.report.sent", ReportSentV1)
RUN_FAILED = EventSpec("screening.run.failed", RunFailedV1)

EVENTS: dict[str, EventSpec] = {
    spec.type: spec
    for spec in (
        RUN_REQUESTED,
        FETCH_PROGRESSED,
        SNAPSHOT_COMPLETED,
        SCORING_RUN_COMPLETED,
        PROFILE_SAVED,
        PROFILE_ACTIVATED,
        REPORT_SENT,
        RUN_FAILED,
    )
}
