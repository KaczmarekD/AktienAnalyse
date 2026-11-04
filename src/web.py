"""Composition Root des web-api-Prozesses (P3.3): ``uvicorn --factory src.web:create_app``.

Ohne NATS rechnet der Code von scoring im selben Prozess. Seit P5.1a sind das dieselben Handler,
die scoring ueber NATS bedient (``va_scoring.entrypoints.rpc``), nur ueber einen ``LocalCaller``:
die Vorschau mit der lesenden Verbindung (``va_read``), die Profil-Befehle mit ``va_profiles``.
Das web-api darf ``va_scoring`` nicht importieren, ``src`` schon. Mit ``WEB_API_NATS_URL``
beantwortet scoring beides selbst (P4.8); dann nutzt das web-api von hier nur die Version.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from va_platform.service import LocalCaller
from va_scoring.entrypoints import rpc as scoring_rpc
from va_web_api import main as web_api
from va_web_api.rpc import RemoteScoring

from . import __version__

if TYPE_CHECKING:
    from fastapi import FastAPI
    from sqlalchemy import Engine

    from va_web_api.settings import WebApiSettings

__all__ = ["create_app", "local_scoring"]


def local_scoring(engine: Engine) -> RemoteScoring:
    """Die Ports ``ScoringPreview`` und ``ProfileCommands`` ohne NATS, mit ``engine``."""
    caller = LocalCaller(scoring_rpc.handlers(engine))
    return RemoteScoring(lambda: caller)


def create_app(settings: WebApiSettings | None = None) -> FastAPI:
    return web_api.create_app(
        settings, preview=local_scoring, commands=local_scoring, app_version=__version__
    )
