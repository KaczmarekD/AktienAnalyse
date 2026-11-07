"""Scheduler der Tageskurse im web-api (D2.3, wertpapiere.md#abdeckung-und-abrufe).

An Handelstagen um 22:30 ``Europe/Berlin`` (nach Xetra-Schluss) schickt das web-api
``marketdata.prices.requested`` ueber seine Outbox. ``web.price_request`` haelt fest, welcher
Termin schon angestossen ist: je Termin genau einmal, auch nach einem Neustart.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import Engine, text

from va_contracts import Envelope, parse_envelope
from va_contracts.events.v1 import PRICES_REQUESTED
from va_web_api.runs import PriceScheduler, Schedule

FRIDAY_2230_BERLIN = datetime(2026, 11, 6, 21, 30, tzinfo=UTC)  # Winterzeit: UTC+1
SCHEDULE = Schedule("30 22 * * 1-5", "Europe/Berlin")


class Clock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


def _outbox(engine: Engine) -> list[Envelope[Any]]:
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT payload::text FROM web.outbox ORDER BY created_at, id"))
        return [parse_envelope(row[0].encode()) for row in rows]


@pytest.fixture
def clock() -> Clock:
    return Clock(FRIDAY_2230_BERLIN + timedelta(minutes=1))


@pytest.fixture
def scheduler(web_engine: Engine, clock: Clock) -> PriceScheduler:
    return PriceScheduler(web_engine, SCHEDULE, clock=clock)


def test_a_due_trading_day_requests_prices_once(scheduler, engine, clock):
    assert scheduler.tick() == FRIDAY_2230_BERLIN
    [event] = _outbox(engine)
    assert event.type == PRICES_REQUESTED.type
    assert event.data.trade_date == date(2026, 11, 6)
    assert event.data.slot == FRIDAY_2230_BERLIN
    clock.now += timedelta(minutes=5)
    assert scheduler.tick() is None  # derselbe Termin
    assert len(_outbox(engine)) == 1


def test_a_restart_does_not_request_again(web_engine, engine, clock):
    PriceScheduler(web_engine, SCHEDULE, clock=clock).tick()
    assert PriceScheduler(web_engine, SCHEDULE, clock=clock).tick() is None
    assert len(_outbox(engine)) == 1


def test_no_prices_on_saturday(web_engine, engine):
    saturday = Clock(datetime(2026, 11, 7, 21, 31, tzinfo=UTC))
    assert PriceScheduler(web_engine, SCHEDULE, clock=saturday).tick() is None
    assert _outbox(engine) == []


def test_without_schedule_nothing_happens(web_engine, engine, clock):
    assert PriceScheduler(web_engine, None, clock=clock).tick() is None
    assert _outbox(engine) == []


def test_the_events_go_out_through_the_publisher(web_engine, clock):
    sent: list[Envelope[Any]] = []
    PriceScheduler(web_engine, SCHEDULE, clock=clock, publisher=lambda: sent.append).tick()
    assert [e.type for e in sent] == [PRICES_REQUESTED.type]
