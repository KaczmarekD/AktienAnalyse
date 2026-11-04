"""``/runs``: Laeufe des Batches (``batch.run``) und der Start aus dem UI (P4.7)."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from va_contracts.events.v1 import RunOptionsV1

from .. import read
from ..models import RunDetail, RunStart, RunStarted, RunSummary
from ..ports import RunActive, RunStarter
from .deps import NOT_FOUND, Conn, not_found

router = APIRouter(tags=["runs"])

START_RESPONSES: dict[int | str, dict[str, Any]] = {
    409: {"description": "Es laeuft schon ein Run"},
    503: {"description": "Runs lassen sich hier nicht starten (ohne NATS)"},
}


def _runs_port(request: Request) -> RunStarter:
    port = request.app.state.runs
    if port is None:
        raise HTTPException(
            status_code=503,
            detail="Runs starten braucht NATS und die Projektions-Datenbank des web-api",
        )
    return port


RunsPort = Annotated[RunStarter, Depends(_runs_port)]


@router.get("/runs")
def list_runs(
    conn: Conn,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[RunSummary]:
    """Laeufe, neueste zuerst."""
    return read.list_runs(conn, limit=limit, offset=offset)


@router.post("/runs", status_code=202, responses=START_RESPONSES)
def start_run(body: RunStart, runs: RunsPort) -> RunStarted:
    """Startet einen Run. Ausgefuehrt wird er vom Worker ueber NATS; Fortschritt und Ergebnis
    meldet der WebSocket."""
    options = RunOptionsV1(
        force_refresh=body.force_refresh, dry_run=body.dry_run, notify=body.notify
    )
    try:
        run_id = runs.start(options)
    except RunActive as e:
        raise HTTPException(status_code=409, detail=f"Lauf #{e.run_id} läuft noch") from e
    return RunStarted(id=run_id)


@router.get("/runs/{run_id}", responses=NOT_FOUND)
def get_run(run_id: int, conn: Conn) -> RunDetail:
    run = read.get_run(conn, run_id)
    if run is None:
        raise not_found("Lauf")
    return run
