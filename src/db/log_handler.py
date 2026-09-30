"""Puffert die Log-Zeilen eines Laufs, damit sie am Ende in ``batch.run_log`` landen.

Die Log-Dateien rotieren weiter (Diagnose-Puffer); dauerhaft gespeichert wird
in der Datenbank. Schlaegt das Schreiben fehl, bleiben die Zeilen in der Datei.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass(frozen=True)
class LogEntry:
    ts: datetime
    level: str
    logger: str
    message: str


class BufferingLogHandler(logging.Handler):
    def __init__(self, level: int = logging.INFO, max_entries: int = 20_000) -> None:
        super().__init__(level)
        self.entries: list[LogEntry] = []
        self._max_entries = max_entries
        self._overflowed = False
        self.setFormatter(logging.Formatter("%(message)s"))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            if len(self.entries) >= self._max_entries:
                if not self._overflowed:
                    self._overflowed = True
                    self.entries.append(
                        LogEntry(
                            datetime.now(UTC),
                            "WARNING",
                            __name__,
                            "Log-Puffer voll - weitere Zeilen nur in der Log-Datei",
                        )
                    )
                return
            self.entries.append(
                LogEntry(
                    datetime.fromtimestamp(record.created, UTC),
                    record.levelname,
                    record.name,
                    self.format(record),
                )
            )
        except Exception:
            self.handleError(record)
