"""Einstieg des Batches: Lauf anlegen, Event-Kette starten, Lauf abschliessen (P1.8).

Die Arbeit machen die Handler der Module am Bus (``src/composition.py``):
market-data -> scoring -> notification. Dieses Modul verdrahtet nur, startet die Kette mit
``screening.run.requested`` und schreibt am Ende das Ergebnis des ``RunTracker`` in
``batch.run``. Ist die Datenbank nicht erreichbar, bricht der Lauf ab (Exit 4): ohne
Speicherung kein Report, ein manueller Nachlauf reicht.

Exit-Codes: 0 ok, 1 Fehler im Lauf, 2 Konfiguration, 3 keine bewertbaren
Daten, 4 Datenbank nicht erreichbar.
"""

from __future__ import annotations

import argparse
import logging
import sys
import traceback
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, get_args

from pydantic import ValidationError

from va_contracts import new_envelope
from va_contracts.events.v1 import (
    RUN_FAILED,
    RUN_REQUESTED,
    RunFailedV1,
    RunOptionsV1,
    ScreeningRunRequestedV1,
    Stage,
)
from va_notification.entrypoints.handlers import notify_failure_without_run
from va_platform.bus import InProcessBus, follow_up

from . import __version__
from .composition import alert_channels, build_adapters, wire
from .config import Settings, load_settings
from .db.log_handler import BufferingLogHandler
from .logging_setup import setup_logging
from .run_tracker import EXIT_FAILED, EXIT_NO_DATA, EXIT_OK, RunOutcome, RunTracker

if TYPE_CHECKING:
    from va_platform.bus import DeadLetter

    from .composition import Adapters

__all__ = ["EXIT_FAILED", "EXIT_NO_DATA", "EXIT_OK", "main", "run"]

EXIT_CONFIG = 2
EXIT_DB_UNAVAILABLE = 4

SOURCE = "va/batch"
# Im Prozess keine Wiederholung: Die Handler fangen ihre Fehler selbst und melden
# screening.run.failed. Was trotzdem durchschlaegt, ist ein Bug - den Abruf deshalb
# nochmal zu starten, kostete nur Minuten und erzeugte einen zweiten fetch_run.
MAX_DELIVER = 1

# Nie in die Datenbank: Passwoerter, Verbindungs-URLs, Healthcheck-UUID
_SECRET_SETTINGS = {"smtp_password", "database_url", "database_owner_url", "healthcheck_url"}

log = logging.getLogger("main")


def _settings_snapshot(settings: Settings) -> dict[str, Any]:
    return settings.model_dump(mode="json", exclude=_SECRET_SETTINGS)


@contextmanager
def _capture_logs() -> Iterator[BufferingLogHandler]:
    """Sammelt die Log-Zeilen des Laufs fuer ``batch.run_log``."""
    root = logging.getLogger()
    handler = BufferingLogHandler()
    previous_level = root.level
    if root.level > logging.INFO:
        root.setLevel(logging.INFO)
    root.addHandler(handler)
    try:
        yield handler
    finally:
        root.removeHandler(handler)
        root.setLevel(previous_level)


