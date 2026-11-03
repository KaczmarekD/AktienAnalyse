"""Spalten von Outbox und Inbox als Mixins (P4.2).

Jeder Besitzer eines Schemas legt seine eigenen Tabellen damit an, etwa in
``va_scoring.adapters.postgres.models``::

    class ScoringOutbox(OutboxMixin, Base):
        __table_args__ = outbox_table_args("scoring")

    class ScoringInbox(InboxMixin, Base):
        __table_args__ = {"schema": "scoring"}

So bleibt jede Tabelle bei ihrem Modul (``tests/db/test_schema_boundaries.py``), und die Logik
gibt es nur einmal. Die Migration ``0009`` legt sie an, der Schreibschutz steht in
``va_platform.db.ddl``.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Index, func, text
from sqlalchemy.orm import Mapped, mapped_column


class OutboxMixin:
    """Ein Event, bis das Relay es veroeffentlicht hat. Einziges UPDATE: ``published_at``."""

    __tablename__ = "outbox"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)  # Event-ID = Nats-Msg-Id
    subject: Mapped[str]
    payload: Mapped[dict[str, Any]]  # die ganze Huelle (CloudEvents)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    published_at: Mapped[datetime | None]


def outbox_table_args(schema: str) -> tuple[Any, ...]:
    """``__table_args__`` der Outbox: Schema und Teilindex auf die offenen Eintraege."""
    pending = Index(
        "ix_outbox_pending", "created_at", postgresql_where=text("published_at IS NULL")
    )
    return (pending, {"schema": schema})


class InboxMixin:
    """Ein Event, das ein Consumer verarbeitet hat. Nur zum Anfuegen."""

    __tablename__ = "inbox"

    message_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    consumer: Mapped[str] = mapped_column(primary_key=True)
    processed_at: Mapped[datetime] = mapped_column(server_default=func.now())
    error: Mapped[str | None]  # nur bei einem aufgegebenen Event (Dead Letter)
