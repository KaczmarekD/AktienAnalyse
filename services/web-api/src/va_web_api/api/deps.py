"""Gemeinsames der Router: Lesemodell (P4.9), 404."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends, HTTPException, Request

from ..ports import ReadModel


def read_model(request: Request) -> ReadModel:
    """Aus den Tabellen oder, mit NATS, aus den Projektionen (``main.create_app``)."""
    return request.app.state.reader


Reader = Annotated[ReadModel, Depends(read_model)]

NOT_FOUND: dict[int | str, dict[str, Any]] = {404: {"description": "Nicht gefunden"}}


def not_found(what: str) -> HTTPException:
    return HTTPException(status_code=404, detail=f"{what} nicht gefunden")
