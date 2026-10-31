"""``GET /api/v1/health``: lebt der Prozess? Ohne Datenbank, damit er auch dann antwortet."""

from __future__ import annotations

from importlib.metadata import version
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(tags=["health"])


class Health(BaseModel):
    status: Literal["ok"]
    version: str


@router.get("/health")
def health() -> Health:
    return Health(status="ok", version=version("va-web-api"))
