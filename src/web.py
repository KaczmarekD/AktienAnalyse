"""Composition Root des web-api-Prozesses (P3.3): ``uvicorn --factory src.web:create_app``.

Verdrahtet die Ports des web-api mit dem Code von scoring, im selben Prozess: die Vorschau mit
der lesenden Verbindung (``va_read``), die Profil-Befehle mit ``va_profiles``
(``src/scoring_ops.py``). Das web-api darf ``va_scoring`` nicht importieren, ``src`` schon. Mit
``WEB_API_NATS_URL`` beantwortet seit P4.8 der Worker beides ueber NATS; dann nutzt das web-api
von hier nur noch die Version fuer ``batch.run``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from va_web_api import main as web_api

from . import __version__
from .scoring_ops import InProcessCommands, InProcessPreview

if TYPE_CHECKING:
    from fastapi import FastAPI

    from va_web_api.settings import WebApiSettings

__all__ = ["InProcessCommands", "InProcessPreview", "create_app"]


def create_app(settings: WebApiSettings | None = None) -> FastAPI:
    return web_api.create_app(
        settings, preview=InProcessPreview, commands=InProcessCommands, app_version=__version__
    )
