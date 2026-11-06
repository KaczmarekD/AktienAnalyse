"""WebSocket-Protokoll v1 (P4.5, docs/architecture/web-api-realtime.md).

Eigene Pydantic-Modelle mit camelCase-Feldnamen. Was der Client schickt, wird streng geprueft:
bekannte ``op``, Topics nach Muster, hoechstens ``MAX_TOPICS`` je Nachricht, keine fremden
Felder. Die Event-Payloads aus ``va-contracts`` (snake_case) bildet ``event_payload`` ab.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    ValidationError,
)
from pydantic.alias_generators import to_camel

PROTOCOL = "va.v1"  # Subprotokoll; ein Client ohne wird beim Handshake abgelehnt
MAX_MESSAGE_BYTES = 4096  # groessere Nachrichten schliessen die Verbindung (1009)
MAX_TOPICS = 20
# D1.3: user:<id> gehoert genau diesem Nutzer (Berechtigung prueft der Endpunkt)
TOPIC = re.compile(
    r"(runs|ranking|profiles|instrument:[A-Z0-9][A-Z0-9.\-]{0,19}|user:[1-9][0-9]{0,18})"
)
USER_TOPIC = re.compile(r"user:([1-9][0-9]{0,18})")
CLOSE_SESSION_ENDED = 4401  # D1.3: Sitzung abgemeldet, abgelaufen oder Konto deaktiviert


def topic_owner(topic: str) -> int | None:
    """Der Nutzer, dem ein Topic gehoert; ``None`` fuer die globalen Topics."""
    match = USER_TOPIC.fullmatch(topic)
    return None if match is None else int(match.group(1))


class ProtocolError(ValueError):
    """Eine ungueltige Nachricht des Clients; der Server antwortet mit ``error``."""

    def __init__(self, message: str, code: str = "bad_request") -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _topic(value: str) -> str:
    if not TOPIC.fullmatch(value):
        msg = f"unbekanntes Topic: {value[:40]}"
        raise ValueError(msg)
    return value


Topic = Annotated[str, AfterValidator(_topic)]
Topics = Annotated[list[Topic], Field(min_length=1, max_length=MAX_TOPICS)]


class _Message(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel, populate_by_name=True, extra="forbid", frozen=True
    )


# --- Client -> Server ------------------------------------------------------------------------


class Subscribe(_Message):
    op: Literal["subscribe"]
    topics: Topics
    resume_from: int | None = Field(default=None, ge=0, strict=True)


class Unsubscribe(_Message):
    op: Literal["unsubscribe"]
    topics: Topics


class Ping(_Message):
    op: Literal["ping"]


type ClientMessage = Annotated[Subscribe | Unsubscribe | Ping, Field(discriminator="op")]
_CLIENT: TypeAdapter[Subscribe | Unsubscribe | Ping] = TypeAdapter(ClientMessage)


def parse_client_message(raw: str) -> Subscribe | Unsubscribe | Ping:
    try:
        return _CLIENT.validate_json(raw)
    except ValidationError as error:
        first = error.errors()[0]
        where = ".".join(str(part) for part in first.get("loc", ())) or "Nachricht"
        raise ProtocolError(f"{where}: {first.get('msg', 'ungueltig')}") from None


# --- Server -> Client ------------------------------------------------------------------------


class Hello(_Message):
    op: Literal["hello"] = "hello"
    server_time: datetime
    last_seq: int | None


class Event(_Message):
    op: Literal["event"] = "event"
    topic: str
    type: str
    seq: int | None  # nur dauerhafte Events; fluechtige (Fortschritt) ohne
    data: dict[str, Any]


class Resync(_Message):
    op: Literal["resync"] = "resync"
    topic: str


class Pong(_Message):
    op: Literal["pong"] = "pong"


class Error(_Message):
    op: Literal["error"] = "error"
    code: str
    message: str


type ServerMessage = Hello | Event | Resync | Pong | Error


def encode(message: ServerMessage) -> str:
    return message.model_dump_json(by_alias=True)


def event_payload(event_type: str, data: dict[str, Any]) -> dict[str, Any]:
    """Payload eines Events fuer den WebSocket: camelCase, ohne grosse Listen.

    ``scoring.run.completed`` traegt die ganze Rangliste (90 Titel mit Fundamentaldaten). Der
    WebSocket meldet nur, dass es sie gibt (``rankingSize``); das UI laedt sie per REST.
    """
    payload = dict(data)
    if event_type == "scoring.run.completed":
        ranking = payload.pop("ranking", None) or []
        payload["ranking_size"] = len(ranking)
    return _camel(payload)


def _camel(value: Any) -> Any:
    if isinstance(value, dict):
        return {to_camel(str(key)): _camel(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_camel(item) for item in value]
    return value
