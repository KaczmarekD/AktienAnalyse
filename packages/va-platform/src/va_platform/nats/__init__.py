"""JetStream fuer die Events der Services (P4.1, docs/architecture/events.md, ADR-0002).

``provision`` legt den Stream ``VA_EVENTS`` und die durable Consumer an oder gleicht sie an die
Vorgabe an; ein zweiter Aufruf aendert nichts. Die Wahrheit liegt in Postgres, der Stream dient
der Zustellung und dem Nachspielen. Fluechtige Meldungen (``live.va.…``) und Request/Reply
(``rpc.va.…``) laufen bewusst ausserhalb des Streams.

Von der Kommandozeile: ``python -m va_platform.nats`` mit ``NATS_URL``. Ab P4.3 rufen die
Services ``provision`` beim Start selbst.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from nats.js.api import AckPolicy, ConsumerConfig, StorageType, StreamConfig
from nats.js.errors import NotFoundError

if TYPE_CHECKING:
    from nats.js.manager import JetStreamManager

log = logging.getLogger(__name__)

STREAM_NAME = "VA_EVENTS"
DAY = 24 * 60 * 60.0
RETENTION = 30 * DAY  # Aufbewahrung im Stream; Postgres behaelt alles
DUPLICATE_WINDOW = 10 * 60.0  # gleiche Nats-Msg-Id (= Event-ID) wird so lange verworfen
MAX_DELIVER = 5  # danach endet der Run ueber va.screening.run.failed (P4.3)
ACK_WAIT = 60.0  # lange Handler senden In-Progress-Acks (market-data, ab P4.3)


@dataclass(frozen=True)
class ConsumerSpec:
    """Ein durable Pull-Consumer und die Subjects, die er bekommt."""

    durable: str
    subjects: tuple[str, ...]

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
)


def stream_config() -> StreamConfig:
    return StreamConfig(
        name=STREAM_NAME,
        subjects=["va.>"],
        storage=StorageType.FILE,
        max_age=RETENTION,
        duplicate_window=DUPLICATE_WINDOW,
    )


async def provision(jsm: JetStreamManager) -> None:
    """Stream und Consumer wie vorgegeben, idempotent."""
    await _ensure_stream(jsm, stream_config())
    for spec in CONSUMERS:
        await _ensure_consumer(jsm, spec)


async def _ensure_stream(jsm: JetStreamManager, wanted: StreamConfig) -> None:
    try:
        current = (await jsm.stream_info(STREAM_NAME)).config
    except NotFoundError:
        await jsm.add_stream(wanted)
        log.info("Stream %s angelegt", STREAM_NAME)
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
        await jsm.update_stream(current)
        log.info("Stream %s angeglichen: %s", STREAM_NAME, ", ".join(sorted(drift)))


async def _ensure_consumer(jsm: JetStreamManager, spec: ConsumerSpec) -> None:
    wanted = spec.config()
    try:
        current = (await jsm.consumer_info(STREAM_NAME, spec.durable)).config
    except NotFoundError:
        await jsm.add_consumer(STREAM_NAME, wanted)
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
        await jsm.add_consumer(STREAM_NAME, wanted)
        log.info("Consumer %s angeglichen", spec.durable)
