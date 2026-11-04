"""Dienste-Prozess: market-data, scoring und notification dauerhaft an NATS (P4.7).

``python -m src.worker`` haengt die Handler wie der Batch an den ``NatsBus`` (``wire``, je
Service ein ``ReliableBus``) und laeuft, bis SIGTERM kommt. Er fuehrt die Runs aus, die das
web-api anlegt (Start aus dem UI, Scheduler). Er legt selbst keine Runs an und schliesst keine
ab, das macht die Run-Verwaltung im web-api aus den Events. Scheitert ein Handler endgueltig,
meldet der Worker ``screening.run.failed`` (``va_platform.service.run_failure``).

Seit P4.8 beantwortet er ausserdem Request/Reply des web-api: Vorschau, Profile und Reports.
Seit P5.1a mit dem Code der Services (``va_scoring.entrypoints.rpc``,
``va_notification.entrypoints.rpc``); die drei Services koennen auch einzeln laufen
(``python -m va_market_data`` usw.). Den Laufrahmen gibt ``va_platform.service.run_service``.

In P5.1 wird daraus ein Image je Service. Exit-Codes: 0 nach SIGTERM, 2 Konfiguration.
"""

from __future__ import annotations

import logging
import signal
import sys
import threading
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from va_notification.entrypoints import service as notification_service
from va_platform.service import run_service
from va_scoring.entrypoints import service as scoring_service

from . import __version__
from .composition import build_adapters, wire
from .config import load_settings
from .logging_setup import setup_logging

if TYPE_CHECKING:
    from sqlalchemy import Engine

    from va_platform.nats import NatsBus

    from .composition import Adapters
    from .config import Settings

EXIT_CONFIG = 2

log = logging.getLogger("worker")


def serve(settings: Settings, stop: threading.Event, *, adapters: Adapters | None = None) -> None:
    """Haengt alle drei Services an NATS und kehrt erst zurueck, wenn ``stop`` gesetzt ist."""
    adapters = adapters or build_adapters(settings)

    def setup(bus: NatsBus, engine: Engine) -> None:
        wire(bus, adapters, settings, version=__version__)
        # P4.8/P4.9, beim Besitzer seit P5.1a: Request/Reply fuer das web-api
        scoring_service.serve(bus, engine)
        notification_service.serve(bus, engine)

    run_service(name="worker", settings=settings, setup=setup, stop=stop)


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
