"""Event-Katalog v1: Typ, Subject, Payload-Modell und Dataschema je Event."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from ...base import Contract
from .payloads import (
    EmailConfirmationRequestedV1,
    FetchProgressedV1,
    PricesCompletedV1,
    PricesRequestedV1,
    ProfileActivatedV1,
    ProfileSavedV1,
    ReportSentV1,
    RunFailedV1,
    ScoringRunCompletedV1,
    ScreeningRunRequestedV1,
    SnapshotCompletedV1,
)


@dataclass(frozen=True)
class EventSpec[T: Contract]:
    """Ein Event des Katalogs.

    ``subject``: dauerhafte Events unter ``va.>`` (Stream ``VA_EVENTS``), fluechtige unter
    ``live.va.``, damit JetStream sie nicht speichert. Seit D1.6 private unter ``priv.va.``
    (Stream ``VA_PRIVATE``, nur im Speicher, 24 h): Mail-Adressen, Links, spaeter Bestaende.
    ``dataschema`` ist eine URN, weil CloudEvents 1.0 dort eine absolute URI verlangt.

    ``max_age``: so lange darf das Event beim Empfaenger ankommen; ohne Angabe gilt die Grenze
    des Empfaengers (``RUN_TIMEOUT_MINUTES`` fuer die Run-Kette).
    """

    type: str
    model: type[T]
    volatile: bool = False
    private: bool = False
    max_age: timedelta | None = None

    @property
    def subject(self) -> str:
        if self.volatile:
            return f"live.va.{self.type}"
        return f"priv.va.{self.type}" if self.private else f"va.{self.type}"

    @property
    def dataschema(self) -> str:
        return f"urn:va-contracts:{self.type}:v1"


RUN_REQUESTED = EventSpec("screening.run.requested", ScreeningRunRequestedV1)
FETCH_PROGRESSED = EventSpec("marketdata.fetch.progressed", FetchProgressedV1, volatile=True)
SNAPSHOT_COMPLETED = EventSpec("marketdata.snapshot.completed", SnapshotCompletedV1)
SCORING_RUN_COMPLETED = EventSpec("scoring.run.completed", ScoringRunCompletedV1)
PROFILE_SAVED = EventSpec("scoring.profile.saved", ProfileSavedV1)
PROFILE_ACTIVATED = EventSpec("scoring.profile.activated", ProfileActivatedV1)
REPORT_SENT = EventSpec("notification.report.sent", ReportSentV1)
RUN_FAILED = EventSpec("screening.run.failed", RunFailedV1)
# D1.6: privat, der Link gilt 24 h
EMAIL_CONFIRMATION_REQUESTED = EventSpec(
    "identity.email_confirmation.requested",
    EmailConfirmationRequestedV1,
    private=True,
    max_age=timedelta(hours=24),
)

# D2.3: Tageskurse; wie die Bestaetigung 24 h gueltig, damit ein NAS-Neustart sie nicht verliert
PRICES_REQUESTED = EventSpec(
    "marketdata.prices.requested", PricesRequestedV1, max_age=timedelta(hours=24)
)
PRICES_COMPLETED = EventSpec(
    "marketdata.prices.completed", PricesCompletedV1, max_age=timedelta(hours=24)
)

EVENTS: dict[str, EventSpec[Any]] = {
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
        EMAIL_CONFIRMATION_REQUESTED,
        PRICES_REQUESTED,
        PRICES_COMPLETED,
    )
}

# Empfaengerseite: Das Dataschema waehlt das Modell (mit v2 kommen weitere Eintraege dazu)
BY_DATASCHEMA: dict[str, EventSpec[Any]] = {spec.dataschema: spec for spec in EVENTS.values()}
