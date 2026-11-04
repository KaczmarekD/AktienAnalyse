"""Scheduler des web-api (P4.7): welcher Cron-Termin gerade faellig ist.

Der Ausdruck gilt in der Zeitzone des Schedules (Standard ``Europe/Berlin``, events.md), nicht in
der des Containers. ``cronsim`` behandelt die Sommerzeit wie cron: Einen Termin in der
uebersprungenen Stunde gibt es zur naechsten gueltigen Zeit.

Faellig ist der juengste Termin, solange er hoechstens ``GRACE`` zurueckliegt. So holt ein
Neustart kurz nach dem Termin den Run nach, ein laengerer Ausfall aber keinen alten. Dass ein
Termin nur einmal zum Run wird, sichert die Datenbank (eindeutiger ``slot``), nicht diese Klasse.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from cronsim import CronSim, CronSimError

GRACE = timedelta(hours=1)


class Schedule:
    """Ein Cron-Ausdruck in einer Zeitzone; ungueltige Werte scheitern schon hier."""

    def __init__(self, expression: str, timezone: str) -> None:
        try:
            self._zone = ZoneInfo(timezone)
        except (ZoneInfoNotFoundError, ValueError) as e:
            msg = f"Unbekannte Zeitzone {timezone!r}"
            raise ValueError(msg) from e
        try:
            CronSim(expression, datetime.now(self._zone))
        except CronSimError as e:
            msg = f"Ungueltiger Cron-Ausdruck {expression!r}: {e}"
            raise ValueError(msg) from e
        self.expression = expression
        self.timezone = timezone

    def due(self, now: datetime, grace: timedelta = GRACE) -> datetime | None:
        """Der juengste Termin bis einschliesslich ``now`` (in UTC), wenn er nicht zu alt ist."""
        if now.tzinfo is None:
            msg = "now braucht eine Zeitzone"
            raise ValueError(msg)
        # cronsim liefert rueckwaerts nur Termine vor dem Startpunkt: also ab der naechsten Minute
        local = now.astimezone(self._zone).replace(second=0, microsecond=0)
        slot = next(CronSim(self.expression, local + timedelta(minutes=1), reverse=True))
        if now - slot > grace:
            return None
        return slot.astimezone(UTC)
