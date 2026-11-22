"""portfolio als eigener Service (D3.1): ``python -m va_portfolio``.

Beantwortet die Depots per Request/Reply (``rpc.va.portfolio.*``, Queue-Gruppe ``portfolio``).
Jede Aenderung legt ``portfolio.depot.changed`` in die Outbox; nach jeder Aenderung und im Takt
``OUTBOX_INTERVAL`` leert der Dienst sie (falls NATS kurz weg war). Events liest er in D3.1 noch
keine; einen Consumer bekommt er mit den Kopien der Stammdaten und Kurse (D3.4).

Seit D3.3 meldet er market-data die Abdeckung (``portfolio.coverage.changed``): bei jeder
Aenderung der Menge, beim Start und alle ``COVERAGE_INTERVAL`` auch unveraendert.
"""

from __future__ import annotations

import logging
import threading
import time
from functools import partial
from typing import TYPE_CHECKING

from va_contracts import parse_envelope
from va_platform.messaging import Outbox, drain_outbox
from va_platform.service import service_main

from ..adapters.postgres.models import PortfolioOutbox
from ..adapters.postgres.store import PostgresDepotStore
from ..application.depots import DepotService
from . import rpc
from .settings import PortfolioSettings

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy import Engine

    from va_platform.nats import NatsBus

log = logging.getLogger(__name__)

QUEUE = "portfolio"  # Queue-Gruppe fuer Request/Reply
OUTBOX_INTERVAL = 30.0  # Sekunden; nur fuer Liegengebliebenes, sonst gleich nach der Aenderung
COVERAGE_INTERVAL = 24 * 3600.0  # D3.3: die ganze Abdeckung einmal am Tag


def outbox_flusher(bus: NatsBus, engine: Engine) -> Callable[[], int]:
    """Gibt die offenen Events der Outbox an den Bus; die Anzahl zurueck."""
    outbox = Outbox(PortfolioOutbox)
    lock = threading.Lock()  # RPC-Threads und Takt nicht gleichzeitig

    def flush() -> int:
        with lock:
            return drain_outbox(
                engine, outbox, lambda message: bus.publish(parse_envelope(message.payload))
            )

    return flush


def _keep_flushing(
    flush: Callable[[], int],
    interval: float,
    closing: Callable[[], bool],
    *,
    announce: Callable[[], object] | None = None,
    announce_every: float = COVERAGE_INTERVAL,
    timer: Callable[[], float] = time.monotonic,
) -> None:
    """Der Takt, bis der Bus schliesst; nur der erste Fehler einer Serie mit Traceback.

    ``announce`` (D3.3): alle ``announce_every`` Sekunden die ganze Abdeckung.
    """
    failures = 0
    pause = threading.Event()
    announced = timer()
    while not pause.wait(interval):
        if closing():
            return
        if announce is not None and timer() - announced >= announce_every:
            announced = timer()
            try:
                announce()
            except Exception:
                log.warning(
                    "Abdeckung nicht gemeldet - der naechste Takt holt es nach", exc_info=True
                )
        try:
            flush()
        except Exception:
            failures += 1
            log.warning(
                "Outbox von portfolio nicht geleert (%d. Mal)", failures, exc_info=failures == 1
            )
        else:
            failures = 0


def setup(
    bus: NatsBus,
    engine: Engine,
    *,
    settings: PortfolioSettings,
    interval: float = OUTBOX_INTERVAL,
) -> None:
    """``settings``: heute nur fuer die Verbindungen, die ``run_service`` schon gebaut hat."""
    del settings
    flush = outbox_flusher(bus, engine)
    service = DepotService(PostgresDepotStore(engine), flush=flush)
    for spec, handler in rpc.handlers(service).items():
        bus.serve(spec, handler, queue=QUEUE)
    try:
        service.announce_coverage()  # D3.3: legt das Event an und leert dabei die Outbox
    except Exception:
        log.warning("Abdeckung beim Start nicht gemeldet", exc_info=True)
    try:
        flush()  # was vor einem Neustart liegen blieb
    except Exception:
        log.warning("Outbox von portfolio beim Start nicht geleert", exc_info=True)
    threading.Thread(
        target=_keep_flushing,
        args=(flush, interval, lambda: bus.closing),
        kwargs={"announce": service.announce_coverage},
        name="portfolio-outbox",
        daemon=True,
    ).start()


def main() -> int:
    return service_main(
        "portfolio",
        PortfolioSettings,  # type: ignore[arg-type] - Pflichtfelder kommen aus der Umgebung
        lambda settings: partial(setup, settings=settings),  # type: ignore[arg-type]
    )
