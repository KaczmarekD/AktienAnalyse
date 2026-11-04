"""FastAPI-App des web-api (P3.1).

Start im Betrieb: ``uvicorn --factory src.web:create_app``. Diese Composition Root verdrahtet
die Ports fuer Vorschau und Profil-Befehle mit dem Code von scoring (P3.3); ``create_app`` hier
allein bietet alles ausser diesen. Der Lifespan oeffnet die Datenbank: Rolle ``va_read`` mit
schreibgeschuetzten Transaktionen, dazu fuer die Profil-Befehle ``va_profiles``. Die Engines
verbinden sich erst beim ersten Zugriff, Health und Doku kommen ohne Datenbank aus.

Mit ``WEB_API_NATS_URL`` beantwortet der Worker Vorschau und Profil-Befehle ueber NATS (P4.8);
ohne rechnet der Code von scoring im selben Prozess (``src.web``).

Mit ``WEB_API_NATS_URL`` und ``WEB_API_PROJECTIONS_DATABASE_URL`` startet der Lifespan ausserdem
im Hintergrund den Event-Consumer (P4.4): Die Events aus NATS fuellen die Projektionen im Schema
``web``. Ist NATS nicht erreichbar, laeuft die App ohne und versucht es spaeter erneut.

Der WebSocket ``/ws`` (P4.5) meldet die Events des Eventmanagers an die offenen Tabs.

Mit NATS und Projektions-Datenbank verwaltet das web-api auch Runs (P4.7): ``POST /runs`` legt
einen an, eine Hintergrund-Aufgabe startet geplante Runs (``WEB_API_SCHEDULE``), ruft den
Watchdog und leert die Outbox, einmal je ``RUNS_TICK_SECONDS``.

Swagger und OpenAPI liegen unter ``/api``, damit nginx (P3.6) sie mit ``/api/*`` weiterreicht.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from functools import partial
from importlib.metadata import version
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError

from va_platform import tracing
from va_platform.db import create_db_engine
from va_platform.nats import NatsBus

from .api import health, instruments, ranking, reports, runs, scoring
from .events import open_event_consumer
from .ports import RemoteUnavailable
from .read_models import ProjectionReadModel, TableReadModel
from .realtime import endpoint
from .realtime.hub import HubBroadcaster, WebSocketHub
from .realtime.replay import NatsReplayer
from .rpc import RemoteReads, RemoteScoring
from .runs import RunManager
from .security import JsonOnlyMiddleware
from .settings import WebApiSettings

if TYPE_CHECKING:
    from fastapi.routing import APIRoute
    from sqlalchemy import Engine

    from va_contracts import Envelope

    from .ports import ProfileCommands, ScoringPreview
    from .runs import Schedule

API_PREFIX = "/api/v1"

log = logging.getLogger(__name__)


def _operation_id(route: APIRoute) -> str:
    return route.name


NATS_RETRY_SECONDS = 30.0  # so oft versucht das web-api, eine NATS-Verbindung aufzubauen
RUNS_TICK_SECONDS = 60.0  # Takt von Scheduler, Watchdog und Outbox (P4.7)


async def _keep_started(app: FastAPI, attr: str, start: Callable[[], NatsBus], what: str) -> None:
    """Baut eine NATS-Verbindung im Hintergrund auf, bis sie steht, und legt sie unter
    ``app.state.<attr>`` ab: den Event-Consumer (P4.4) und die fuer Request/Reply (P4.8).

    Der Start der App wartet nicht darauf: Ist NATS (noch) nicht da, laeuft das web-api ohne
    weiter und versucht es alle ``NATS_RETRY_SECONDS`` erneut.
    """
    while True:
        try:
            # Im Thread: Der Start wartet auf NATS und darf die Event-Loop nicht blockieren
            bus = await asyncio.to_thread(start)
        except Exception:
            log.warning(
                "%s nicht gestartet, neuer Versuch in %.0f s",
                what,
                NATS_RETRY_SECONDS,
                exc_info=True,
            )
            await asyncio.sleep(NATS_RETRY_SECONDS)
        else:
            setattr(app.state, attr, bus)
            log.info("%s laeuft", what)
            return


def _rpc_bus(url: str) -> NatsBus:
    bus = NatsBus(url)
    bus.start()
    return bus


async def _keep_runs(manager: RunManager, schedule: Schedule | None) -> None:
    """Takt der Run-Verwaltung (P4.7): Scheduler, Watchdog, Outbox. Ein Fehler (etwa die
    Datenbank weg) kostet nur diesen Takt."""
    while True:
        try:
            await asyncio.to_thread(manager.tick, schedule)
        except Exception:
            log.warning("Takt der Run-Verwaltung fehlgeschlagen", exc_info=True)
        await asyncio.sleep(RUNS_TICK_SECONDS)


def _publisher(app: FastAPI) -> Callable[[Envelope[Any]], None] | None:
    """Senden ueber den Bus des Event-Consumers, sobald er laeuft."""
    bus: NatsBus | None = app.state.events
    return None if bus is None else bus.publish


def create_app(
    settings: WebApiSettings | None = None,
    *,
    preview: Callable[[Engine], ScoringPreview] | None = None,
    commands: Callable[[Engine], ProfileCommands] | None = None,
    app_version: str | None = None,
) -> FastAPI:
    """``preview`` bekommt die lesende Engine, ``commands`` die von ``va_profiles``.

    ``app_version`` steht in ``batch.run`` der Runs, die das web-api anlegt; ohne die Version
    des Pakets ``va-web-api``.
    """
    settings = settings or WebApiSettings()  # type: ignore[call-arg]
    run_version = app_version or version("va-web-api")

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        tracing.configure("va-web-api", settings.otel_traces_exporter)  # Runs beginnen hier
        app.state.engine = create_db_engine(
            settings.database_url.get_secret_value(), read_only=True
        )
        profiles_url = settings.profiles_database_url
        app.state.profiles_engine = (
            None if profiles_url is None else create_db_engine(profiles_url.get_secret_value())
        )
        app.state.rpc = None
        if settings.nats_url:
            # P4.8: Vorschau und Profil-Befehle beantwortet der Worker ueber NATS
            app.state.preview = app.state.commands = RemoteScoring(lambda: app.state.rpc)
        else:
            app.state.preview = None if preview is None else preview(app.state.engine)
            app.state.commands = (
                None
                if commands is None or app.state.profiles_engine is None
                else commands(app.state.profiles_engine)
            )
        # P4.5: WebSocket-Hub; der Eventmanager meldet ueber den Broadcaster aus seinen Threads
        app.state.settings = settings
        app.state.hub = WebSocketHub()
        app.state.broadcaster = HubBroadcaster(app.state.hub, asyncio.get_running_loop())
        app.state.events = None
        app.state.projections_engine = None
        app.state.runs = None
        tasks: list[asyncio.Task[None]] = []
        nats_url, projections = settings.nats_url, settings.projections_database_url
        app.state.replayer = NatsReplayer(nats_url) if nats_url else None
        if nats_url:
            tasks.append(
                asyncio.create_task(
                    _keep_started(app, "rpc", partial(_rpc_bus, nats_url), "Verbindung zu scoring")
                )
            )
        if nats_url and projections is not None:
            engine = app.state.projections_engine = create_db_engine(projections.get_secret_value())
            consumer = partial(open_event_consumer, nats_url, engine, app.state.broadcaster)
            tasks.append(
                asyncio.create_task(_keep_started(app, "events", consumer, "Event-Consumer"))
            )
            # P4.7: Runs anlegen, ueberwachen und ihre Events senden
            app.state.runs = RunManager(
                app.state.projections_engine,
                version=run_version,
                limits=settings.watchdog_limits,
                publisher=lambda: _publisher(app),
            )
            tasks.append(asyncio.create_task(_keep_runs(app.state.runs, settings.run_schedule)))
        # P4.9: Mit NATS lesen die REST-Endpunkte aus den Projektionen, sonst aus den Tabellen
        app.state.reader = (
            TableReadModel(app.state.engine)
            if app.state.projections_engine is None
            else ProjectionReadModel(
                app.state.projections_engine, RemoteReads(lambda: app.state.rpc)
            )
        )
        try:
            yield
        finally:
            for task in tasks:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
            for bus in (app.state.events, app.state.rpc):
                if bus is not None:
                    await asyncio.to_thread(bus.close)
            if app.state.replayer is not None:
                with contextlib.suppress(Exception):
                    await app.state.replayer.close()
            app.state.engine.dispose()
            if app.state.profiles_engine is not None:
                app.state.profiles_engine.dispose()
            if app.state.projections_engine is not None:
                app.state.projections_engine.dispose()

    app = FastAPI(
        title="Value-Analyzer web-api",
        version=version("va-web-api"),
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url=f"{API_PREFIX}/openapi.json",
        # Operation-ID = Name der Funktion: Der generierte Client (P3.5) heisst dann
        # latestRankingResource statt latestRankingApiV1RankingLatestGetResource
        generate_unique_id_function=_operation_id,
    )
    # Kein CORSMiddleware: CORS bleibt bewusst aus (ADR-0007)
    app.add_middleware(JsonOnlyMiddleware)
    for module in (health, runs, ranking, instruments, reports, scoring):
        app.include_router(module.router, prefix=API_PREFIX)
    # P4.5: WebSocket unter /ws, nginx reicht ihn neben /api/ weiter
    app.include_router(endpoint.router)

    @app.exception_handler(RemoteUnavailable)
    async def remote_down(request: Request, exc: RemoteUnavailable) -> JSONResponse:  # noqa: ARG001 - Signatur von FastAPI
        return JSONResponse(status_code=503, content={"detail": f"{exc.service} nicht erreichbar"})

    @app.exception_handler(OperationalError)
    async def database_down(request: Request, exc: OperationalError) -> JSONResponse:  # noqa: ARG001 - Signatur von FastAPI
        # Keine Details nach aussen: Die Meldung enthielte Host und Rolle
        return JSONResponse(status_code=503, content={"detail": "Datenbank nicht erreichbar"})

    return app
