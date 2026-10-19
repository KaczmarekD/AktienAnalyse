"""Ports von notification: Versand des Reports und Lebenszeichen nach aussen."""

from __future__ import annotations

from typing import Protocol


class ReportSender(Protocol):
    """Verschickt den Report. ``attachment`` = (Dateiname, Inhalt)."""

    def send(
        self, subject: str, html_body: str, attachment: tuple[str, bytes] | None = None
    ) -> None: ...


class Heartbeat(Protocol):
    """Meldet Erfolg oder Fehlschlag eines Laufs. None = nicht konfiguriert.

    Wirft nie: Ein Lebenszeichen darf den Lauf nicht abbrechen.
    """

    def ping(self, success: bool, message: str | None = None) -> bool | None: ...
