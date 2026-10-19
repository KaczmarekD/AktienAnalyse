"""Ports von notification: Versand des Reports und Lebenszeichen nach aussen."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from ..domain.report import ReportArtifacts


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


class ReportStore(Protocol):
    """Speicher von notification: erzeugte Reports und jeder Versandversuch."""

    def record_report(
        self, run_id: int | None, scoring_run_id: int | None, report: ReportArtifacts
    ) -> int: ...

    def record_delivery(
        self,
        *,
        run_id: int | None,
        report_id: int | None,
        channel: str,
        kind: str,
        recipient: str | None,
        subject: str | None,
        success: bool,
        error: str | None = None,
    ) -> None: ...
