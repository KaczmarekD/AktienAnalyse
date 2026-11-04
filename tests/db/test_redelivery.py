"""Erneute und veraltete Zustellungen im ganzen Batch (P4.3b), mit echter Datenbank.

Ueber NATS kann dasselbe Event noch einmal kommen (verlorenes Ack) oder ein altes Event aus
einem abgebrochenen Lauf liegen bleiben. Die Kette darf dadurch nichts doppelt tun. Der Bus ist
hier der im Prozess: Er stellt dasselbe Event zu, wenn man es zweimal veroeffentlicht.
Yahoo ist gepatcht wie in ``test_pipeline_db.py``.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import Mock, patch

from sqlalchemy import Engine, text

from src.composition import Adapters, build_adapters, wire
from tests.db.test_pipeline_db import (
    TICKERS,
    UNIVERSE,
    _fake_consensus,
    _fake_prices,
    _fake_quarterly,
    _fake_shares,
    _fake_ticker_data,
)
from va_contracts import Envelope, new_envelope
from va_contracts.events.v1 import (
    REPORT_SENT,
    RUN_FAILED,
    RUN_REQUESTED,
    RunOptionsV1,
    ScreeningRunRequestedV1,
)
from va_platform.bus import InProcessBus


@contextmanager
def _yahoo() -> Iterator[Mock]:
    with (
        patch(
            "va_market_data.adapters.yahoo._ticker_data", side_effect=_fake_ticker_data
        ) as ticker_data,
        patch("va_market_data.adapters.yahoo.fetch_consensus", side_effect=_fake_consensus),
        patch("va_market_data.adapters.yahoo.fetch_quarterly", side_effect=_fake_quarterly),
        patch("va_market_data.adapters.yahoo.fetch_share_counts", side_effect=_fake_shares),
        patch("va_market_data.adapters.yahoo.fetch_prices", side_effect=_fake_prices),
        patch("va_market_data.application.fetch.time.sleep"),
    ):
        yield ticker_data


def _wired(settings) -> tuple[InProcessBus, Adapters, list[Envelope[Any]]]:
    adapters = replace(
        build_adapters(settings),
        load_universe=lambda: UNIVERSE,
        sender=Mock(),
        heartbeat=Mock(ping=Mock(return_value=None)),
    )
    bus = InProcessBus(max_deliver=1)
    wire(bus, adapters, settings, version="test")
    ends: list[Envelope[Any]] = []
    bus.subscribe(REPORT_SENT, "probe-sent", ends.append)
    bus.subscribe(RUN_FAILED, "probe-failed", ends.append)
    return bus, adapters, ends


def _requested(*, age: timedelta | None = None) -> Envelope[Any]:
    data = ScreeningRunRequestedV1(run_id=1, trigger="manual", options=RunOptionsV1())
    envelope = new_envelope(RUN_REQUESTED, data, source="va/test", correlationid="1")
    if age is None:
        return envelope
    return envelope.model_copy(update={"time": datetime.now(UTC) - age})


def _count(engine: Engine, table: str) -> int:
    with engine.connect() as conn:
        return conn.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()


def test_same_request_twice_fetches_scores_and_mails_once(db_settings, engine):
    bus, adapters, ends = _wired(db_settings)
    request = _requested()
    with _yahoo() as ticker_data:
        bus.publish(request)
        bus.publish(request)

    assert ticker_data.call_count == len(TICKERS)  # ein Abruf
    assert _count(engine, "market_data.fetch_run") == 1
    assert _count(engine, "scoring.scoring_run") == 1
    assert adapters.sender.send.call_count == 1  # type: ignore[attr-defined]
    assert [e.type for e in ends] == [REPORT_SENT.type]
    # Jede Stufe hat das Event einmal verarbeitet und ihr Folge-Event ueber die Outbox geschickt
    for schema in ("market_data", "scoring", "reporting"):
        assert _count(engine, f"{schema}.inbox") == 1, schema
        assert _count(engine, f"{schema}.outbox WHERE published_at IS NOT NULL") == 1, schema


def test_stale_request_starts_no_fetch(db_settings, engine):
    """Aelter als RUN_TIMEOUT_MINUTES: ein Rest aus einem abgebrochenen Lauf."""
    bus, adapters, ends = _wired(db_settings)
    age = timedelta(minutes=db_settings.run_timeout_minutes + 1)
    with _yahoo() as ticker_data:
        bus.publish(_requested(age=age))
    ticker_data.assert_not_called()
    assert _count(engine, "market_data.fetch_run") == 0
    assert ends == []
    adapters.sender.send.assert_not_called()  # type: ignore[attr-defined]
