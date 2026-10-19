"""Huelle jedes Events nach CloudEvents 1.0 (docs/architecture/events.md, Abschnitt Envelope)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal
from uuid import UUID

from pydantic import AwareDatetime

from .base import Contract

if TYPE_CHECKING:
    from .events.v1.catalog import EventSpec


class Envelope[T](Contract):
    """Ein Event: Metadaten plus Payload ``data``.

    ``id`` ist eine UUIDv7 und zugleich ``Nats-Msg-Id`` fuer die Deduplizierung; sie ist
    zeitlich sortierbar. ``correlationid`` ist die ``batch.run.id`` als Text,
    ``causationid`` die ``id`` des ausloesenden Events. Die Tabellen in Postgres behalten
    ihre ``bigint``-IDs, UUIDs gibt es nur fuer Events.
    """

    specversion: Literal["1.0"] = "1.0"
    id: UUID
    type: str  # z. B. "scoring.run.completed"
    source: str  # z. B. "va/scoring"
    time: AwareDatetime
    dataschema: str  # z. B. "va-contracts/scoring.run.completed/v1"
    correlationid: str | None = None
    causationid: UUID | None = None
    data: T


def new_envelope[T: Contract](
    spec: EventSpec,
    data: T,
    *,
    source: str,
    correlationid: str | None = None,
    causationid: UUID | None = None,
) -> Envelope[T]:
    """Huellt eine Payload ein. Typ und Dataschema kommen aus dem Katalog."""
    if not isinstance(data, spec.model):
        msg = f"{spec.type} erwartet {spec.model.__name__}, nicht {type(data).__name__}"
        raise TypeError(msg)
    return Envelope[T](
        id=uuid.uuid7(),
        type=spec.type,
        source=source,
        time=datetime.now(UTC),
        dataschema=spec.dataschema,
        correlationid=correlationid,
        causationid=causationid,
        data=data,
    )
