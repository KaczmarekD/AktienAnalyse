"""Outbox und Inbox (P4.2, docs/architecture/events.md, ADR-0002).

Mindestens einmal zugestellt, einmal verarbeitet:

- Der Sender schreibt Fachdaten und Event in einer Transaktion (``Outbox``), das
  ``OutboxRelay`` veroeffentlicht danach (Publisher fuer JetStream:
  ``va_platform.nats.JetStreamPublisher``).
- Der Empfaenger verarbeitet ein Event je Consumer nur einmal (``Inbox``), in derselben
  Transaktion wie seine Fachdaten und Folge-Events.

Die Tabellen legt jeder Besitzer eines Schemas mit ``OutboxMixin`` und ``InboxMixin`` an.
"""

from .inbox import Inbox
from .models import InboxMixin, OutboxMixin, outbox_table_args
from .outbox import Outbox, OutboxMessage, OutboxRelay, Publisher, VolatileEventError

__all__ = [
    "Inbox",
    "InboxMixin",
    "Outbox",
    "OutboxMessage",
    "OutboxMixin",
    "OutboxRelay",
    "Publisher",
    "VolatileEventError",
    "outbox_table_args",
]
