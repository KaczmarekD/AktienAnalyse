"""FastAPI-App des web-api (P3.1).

Start: ``uvicorn --factory va_web_api.main:create_app``. Der Lifespan oeffnet die Datenbank:
Rolle ``va_read`` und zusaetzlich schreibgeschuetzte Transaktionen. Die Engine verbindet sich
erst beim ersten Zugriff, Health und Doku kommen ohne Datenbank aus.

Swagger und OpenAPI liegen unter ``/api``, damit nginx (P3.6) sie mit ``/api/*`` weiterreicht.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from importlib.metadata import version
from typing import TYPE_CHECKING

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError

from va_platform.db import create_db_engine

from .api import health, instruments, ranking, reports, runs
from .security import JsonOnlyMiddleware
from .settings import WebApiSettings

if TYPE_CHECKING:
    from fastapi.routing import APIRoute

API_PREFIX = "/api/v1"


def _operation_id(route: APIRoute) -> str:
    return route.name


def create_app(settings: WebApiSettings | None = None) -> FastAPI:
    settings = settings or WebApiSettings()  # type: ignore[call-arg]

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.engine = create_db_engine(
            settings.database_url.get_secret_value(), read_only=True
        )
        try:
            yield
        finally:
            app.state.engine.dispose()

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
    for module in (health, runs, ranking, instruments, reports):
        app.include_router(module.router, prefix=API_PREFIX)

    @app.exception_handler(OperationalError)
    async def database_down(request: Request, exc: OperationalError) -> JSONResponse:  # noqa: ARG001 - Signatur von FastAPI
        # Keine Details nach aussen: Die Meldung enthielte Host und Rolle
        return JSONResponse(status_code=503, content={"detail": "Datenbank nicht erreichbar"})

    return app
