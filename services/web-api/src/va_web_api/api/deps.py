"""Gemeinsames der Router: Datenbankverbindung je Anfrage, 404."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated, Any

from fastapi import Depends, HTTPException, Request
from sqlalchemy import Connection


def connection(request: Request) -> Iterator[Connection]:
    with request.app.state.engine.connect() as conn:
        yield conn


Conn = Annotated[Connection, Depends(connection)]

NOT_FOUND: dict[int | str, dict[str, Any]] = {404: {"description": "Nicht gefunden"}}


def not_found(what: str) -> HTTPException:
    return HTTPException(status_code=404, detail=f"{what} nicht gefunden")
