"""Inbox des Empfaengers: jedes Event je Consumer nur einmal verarbeiten (P4.2).

JetStream stellt mindestens einmal zu, etwa erneut nach einem verlorenen Ack. Der Eintrag in
der Inbox entsteht in derselben Transaktion wie die Fachdaten und die Folge-Events (Outbox):
Scheitert die Verarbeitung, faellt alles zusammen weg, und die naechste Zustellung beginnt
von vorn. Gelingt sie, erkennt jede weitere Zustellung das Event am Eintrag.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from ..db import session_scope

if TYPE_CHECKING:
    from collections.abc import Callable
    from uuid import UUID

    from sqlalchemy import Engine
    from sqlalchemy.orm import Session

    from .models import InboxMixin

log = logging.getLogger(__name__)


class Inbox:
    """Die Inbox eines Schemas, ``model`` ist dessen Tabelle (``InboxMixin``)."""

    def __init__(self, model: type[InboxMixin]) -> None:
        self.model = model

    def claim(self, session: Session, message_id: UUID, consumer: str) -> bool:
        """``True``, wenn das Event fuer diesen Consumer neu ist. Der Eintrag gilt erst mit dem
        Commit der Session. Eine parallele Zustellung desselben Events wartet so lange: Nach
        dem Commit bekommt sie ``False``, nach einem Rollback ist sie selbst dran."""
        return self._insert(session, message_id, consumer, error=None)

    def seen(self, session: Session, message_id: UUID, consumer: str) -> bool:
        """Hat dieser Consumer das Event schon verarbeitet oder aufgegeben (P4.3b)?"""
        model = self.model
        query = select(model.message_id).where(
            model.message_id == message_id, model.consumer == consumer
        )
        return session.execute(query).first() is not None

    def record_dead_letter(
        self, session: Session, message_id: UUID, consumer: str, error: str
    ) -> bool:
        """Ein aufgegebenes Event (nach ``max_deliver``) mit Fehler vermerken. Danach gilt es
        fuer den Consumer als erledigt. ``False``, wenn es schon einen Eintrag gibt."""
        return self._insert(session, message_id, consumer, error=error)

    def process_once(
        self,
        engine: Engine,
        message_id: UUID,
        consumer: str,
        work: Callable[[Session], None],
    ) -> bool:
        """``work`` in einer Transaktion mit dem Inbox-Eintrag, nur fuer ein neues Event.

        ``work`` schreibt Fachdaten und Folge-Events in die uebergebene Session. ``False``, wenn
        das Event schon verarbeitet war. Wirft ``work``, ist nichts gespeichert.
        """
        with session_scope(engine) as session:
            if not self.claim(session, message_id, consumer):
                log.info("%s: Event %s schon verarbeitet, uebersprungen", consumer, message_id)
                return False
            work(session)
        return True

    def _insert(
        self, session: Session, message_id: UUID, consumer: str, *, error: str | None
    ) -> bool:
        model = self.model
        statement = (
            insert(model)
            .values(message_id=message_id, consumer=consumer, error=error)
            .on_conflict_do_nothing()
            .returning(model.message_id)
        )
        return session.execute(statement).first() is not None
