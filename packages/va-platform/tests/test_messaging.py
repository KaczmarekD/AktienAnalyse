"""Outbox und Inbox ohne Datenbank (P4.2): was zum Katalog und zu den Consumern passen muss.

Das Verhalten gegen Postgres pruefen ``tests/db/test_outbox_inbox.py`` und, fuer den Publisher,
``test_nats_provision.py``.
"""

from __future__ import annotations

from typing import Any

import pytest

from va_contracts import new_envelope
from va_contracts.events.v1 import EVENTS, FETCH_PROGRESSED, FetchProgressedV1
from va_platform.nats import CONSUMERS


def test_consumer_filters_are_subjects_of_durable_events():
    """Die Outbox sendet unter ``EventSpec.subject``. Ein Tippfehler im Filter eines Consumers
    liesse ihn still leer laufen."""
    durable = {spec.subject for spec in EVENTS.values() if not spec.volatile}
    filters = {subject for spec in CONSUMERS for subject in spec.subjects if subject != "va.>"}
    assert filters
    assert filters <= durable


class _NoSession:
    def execute(self, *_args: Any, **_kwargs: Any) -> None:
        pytest.fail("ein fluechtiges Event darf nichts schreiben")


def test_outbox_refuses_volatile_events_before_writing():
    from va_platform.messaging import Outbox, OutboxMixin, VolatileEventError

    data = FetchProgressedV1(run_id=1, done=1, total=90, symbol="SAP.DE", ok=True)
    envelope = new_envelope(FETCH_PROGRESSED, data, source="va/test")
    with pytest.raises(VolatileEventError, match=r"live\.va\.marketdata\.fetch\.progressed"):
        Outbox(OutboxMixin).add(_NoSession(), envelope)  # type: ignore[arg-type]