def _safely(what: str, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
    """Protokoll-Schreibzugriffe, die den Lauf nicht mehr kippen duerfen."""
    try:
        fn(*args, **kwargs)
    except Exception:
        log.warning("%s konnte nicht gespeichert werden", what, exc_info=True)


def _run(
    settings: Settings,
    *,
    force_refresh: bool,
    dry_run: bool,
    adapters: Adapters | None = None,
) -> int:
    with _capture_logs() as captured:
        log.info("=== value-analyzer v%s START ===", __version__)
        try:
            adapters = adapters or build_adapters(settings)
            run_id = adapters.batch.start_run(
                kind="batch",
                dry_run=dry_run,
                force_refresh=force_refresh,
                universe_mode=settings.universe,
                settings=_settings_snapshot(settings),
            )
        except Exception:
            log.exception("Datenbank nicht erreichbar - Lauf abgebrochen")
            sender, heartbeat = (
                (adapters.sender, adapters.heartbeat) if adapters else alert_channels(settings)
            )
            notify_failure_without_run(
                sender,
                heartbeat,
                "database unreachable",
                detail=traceback.format_exc(),
                dry_run=dry_run,
            )
            return EXIT_DB_UNAVAILABLE

        try:
            options = RunOptionsV1(force_refresh=force_refresh, dry_run=dry_run)
            try:
                outcome = _execute(settings, adapters, run_id, options)
            except Exception:
                # Faellt etwas aus dem Bus heraus, ist es ein Bug: abschliessen und alarmieren
                log.exception("Unerwarteter Fehler im Run")
                outcome = RunOutcome(
                    status="failed", exit_code=EXIT_FAILED, error=traceback.format_exc()
                )
                _alarm(adapters, "unexpected error", outcome.error or "", dry_run=dry_run)
            _safely("Laufabschluss", adapters.batch.finish_run, run_id, **outcome.finish_kwargs())
            if outcome.exit_code == EXIT_OK:
                log.info(
                    "=== Run erfolgreich (scored %s/%s) ===",
                    outcome.scored_count,
                    outcome.universe_size,
                )
            return outcome.exit_code
        finally:
            _safely("Log-Zeilen", adapters.batch.record_logs, run_id, captured.entries)


def _execute(
    settings: Settings, adapters: Adapters, run_id: int, options: RunOptionsV1
) -> RunOutcome:
    """Startet die Kette und wartet ihr Ende ab (im Prozess: bis ``publish`` zurueckkehrt)."""
    tracker = RunTracker(run_id)

    def dead_letter(dead: DeadLetter) -> None:
        # Ein Handler ist an einem Bug gescheitert: Der Lauf endet wie jeder Fehlschlag,
        # also mit Ping und Fehlermail. Ein gescheitertes Fehler-Event loest keines mehr aus.
        tracker.on_dead_letter(dead)
        if dead.envelope.type != RUN_FAILED.type:
            failed = RunFailedV1(
                run_id=run_id,
                trigger="scheduled",
                options=options,
                stage=_stage(dead.consumer),
                reason=f"{dead.consumer}: {dead.error}",
                detail=repr(dead.error),
            )
            bus.publish(follow_up(dead.envelope, RUN_FAILED, failed, source=SOURCE))

    bus = InProcessBus(max_deliver=MAX_DELIVER, on_dead_letter=dead_letter)
    wire(bus, adapters, settings, version=__version__)
    tracker.subscribe(bus)
    bus.publish(
        new_envelope(
            RUN_REQUESTED,
            ScreeningRunRequestedV1(run_id=run_id, trigger="scheduled", options=options),
            source=SOURCE,
            correlationid=str(run_id),
        )
    )
    if tracker.outcome is None:
        log.error("Die Event-Kette endete ohne Ergebnis - Lauf gilt als gescheitert")
        _alarm(adapters, "run without outcome", "Lauf ohne Ergebnis", dry_run=options.dry_run)
        return RunOutcome(status="failed", exit_code=EXIT_FAILED, error="Lauf ohne Ergebnis")
    return tracker.outcome


def _alarm(adapters: Adapters, message: str, detail: str, *, dry_run: bool) -> None:
    """Ping /fail und Fehlermail, wenn die Kette selbst keinen Fehlschlag melden konnte."""
    try:
        notify_failure_without_run(
            adapters.sender, adapters.heartbeat, message, detail=detail, dry_run=dry_run
        )
    except Exception:
        log.exception("Alarm konnte nicht verschickt werden")


def _stage(consumer: str) -> Stage:
    """Stufe fuer screening.run.failed; was keinem Modul gehoert, meldet der Watchdog."""
    return consumer if consumer in get_args(Stage) else "watchdog"  # type: ignore[return-value]


def run(force_refresh: bool = False, dry_run: bool = False) -> int:
    try:
        settings = load_settings()
    except ValidationError as e:
        # Logging ist hier noch nicht initialisiert - direkt auf stderr
        sys.stderr.write("Konfigurationsfehler:\n")
        sys.stderr.write(str(e) + "\n")
        return EXIT_CONFIG

    setup_logging(settings.logs_dir)
    return _run(settings, force_refresh=force_refresh, dry_run=dry_run)


def main() -> int:
    parser = argparse.ArgumentParser(description="DAX/MDAX Value-Aktien Batch-Analyse")
    parser.add_argument(
        "--force-refresh",
        action="store_true",
        help="Abruf von heute in der Datenbank ignorieren und neu von yfinance laden",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Kein Mailversand; Vorschau-HTML und CSV zusaetzlich nach DATA_DIR schreiben",
    )
    args = parser.parse_args()
    return run(force_refresh=args.force_refresh, dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
