"""Scheduler der Tageskurse im web-api (D2.3, docs/architecture/depot/wertpapiere.md).

An Handelstagen nach Xetra-Schluss (``WEB_API_PRICE_SCHEDULE``, Standard 22:30 Mo-Fr
``Europe/Berlin``) schickt das web-api ``marketdata.prices.requested`` ueber seine Outbox. Die
Zeile in ``web.price_request`` (Termin eindeutig) und das Event entstehen in einer Transaktion:
je Termin genau eine Anfrage, auch nach einem Neustart oder mit zwei Takten zugleich. Feiertage
kennt der Scheduler nicht; market-data liefert dann den letzten Handelstag, und die Kurse dieses
Tages stehen schon in der Datenbank.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from sqlalchemy.dialects.postgresql import insert

from va_contracts import new_envelope, parse_envelope
from va_contracts.events.v1 import PRICES_REQUESTED, PricesRequestedV1
from va_platform.db import session_scope
from va_platform.messaging import Outbox, drain_outbox

from ..adapters.postgres.models import PriceRequest, WebOutbox

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy import Engine

    from va_contracts import Envelope

    from .schedule import Schedule

    type Publish = Callable[[Envelope[Any]], None]

log = logging.getLogger(__name__)

SOURCE = "va/web-api"


def _utcnow() -> datetime:
    return datetime.now(UTC)


class PriceScheduler:
    """``engine`` schreibt mit der Rolle ``va_web``. ``publisher`` liefert die Sende-Funktion des
    Busses, solange keiner da ist ``None``; dann bleibt das Event in der Outbox."""

    def __init__(
        self,
        engine: Engine,
        schedule: Schedule | None,
        *,
        clock: Callable[[], datetime] = _utcnow,
        publisher: Callable[[], Publish | None] = lambda: None,
    ) -> None:
        self._engine = engine
        self._schedule = schedule
        self._clock = clock
        self._publisher = publisher
        self._outbox = Outbox(WebOutbox)

    def tick(self) -> datetime | None:
        """Stoesst einen faelligen Termin an; gibt ihn zurueck, sonst ``None``."""
        if self._schedule is None:
            return None
        now = self._clock()
        slot = self._schedule.due(now)
        requested = None if slot is None else self._request(slot, now)
        self._flush()
        return requested

    def _request(self, slot: datetime, now: datetime) -> datetime | None:
        assert self._schedule is not None
        trade_date = slot.astimezone(ZoneInfo(self._schedule.timezone)).date()
        with session_scope(self._engine) as session:
            created = session.execute(
                insert(PriceRequest)
                .values(slot=slot, trade_date=trade_date, requested_at=now)
                .on_conflict_do_nothing(index_elements=["slot"])
                .returning(PriceRequest.slot)
            ).scalar()
            if created is None:
                return None
            data = PricesRequestedV1(slot=slot, trade_date=trade_date)
            self._outbox.add(session, new_envelope(PRICES_REQUESTED, data, source=SOURCE))
        log.info("Tageskurse fuer %s angefordert (Termin %s)", trade_date, slot.isoformat())
        return slot

    def _flush(self) -> None:
        publish = self._publisher()
        if publish is None:
            return
        try:
            drain_outbox(
                self._engine,
                self._outbox,
                lambda message: publish(parse_envelope(message.payload)),
            )
        except Exception:
            log.warning("Outbox nicht geleert, der naechste Takt versucht es erneut", exc_info=True)
