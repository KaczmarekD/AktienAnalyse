"""``GET /api/v1/health``: lebt der Prozess? Ohne Datenbank, damit er auch dann antwortet.

Seit D1.4 sagt er auch, ob eine Anmeldung noetig ist (``auth_required``): Im Uebergang ohne
Sitzungspflicht zeigt das UI dann keine Anmeldung.
"""

from __future__ import annotations

from importlib.metadata import version
from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel

router = APIRouter(tags=["health"])


class Health(BaseModel):
    status: Literal["ok"]
    version: str
    auth_required: bool


@router.get("/health")
def health(request: Request) -> Health:
    return Health(
        status="ok",
        version=version("va-web-api"),
        auth_required=request.app.state.settings.auth_required,
    )
