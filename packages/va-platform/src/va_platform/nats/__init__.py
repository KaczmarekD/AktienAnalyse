"""JetStream fuer die Events der Services (P4.1, docs/architecture/events.md, ADR-0002).

``provision`` legt den Stream ``VA_EVENTS`` und die durable Consumer an oder gleicht sie an die
Vorgabe an; ein zweiter Aufruf aendert nichts. Die Wahrheit liegt in Postgres, der Stream dient
der Zustellung und dem Nachspielen. Fluechtige Meldungen (``live.va.…``) und Request/Reply
(``rpc.va.…``) laufen bewusst ausserhalb des Streams.

Von der Kommandozeile: ``python -m va_platform.nats`` mit ``NATS_URL``. Ab P4.3 rufen die
Services ``provision`` beim Start selbst.

``JetStreamPublisher`` (P4.2) sendet fuer das Relay der Outbox (``va_platform.messaging``).
``NatsBus`` (P4.3, ``va_platform.nats.bus``) ist der ``EventBus`` ueber JetStream.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from nats.js.api import AckPolicy, ConsumerConfig, StorageType, StreamConfig
from nats.js.errors import NotFoundError

if TYPE_CHECKING:
    from collections.abc import Iterable

    from nats.js.client import JetStreamContext
    from nats.js.manager import JetStreamManager

    from ..messaging import OutboxMessage

log = logging.getLogger(__name__)

STREAM_NAME = "VA_EVENTS"
# D1.6: private Events (priv.va.>): Mail-Adressen, Links, spaeter Bestaende und Berichte. Nur im
# Speicher (nicht in natsdata, also nicht im Backup) und nach 24 h weg
PRIVATE_STREAM = "VA_PRIVATE"
DAY = 24 * 60 * 60.0
RETENTION = 30 * DAY  # Aufbewahrung im Stream; Postgres behaelt alles
PRIVATE_RETENTION = DAY
DUPLICATE_WINDOW = 10 * 60.0  # gleiche Nats-Msg-Id (= Event-ID) wird so lange verworfen
MAX_DELIVER = 5  # danach endet der Run ueber va.screening.run.failed (P4.3)
ACK_WAIT = 60.0  # lange Handler senden In-Progress-Acks (market-data, ab P4.3)


def stream_for(subject: str) -> str:
    """Der Stream, in dem ein Subject landet."""
    return PRIVATE_STREAM if subject.startswith("priv.va.") else STREAM_NAME


@dataclass(frozen=True)
class ConsumerSpec:
    """Ein durable Pull-Consumer, die Subjects, die er bekommt, und sein Stream.

    Die Namen sind ueber beide Streams eindeutig (``notification-private``): Der Bus fuehrt seine
    Consumer nur nach Namen.
    """

    durable: str
    subjects: tuple[str, ...]

    @property
    def stream(self) -> str:
        streams = {stream_for(subject) for subject in self.subjects}
        if len(streams) != 1:
            msg = f"Consumer {self.durable} mischt Streams: {', '.join(self.subjects)}"
            raise ValueError(msg)
        return streams.pop()

    def config(self) -> ConsumerConfig:
        config = ConsumerConfig(
            durable_name=self.durable,
            ack_policy=AckPolicy.EXPLICIT,
            max_deliver=MAX_DELIVER,
            ack_wait=ACK_WAIT,
        )
        if len(self.subjects) == 1:
            config.filter_subject = self.subjects[0]
        else:
            config.filter_subjects = list(self.subjects)
        return config


# Die Tabelle "Consumer" aus events.md
CONSUMERS = (
    ConsumerSpec("market-data", ("va.screening.run.requested",)),
    ConsumerSpec("scoring", ("va.marketdata.snapshot.completed",)),
    ConsumerSpec("notification", ("va.scoring.run.completed", "va.screening.run.failed")),
    ConsumerSpec("web-api", ("va.>",)),
    # P4.3: der RunTracker des Batches, Vorlaeufer der Run-Projektion im web-api
    ConsumerSpec(
        "batch",
        (
            "va.marketdata.snapshot.completed",
            "va.scoring.run.completed",
            "va.notification.report.sent",
            "va.screening.run.failed",
        ),
    ),
    # D1.6: Bestaetigungsmail (VA_PRIVATE)
    ConsumerSpec("notification-private", ("priv.va.identity.email_confirmation.requested",)),
)
CONSUMERS_BY_NAME = {spec.durable: spec for spec in CONSUMERS}


def stream_config() -> StreamConfig:
    return StreamConfig(
        name=STREAM_NAME,
        subjects=["va.>"],
        storage=StorageType.FILE,
        max_age=RETENTION,
        duplicate_window=DUPLICATE_WINDOW,
    )


def private_stream_config() -> StreamConfig:
    return StreamConfig(
        name=PRIVATE_STREAM,
        subjects=["priv.va.>"],
        storage=StorageType.MEMORY,
        max_age=PRIVATE_RETENTION,
        duplicate_window=DUPLICATE_WINDOW,
    )


STREAMS = {STREAM_NAME: stream_config, PRIVATE_STREAM: private_stream_config}


async def provision(
    jsm: JetStreamManager,
    *,
    consumers: Iterable[str] | None = None,
    streams: Iterable[str] | None = None,
) -> None:
    """Streams und Consumer wie vorgegeben, idempotent.

    ``consumers``: nur diese Consumer (D1.5). Mit einem NATS-Nutzer je Dienst darf ein Dienst nur
    seinen eigenen anlegen. Ohne Angabe alle (Batch, Werkzeuge, Tests).

    ``streams``: diese Streams; ohne Angabe ``VA_EVENTS`` und die Streams der Consumer (D1.6).
    ``VA_PRIVATE`` sieht so nur, wer ihn braucht; das web-api verlangt ihn, weil es dorthin sendet.
    """
    wanted = None if consumers is None else set(consumers)
    specs = [spec for spec in CONSUMERS if wanted is None or spec.durable in wanted]
    if streams is not None:
        names = set(streams)
    elif wanted is None:
        names = set(STREAMS)
    else:
        names = {STREAM_NAME, *(spec.stream for spec in specs)}
    for name, config in STREAMS.items():
        if name in names:
            await _ensure_stream(jsm, config())
    for spec in specs:
        await _ensure_consumer(jsm, spec)


def inbox_prefix(url: str) -> str:
    """Inbox des NATS-Nutzers aus der URL (D1.5): ``_INBOX.<nutzer>``, ohne Nutzer ``_INBOX``.

    Mit ``_INBOX.>`` laese jeder Dienst die Antworten an alle anderen mit; die Rechte in
    ``docker/nats/nats.conf`` erlauben jedem Nutzer nur seine eigene Inbox.
    """
    user = urlsplit(url).username
    return f"_INBOX.{user}" if user else "_INBOX"


async def _ensure_stream(jsm: JetStreamManager, wanted: StreamConfig) -> None:
    name = wanted.name
    assert name is not None
    try:
        current = (await jsm.stream_info(name)).config
    except NotFoundError:
        await jsm.add_stream(wanted)
        log.info("Stream %s angelegt", name)
        return
    drift = {
        field: getattr(wanted, field)
        for field in ("subjects", "max_age", "duplicate_window")
        if getattr(current, field) != getattr(wanted, field)
    }
    if drift:
        # Nur die eigenen Felder angleichen, die uebrigen behalten die Werte des Servers
        for field, value in drift.items():
            setattr(current, field, value)
        try:
            await jsm.update_stream(current)
        except Exception:
            # D1.5: Umstellen darf nur der NATS-Nutzer batch (make nats-provision); ein Dienst
            # laeuft mit dem bisherigen Stream weiter, statt nicht zu starten
            log.warning(
                "Stream %s weicht ab (%s), angleichen mit make nats-provision",
                name,
                ", ".join(sorted(drift)),
                exc_info=True,
            )
            return
        log.info("Stream %s angeglichen: %s", name, ", ".join(sorted(drift)))


async def _ensure_consumer(jsm: JetStreamManager, spec: ConsumerSpec) -> None:
    wanted = spec.config()
    try:
        current = (await jsm.consumer_info(spec.stream, spec.durable)).config
    except NotFoundError:
        await jsm.add_consumer(spec.stream, wanted)
        log.info("Consumer %s angelegt", spec.durable)
        return
    filters = sorted(current.filter_subjects or [current.filter_subject or ""])
    if (
        filters != sorted(spec.subjects)
        or current.ack_policy != wanted.ack_policy
        or current.max_deliver != wanted.max_deliver
        or current.ack_wait != wanted.ack_wait
    ):
        # Dieselbe Anfrage aendert einen bestehenden durable Consumer (NATS ab 2.10)
        await jsm.add_consumer(spec.stream, wanted)
        log.info("Consumer %s angeglichen", spec.durable)


class JetStreamPublisher:
    """``Publisher`` der Outbox fuer JetStream (P4.2).

    ``Nats-Msg-Id`` ist die Event-ID: Sendet das Relay ein Event noch einmal, verwirft JetStream
    es im Deduplizierungsfenster. ``stream`` verlangt die Bestaetigung des Streams, in den das
    Subject gehoert (``VA_EVENTS`` oder seit D1.6 ``VA_PRIVATE``). Fehlt der Stream oder antwortet
    NATS nicht, wirft ``publish``, und der Eintrag bleibt offen.
    """

    def __init__(self, js: JetStreamContext, *, timeout: float = 5.0) -> None:
        self._js = js
        self._timeout = timeout

    async def publish(self, message: OutboxMessage) -> None:
        await self._js.publish(
            message.subject,
            message.payload,
            timeout=self._timeout,
            stream=stream_for(message.subject),
            headers={"Nats-Msg-Id": str(message.id)},
        )


# Am Ende: bus.py nutzt die Namen oben (Stream, Grenzen, Provisionierung, Publisher)
from .bus import (  # noqa: E402
    RPC_TIMEOUT,
    NatsBus,
    RpcUnavailable,
    answer_request,
    current_sequence,
)

__all__ = [
    "ACK_WAIT",
    "CONSUMERS",
    "CONSUMERS_BY_NAME",
    "MAX_DELIVER",
    "PRIVATE_STREAM",
    "RPC_TIMEOUT",
    "STREAM_NAME",
    "ConsumerSpec",
    "JetStreamPublisher",
    "NatsBus",
    "RpcUnavailable",
    "answer_request",
    "current_sequence",
    "provision",
    "stream_config",
]
