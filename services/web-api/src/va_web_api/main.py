"""FastAPI-App des web-api (P3.1).

Start im Betrieb: ``uvicorn --factory src.web:create_app``. Diese Composition Root verdrahtet
die Ports fuer Vorschau und Profil-Befehle mit dem Code von scoring (P3.3); ``create_app`` hier
allein bietet alles ausser diesen. Der Lifespan oeffnet die Datenbank: Rolle ``va_read`` mit
schreibgeschuetzten Transaktionen, dazu fuer die Profil-Befehle ``va_profiles``. Die Engines
verbinden sich erst beim ersten Zugriff, Health und Doku kommen ohne Datenbank aus.

Swagger und OpenAPI liegen unter ``/api``, damit nginx (P3.6) sie mit ``/api/*`` weiterreicht.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from importlib.metadata import version
from typing import TYPE_CHECKING

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError

from va_platform.db import create_db_engine

from .api import health, instruments, ranking, reports, runs, scoring
from .security import JsonOnlyMiddleware
from .settings import WebApiSettings

if TYPE_CHECKING:
    from fastapi.routing import APIRoute
    from sqlalchemy import Engine

    from .ports import ProfileCommands, ScoringPreview

API_PREFIX = "/api/v1"


def _operation_id(route: APIRoute) -> str:
    return route.name


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
        try:
            yield
        finally:
            app.state.engine.dispose()
            if app.state.profiles_engine is not None:
                app.state.profiles_engine.dispose()

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

    @app.exception_handler(OperationalError)
    async def database_down(request: Request, exc: OperationalError) -> JSONResponse:  # noqa: ARG001 - Signatur von FastAPI
        # Keine Details nach aussen: Die Meldung enthielte Host und Rolle
        return JSONResponse(status_code=503, content={"detail": "Datenbank nicht erreichbar"})

    return app
