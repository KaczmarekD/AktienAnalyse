"""Gemeinsames der Services (P5.1a): Settings-Basis, Laufrahmen, Request/Reply im Prozess.

- ``ServiceSettings``: was jeder Service braucht (Datenbank, NATS, Zeitlimit, Logs). Die Settings
  der Services erben davon, der Batch erbt die der Services.
- ``run_service``: Bus starten, den Service verdrahten (``setup(bus, engine)``) und bis zum
  Stopp-Event laufen. Ein Dead Letter wird zu ``screening.run.failed`` (``run_failure``).
- ``service_main``: der Einstieg von ``python -m va_<service>``, mit SIGTERM und Exit-Codes.
- ``LocalCaller``: beantwortet Request/Reply ohne NATS mit denselben Handlern wie ``serve``.
"""

from __future__ import annotations

import logging
import signal
import sys
import threading
import traceback
from pathlib import Path
from typing import TYPE_CHECKING, Any, get_args

from pydantic import Field, SecretStr, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

from va_contracts.events.v1 import RUN_FAILED, RunFailedV1, Stage

from . import tracing
from .bus import follow_up
from .db import create_db_engine
from .nats import MAX_DELIVER, NatsBus, RpcUnavailable, answer_request
from .redaction import install_redaction

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from sqlalchemy import Engine

    from va_contracts import Contract, Envelope
    from va_contracts.rpc.v1 import RpcReplyV1, RpcSpec

    from .bus import DeadLetter

log = logging.getLogger(__name__)

EXIT_OK = 0
EXIT_CONFIG = 2


class ServiceSettings(BaseSettings):
    """Felder aller Services; jeder Service ergaenzt seine eigenen (``entrypoints/settings.py``)."""

    # env_ignore_empty: Compose reicht nicht gesetzte Variablen als leeren Text durch
    # (${MAIL_FROM:-}); leer heisst dann "nicht gesetzt", es gilt der Standardwert (P5.1)
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        env_ignore_empty=True,
    )

    # postgresql+psycopg://va_app:<pw>@db:5432/value_analyzer
    database_url: SecretStr = Field(min_length=1)
    # nats://nats:4222 - Pflicht fuer einen Service, der Batch im Prozess braucht ihn nicht
    nats_url: str | None = None
    # Aeltere Events sind Reste abgebrochener Laeufe (P4.3b); so lange wartet auch der Batch
    run_timeout_minutes: float = Field(default=120, gt=0)
    logs_dir: Path = Path("/app/logs")
    # P5.5: "console" schreibt die Spans eines Runs ins Log (Name wie bei OpenTelemetry)
    otel_traces_exporter: tracing.Exporter = "none"


def stage_of(consumer: str) -> Stage:
    """Stufe fuer screening.run.failed; was keinem Modul gehoert, meldet der Watchdog."""
    return consumer if consumer in get_args(Stage) else "watchdog"  # type: ignore[return-value]


def run_failure(dead: DeadLetter, *, source: str) -> Envelope[RunFailedV1] | None:
    """Aus einem Dead Letter wird ``screening.run.failed`` fuer den Run des Events (P1.8).

    Ein Handler ist trotz Wiederholung gescheitert, das ist ein Bug. Der Run endet dann wie jeder
    Fehlschlag. Ein gescheitertes Fehler-Event loest keines mehr aus, ein Event ohne Run auch nicht.
    """
    if dead.envelope.type == RUN_FAILED.type:
        return None
    data: Any = dead.envelope.data
    if not all(hasattr(data, field) for field in ("run_id", "trigger", "options")):
        return None
    failure = RunFailedV1(
        run_id=data.run_id,
        trigger=data.trigger,
        options=data.options,
        stage=stage_of(dead.consumer),
        reason=f"{dead.consumer}: {dead.error}",
        detail="".join(traceback.format_exception(dead.error)),
    )
    return follow_up(dead.envelope, RUN_FAILED, failure, source=source)


def run_service(
    *,
    name: str,
    settings: ServiceSettings,
    setup: Callable[[NatsBus, Engine], None],
    stop: threading.Event,
    max_deliver: int = MAX_DELIVER,
    all_consumers: bool = False,
) -> None:
    """Startet den Bus, ruft ``setup`` und kehrt erst zurueck, wenn ``stop`` gesetzt ist.

    Der Bus legt nur den Consumer ``name`` an (D1.5); ``all_consumers`` fuer ``src.worker``, der
    alle drei Services in einem Prozess startet (NATS-Nutzer ``batch``).
    """
    if not settings.nats_url:
        msg = f"{name} braucht NATS_URL"
        raise ValueError(msg)
    source = f"va/{name}"
    engine = create_db_engine(settings.database_url.get_secret_value())

    def dead_letter(dead: DeadLetter) -> None:
        failure = run_failure(dead, source=source)
        if failure is None:
            return
        try:
            bus.publish(failure)
        except Exception:
            log.exception("Fehlschlag von Run %s nicht gemeldet", failure.data.run_id)

    # D1.5: Mit einem NATS-Nutzer je Dienst legt der Service nur seinen eigenen Consumer an
    bus = NatsBus(
        settings.nats_url,
        max_deliver=max_deliver,
        on_dead_letter=dead_letter,
        consumers=None if all_consumers else (name,),
    )
    bus.start()
    try:
        setup(bus, engine)
        log.info("Service %s laeuft", name)
        stop.wait()
        log.info("Service %s wird beendet", name)
    finally:
        bus.close()
        engine.dispose()


def service_main(
    name: str,
    load: Callable[[], ServiceSettings],
    setup: Callable[[ServiceSettings], Callable[[NatsBus, Engine], None]],
) -> int:
    """``python -m va_<service>``: Settings laden, bis SIGTERM laufen. Exit 2 bei Konfiguration."""
    try:
        settings = load()
    except ValidationError as e:
        sys.stderr.write(f"Konfigurationsfehler:\n{e}\n")
        return EXIT_CONFIG
    if not settings.nats_url:
        sys.stderr.write(f"Konfigurationsfehler: {name} braucht NATS_URL\n")
        return EXIT_CONFIG
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s | %(levelname)-7s | %(name)-22s | %(message)s"
    )
    install_redaction()  # D1.2: keine Geheimnisse und Mail-Adressen im Log
    tracing.configure(f"va-{name}", settings.otel_traces_exporter)
    stop = threading.Event()

    def on_signal(signum: int, frame: Any) -> None:  # noqa: ARG001 - Signatur von signal
        stop.set()

    previous = {sig: signal.signal(sig, on_signal) for sig in (signal.SIGTERM, signal.SIGINT)}
    try:
        run_service(name=name, settings=settings, setup=setup(settings), stop=stop)
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)
    return EXIT_OK


class LocalCaller:
    """Request/Reply im selben Prozess (``va_web_api.rpc.RpcCaller``), wie ueber NATS."""

    def __init__(self, handlers: Mapping[RpcSpec[Any, Any], Callable[[Any], Any]]) -> None:
        self._handlers = dict(handlers)

    def call[Q: Contract, R: RpcReplyV1](self, spec: RpcSpec[Q, R], request: Q) -> R:
        handler = self._handlers.get(spec)
        if handler is None:
            raise RpcUnavailable(spec.name)
        return answer_request(spec, handler, request)
