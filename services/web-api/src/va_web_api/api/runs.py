"""``/runs``: Laeufe des Batches (``batch.run``)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from .. import read
from ..models import RunDetail, RunSummary
from .deps import NOT_FOUND, Conn, not_found

router = APIRouter(tags=["runs"])


@router.get("/runs")
def list_runs(
    conn: Conn,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[RunSummary]:
    """Laeufe, neueste zuerst."""
    return read.list_runs(conn, limit=limit, offset=offset)


@router.get("/runs/{run_id}", responses=NOT_FOUND)
def get_run(run_id: int, conn: Conn) -> RunDetail:
    run = read.get_run(conn, run_id)
    if run is None:
        raise not_found("Lauf")
    return run
