"""Scheduler des web-api (P4.7): welcher Cron-Termin gerade faellig ist.

Der Ausdruck gilt in der Zeitzone des Schedules (Standard ``Europe/Berlin``), unabhaengig von der
Zeitzone des Containers. Faellig ist der juengste Termin, solange er hoechstens ``GRACE``
zurueckliegt. Wie oft der Takt fragt, spielt keine Rolle: Den Run je Termin legt die Datenbank
nur einmal an (``tests/db/web_api/test_runs.py``).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from pydantic import SecretStr, ValidationError

from va_web_api.runs.schedule import GRACE, Schedule
from va_web_api.settings import WebApiSettings

BERLIN = ZoneInfo("Europe/Berlin")
SATURDAY = "30 7 * * 6"


def _berlin(*args: int) -> datetime:
    return datetime(*args, tzinfo=BERLIN)


class TestDue:
    def test_the_slot_itself_is_due(self):
        schedule = Schedule(SATURDAY, "Europe/Berlin")
        slot = schedule.due(_berlin(2026, 11, 7, 7, 30))
        assert slot == _berlin(2026, 11, 7, 7, 30)

    def test_shortly_after_the_slot_it_is_still_due(self):
        schedule = Schedule(SATURDAY, "Europe/Berlin")
        assert schedule.due(_berlin(2026, 11, 7, 7, 59, 30)) == _berlin(2026, 11, 7, 7, 30)

    def test_before_the_slot_nothing_is_due(self):
        schedule = Schedule(SATURDAY, "Europe/Berlin")
        assert schedule.due(_berlin(2026, 11, 7, 7, 29, 59)) is None

    def test_after_the_grace_period_nothing_is_due(self):
        schedule = Schedule(SATURDAY, "Europe/Berlin")
        slot = _berlin(2026, 11, 7, 7, 30)
        assert schedule.due(slot + GRACE) == slot
        assert schedule.due(slot + GRACE + timedelta(minutes=1)) is None

    def test_the_slot_is_returned_in_utc(self):
        schedule = Schedule(SATURDAY, "Europe/Berlin")
        slot = schedule.due(datetime(2026, 11, 7, 6, 31, tzinfo=UTC))
        assert slot == datetime(2026, 11, 7, 6, 30, tzinfo=UTC)
        assert slot is not None
        assert slot.utcoffset() == timedelta(0)

    def test_the_timezone_is_the_schedules_not_the_callers(self):
        """07:30 in Berlin ist im Sommer 05:30 UTC, im Winter 06:30 UTC."""
        schedule = Schedule(SATURDAY, "Europe/Berlin")
        summer = schedule.due(datetime(2026, 7, 4, 5, 31, tzinfo=UTC))
        winter = schedule.due(datetime(2026, 11, 7, 6, 31, tzinfo=UTC))
        assert summer == datetime(2026, 7, 4, 5, 30, tzinfo=UTC)
        assert winter == datetime(2026, 11, 7, 6, 30, tzinfo=UTC)

    def test_a_skipped_hour_runs_like_cron(self):
        """Am 29.03.2026 gibt es 02:30 nicht, cron laeuft dann um 03:00 Sommerzeit."""
        schedule = Schedule("30 2 * * *", "Europe/Berlin")
        assert schedule.due(_berlin(2026, 3, 29, 3, 5)) == _berlin(2026, 3, 29, 3, 0)

    def test_a_naive_time_is_rejected(self):
        schedule = Schedule(SATURDAY, "Europe/Berlin")
        with pytest.raises(ValueError, match="Zeitzone"):
            schedule.due(datetime(2026, 11, 7, 7, 30))  # ohne Zeitzone: genau das ist der Fall


class TestValidation:
    def test_an_invalid_expression_fails(self):
        with pytest.raises(ValueError, match="Cron"):
            Schedule("61 7 * * 6", "Europe/Berlin")

    def test_an_unknown_timezone_fails(self):
        with pytest.raises(ValueError, match="Zeitzone"):
            Schedule(SATURDAY, "Europe/Nirgendwo")


class TestSettings:
    NO_DB = SecretStr("postgresql+psycopg://x:x@127.0.0.1:1/none")

    def test_off_by_default_in_berlin(self):
        settings = WebApiSettings(database_url=self.NO_DB)
        assert settings.schedule == ""
        assert settings.schedule_timezone == "Europe/Berlin"
        assert settings.run_schedule is None

    def test_a_schedule_is_parsed_once(self):
        settings = WebApiSettings(database_url=self.NO_DB, schedule=SATURDAY)
        assert settings.run_schedule is not None
        assert settings.run_schedule.due(_berlin(2026, 11, 7, 7, 30)) == _berlin(2026, 11, 7, 7, 30)

    def test_an_invalid_schedule_stops_the_start(self):
        with pytest.raises(ValidationError, match="Cron"):
            WebApiSettings(database_url=self.NO_DB, schedule="jeden Samstag")

    def test_an_invalid_timezone_stops_the_start(self):
        with pytest.raises(ValidationError, match="Zeitzone"):
            WebApiSettings(database_url=self.NO_DB, schedule=SATURDAY, schedule_timezone="Mars")

    def test_watchdog_limits_have_defaults(self):
        settings = WebApiSettings(database_url=self.NO_DB)
        limits = settings.watchdog_limits
        assert limits.fetch == timedelta(minutes=45)
        assert limits.scoring == timedelta(minutes=5)
        assert limits.report == timedelta(minutes=5)

    def test_watchdog_limits_must_be_positive(self):
        with pytest.raises(ValidationError):
            WebApiSettings(database_url=self.NO_DB, watchdog_fetch_minutes=0)
