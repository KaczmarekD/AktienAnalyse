"""Dienste-Prozess: market-data, scoring und notification dauerhaft an NATS (P4.7).

``python -m src.worker`` haengt die Handler wie der Batch an den ``NatsBus`` (``wire``, je
Service ein ``ReliableBus``) und laeuft, bis SIGTERM kommt. Er fuehrt die Runs aus, die das
web-api anlegt (Start aus dem UI, Scheduler). Er legt selbst keine Runs an und schliesst keine
ab, das macht die Run-Verwaltung im web-api aus den Events. Scheitert ein Handler endgueltig,
meldet der Worker ``screening.run.failed`` (``src.dead_letters``).

In P5.1 wird daraus ein Image je Service. Exit-Codes: 0 nach SIGTERM, 2 Konfiguration.
"""

from __future__ import annotations

import logging
import signal
import sys
import threading
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from va_platform.nats import MAX_DELIVER, NatsBus

from . import __version__
from .composition import build_adapters, wire
from .config import load_settings
from .dead_letters import run_failure
from .logging_setup import setup_logging

if TYPE_CHECKING:
    from va_platform.bus import DeadLetter

    from .composition import Adapters
    from .config import Settings

SOURCE = "va/worker"
EXIT_CONFIG = 2

log = logging.getLogger("worker")


def serve(settings: Settings, stop: threading.Event, *, adapters: Adapters | None = None) -> None:
    """Haengt die Handler an NATS und kehrt erst zurueck, wenn ``stop`` gesetzt ist."""
    if not settings.nats_url:
        msg = "Der Worker braucht NATS_URL"
        raise ValueError(msg)
    adapters = adapters or build_adapters(settings)

    def dead_letter(dead: DeadLetter) -> None:
        failure = run_failure(dead, source=SOURCE)
        log.error(
            "%s: %s (%s) nach %s Versuchen aufgegeben: %r",
            dead.consumer,
            dead.envelope.type,
            dead.envelope.id,
            dead.attempts,
            dead.error,
        )
        if failure is None:
            return
        try:
            bus.publish(failure)
        except Exception:
            log.exception("Fehlschlag von Run %s nicht gemeldet", failure.data.run_id)

    bus = NatsBus(settings.nats_url, max_deliver=MAX_DELIVER, on_dead_letter=dead_letter)
    bus.start()
    try:
        wire(bus, adapters, settings, version=__version__)
        log.info("=== value-analyzer v%s Worker laeuft ===", __version__)
        stop.wait()
        log.info("Worker wird beendet")
    finally:
        bus.close()


def main() -> int:
    try:
        settings = load_settings()
    except ValidationError as e:
        # Logging ist hier noch nicht initialisiert - direkt auf stderr
        sys.stderr.write(f"Konfigurationsfehler:\n{e}\n")
        return EXIT_CONFIG
    if not settings.nats_url:
        sys.stderr.write("Konfigurationsfehler: Der Worker braucht NATS_URL\n")
        return EXIT_CONFIG

    setup_logging(settings.logs_dir)
    stop = threading.Event()

    def on_signal(signum: int, frame: Any) -> None:  # noqa: ARG001 - Signatur von signal
        stop.set()

    previous = {sig: signal.signal(sig, on_signal) for sig in (signal.SIGTERM, signal.SIGINT)}
    try:
        serve(settings, stop)
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)
    return 0


if __name__ == "__main__":
    sys.exit(main())
