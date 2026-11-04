"""FastAPI-App des web-api (P3.1).

Start im Betrieb: ``uvicorn --factory src.web:create_app``. Diese Composition Root verdrahtet
die Ports fuer Vorschau und Profil-Befehle mit dem Code von scoring (P3.3); ``create_app`` hier
allein bietet alles ausser diesen. Der Lifespan oeffnet die Datenbank: Rolle ``va_read`` mit
schreibgeschuetzten Transaktionen, dazu fuer die Profil-Befehle ``va_profiles``. Die Engines
verbinden sich erst beim ersten Zugriff, Health und Doku kommen ohne Datenbank aus.

Mit ``WEB_API_NATS_URL`` und ``WEB_API_PROJECTIONS_DATABASE_URL`` startet der Lifespan ausserdem
im Hintergrund den Event-Consumer (P4.4): Die Events aus NATS fuellen die Projektionen im Schema
``web``. Ist NATS nicht erreichbar, laeuft die App ohne und versucht es spaeter erneut.

Der WebSocket ``/ws`` (P4.5) meldet die Events des Eventmanagers an die offenen Tabs.

Swagger und OpenAPI liegen unter ``/api``, damit nginx (P3.6) sie mit ``/api/*`` weiterreicht.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from importlib.metadata import version
from typing import TYPE_CHECKING

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError

from va_platform.db import create_db_engine

from .api import health, instruments, ranking, reports, runs, scoring
from .events import Broadcaster, open_event_consumer
from .realtime import endpoint
from .realtime.hub import HubBroadcaster, WebSocketHub
from .realtime.replay import NatsReplayer
from .security import JsonOnlyMiddleware
from .settings import WebApiSettings

if TYPE_CHECKING:
    from fastapi.routing import APIRoute
    from sqlalchemy import Engine

    from va_platform.nats import NatsBus

    from .ports import ProfileCommands, ScoringPreview

API_PREFIX = "/api/v1"

log = logging.getLogger(__name__)


def _operation_id(route: APIRoute) -> str:
    return route.name


EVENTS_RETRY_SECONDS = 30.0  # so oft versucht das web-api, den Event-Consumer zu starten


async def _keep_events(app: FastAPI, url: str, engine: Engine, broadcaster: Broadcaster) -> None:
    """Startet den Event-Consumer (P4.4) im Hintergrund, bis er laeuft.

    Der Start der App wartet nicht darauf: Ist NATS (noch) nicht da, laeuft das web-api ohne
    Projektionen weiter und versucht es alle ``EVENTS_RETRY_SECONDS`` erneut.
    """
    while True:
        try:
            # Im Thread: Der Start wartet auf NATS und darf die Event-Loop nicht blockieren
            bus: NatsBus = await asyncio.to_thread(open_event_consumer, url, engine, broadcaster)
        except Exception:
            log.warning(
                "Event-Consumer nicht gestartet, neuer Versuch in %.0f s",
                EVENTS_RETRY_SECONDS,
                exc_info=True,
            )
            await asyncio.sleep(EVENTS_RETRY_SECONDS)
        else:
            app.state.events = bus
            log.info("Event-Consumer laeuft, Projektionen werden gefuellt")
            return


def create_app(
    settings: WebApiSettings | None = None,
    *,
    preview: Callable[[Engine], ScoringPreview] | None = None,
    commands: Callable[[Engine], ProfileCommands] | None = None,
) -> FastAPI:
    """``preview`` bekommt die lesende Engine, ``commands`` die von ``va_profiles``."""
    settings = settings or WebApiSettings()  # type: ignore[call-arg]

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.engine = create_db_engine(
            settings.database_url.get_secret_value(), read_only=True
        )
        profiles_url = settings.profiles_database_url
        app.state.profiles_engine = (
            None if profiles_url is None else create_db_engine(profiles_url.get_secret_value())
        )
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
        starter: asyncio.Task[None] | None = None
        nats_url, projections = settings.nats_url, settings.projections_database_url
        app.state.replayer = NatsReplayer(nats_url) if nats_url else None
        if nats_url and projections is not None:
            app.state.projections_engine = create_db_engine(projections.get_secret_value())
            starter = asyncio.create_task(
                _keep_events(app, nats_url, app.state.projections_engine, app.state.broadcaster)
            )
        try:
            yield
        finally:
            if starter is not None:
                starter.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await starter
            if app.state.events is not None:
                await asyncio.to_thread(app.state.events.close)
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

    @app.exception_handler(OperationalError)
    async def database_down(request: Request, exc: OperationalError) -> JSONResponse:  # noqa: ARG001 - Signatur von FastAPI
        # Keine Details nach aussen: Die Meldung enthielte Host und Rolle
        return JSONResponse(status_code=503, content={"detail": "Datenbank nicht erreichbar"})

    return app
