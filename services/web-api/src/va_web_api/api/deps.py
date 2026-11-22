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


def etag(version: int) -> str:
    """``ETag`` einer Version (Profile, seit D3.2 Depotstaende)."""
    return f'"{version}"'


def if_match_version(if_match: str | None, *, missing: str) -> int:
    """Die Version aus ``If-Match``: ohne 428 (``missing`` erklaert, welche), ohne Zahl 400."""
    if if_match is None:
        raise HTTPException(status_code=428, detail=f"If-Match fehlt: {missing}")
    value = if_match.strip().removeprefix("W/").strip('"')
    if not value.isdigit():
        raise HTTPException(status_code=400, detail='If-Match muss eine Version sein, z. B. "3"')
    return int(value)
