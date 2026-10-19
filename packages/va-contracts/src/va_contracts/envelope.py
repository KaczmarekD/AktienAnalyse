"""Huelle jedes Events nach CloudEvents 1.0 (docs/architecture/events.md, Abschnitt Envelope)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, model_validator

from .base import Contract
from .events.v1.catalog import BY_DATASCHEMA, EventSpec


class UnknownEventError(ValueError):
    """Typ oder Dataschema eines empfangenen Events stehen nicht im Katalog."""


class Envelope[T](Contract):
    """Ein Event: Metadaten plus Payload ``data``.

    ``id`` ist eine UUIDv7 und zugleich ``Nats-Msg-Id`` fuer die Deduplizierung; sie ist
    zeitlich sortierbar. ``correlationid`` ist die ``batch.run.id`` als Text,
    ``causationid`` die ``id`` des ausloesenden Events. Die Tabellen in Postgres behalten
    ihre ``bigint``-IDs, UUIDs gibt es nur fuer Events.

    Ist ``data`` ein Contract, muessen ``type`` und ``dataschema`` laut Katalog genau zu
    seinem Modell gehoeren. ``Envelope[dict[str, Any]]`` liest nur die Huelle.
    """

    specversion: Literal["1.0"] = "1.0"
    id: UUID
    type: str  # z. B. "scoring.run.completed"
    source: str  # z. B. "va/scoring"
    time: AwareDatetime
    dataschema: str  # z. B. "urn:va-contracts:scoring.run.completed:v1"
    correlationid: str | None = None
    causationid: UUID | None = None
    data: T

    @model_validator(mode="after")
    def _data_matches_the_catalog(self) -> Self:
        if not isinstance(self.data, Contract):
            return self
        spec = BY_DATASCHEMA.get(self.dataschema)
        if spec is None or spec.type != self.type or type(self.data) is not spec.model:
            msg = (
                f"{type(self.data).__name__} passt nicht zu type={self.type!r}, "
                f"dataschema={self.dataschema!r}"
            )
            raise ValueError(msg)
        return self


def new_envelope[T: Contract](
    spec: EventSpec[T],
    data: T,
    *,
    source: str,
    correlationid: str | None = None,
    causationid: UUID | None = None,
) -> Envelope[T]:
    """Huellt eine Payload ein. Typ und Dataschema kommen aus dem Katalog."""
    if type(data) is not spec.model:
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


def parse_envelope(raw: str | bytes) -> Envelope[Contract]:
    """Empfaengerseite: rohes JSON -> Envelope mit dem Payload-Modell aus dem Katalog.

    Wirft ``UnknownEventError`` fuer ein Dataschema, das dieser Stand nicht kennt (etwa
    eine neuere Version), und ``ValidationError`` fuer eine ungueltige Payload.
    """
    head = Envelope[dict[str, Any]].model_validate_json(raw)
    spec = BY_DATASCHEMA.get(head.dataschema)
    if spec is None or spec.type != head.type:
        msg = f"unbekanntes Event: type={head.type!r}, dataschema={head.dataschema!r}"
        raise UnknownEventError(msg)
    return Envelope[Contract].model_validate(
        {**head.model_dump(exclude={"data"}), "data": spec.model.model_validate(head.data)}
    )
