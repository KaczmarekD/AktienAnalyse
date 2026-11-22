"""``/depots``: eigene Depots und Depotstaende (D3.2, docs/architecture/depot/depots.md).

portfolio beantwortet alles per Request/Reply (``rpc.va.portfolio.*``); das web-api haelt keine
Depots. Jede Anfrage nennt den angemeldeten Nutzer, portfolio prueft den Besitz noch einmal.

- Nur mit echter Sitzung, auch im Uebergang ohne Sitzungspflicht (``depot_owner``).
- Ein fremdes oder unbekanntes Depot ist 404, ohne portfolio 503.
- Speichern ist optimistisch wie bei den Profilen: ``If-Match`` nennt den Depotstand, auf dem die
  Aenderung beruht (aus dem ``ETag`` beim Lesen). Ist er nicht mehr der neueste: 409, ohne
  ``If-Match``: 428. Ein archiviertes Depot aendert sich erst nach dem Wiederherstellen (409).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response

from va_contracts.portfolio import CashLineV1, HoldingLineV1

from ..models import CreateDepot, Depot, HistoryEntry, Holdings, SaveHoldings, UpdateDepot
from ..ports import (
    DepotArchived,
    DepotConflict,
    DepotDirectory,
    DepotInvalid,
    DepotNotFound,
    PortfolioUnavailable,
)
from .auth import DepotOwner
from .deps import NOT_FOUND, etag, if_match_version, not_found

router = APIRouter(tags=["depots"])

UNAVAILABLE: dict[int | str, dict[str, Any]] = {503: {"description": "portfolio nicht erreichbar"}}
WRITE: dict[int | str, dict[str, Any]] = {
    409: {"description": "Depot archiviert oder Depotstand nicht mehr der neueste"},
    422: {"description": "Eingabe passt nicht (z. B. ISIN doppelt, Menge fehlt)"},
}
CONFLICT: dict[int | str, dict[str, Any]] = {
    **WRITE,
    428: {"description": "If-Match fehlt"},
}


def _directory(request: Request) -> DepotDirectory:
    directory = getattr(request.app.state, "depots", None)
    if directory is None:
        raise PortfolioUnavailable("portfolio")
    return directory


Directory = Annotated[DepotDirectory, Depends(_directory)]


_etag = etag


def _base_version(if_match: str | None) -> int:
    return if_match_version(if_match, missing="der Depotstand, auf dem die Aenderung beruht")


def _guarded[T](work: Callable[[], T]) -> T:
    """Die Fehler des Ports als Antwort; portfolio nennt keine Inhalte fremder Depots."""
    try:
        return work()
    except DepotNotFound as e:
        raise not_found("Depot") from e
    except DepotArchived as e:
        raise HTTPException(
            status_code=409, detail="Das Depot ist archiviert; erst wiederherstellen"
        ) from e
    except DepotConflict as e:
        detail = "Der Depotstand ist nicht mehr der neueste"
        if e.newest is not None:
            detail += f" (aktuell: {e.newest})"
        raise HTTPException(status_code=409, detail=detail) from e
    except DepotInvalid as e:
        raise HTTPException(status_code=422, detail=str(e)) from e


def _depot(value: Any) -> Depot:
    return Depot.model_validate(value.model_dump())


def _holdings(value: Any) -> Holdings:
    return Holdings.model_validate(value.model_dump())


@router.get("/depots", responses=UNAVAILABLE)
def list_depots(
    user: DepotOwner,
    directory: Directory,
    include_archived: Annotated[bool, Query()] = False,
) -> list[Depot]:
    """Die eigenen Depots, archivierte nur auf Wunsch."""
    return [_depot(d) for d in directory.list(user.id, include_archived=include_archived)]


@router.post("/depots", status_code=201, responses={**UNAVAILABLE, **WRITE})
def create_depot(user: DepotOwner, directory: Directory, body: CreateDepot) -> Depot:
    """Ein neues Depot oder eine Beobachtungsliste, mit dem leeren Depotstand 0."""
    return _guarded(
        lambda: _depot(
            directory.create(user.id, kind=body.kind, name=body.name, description=body.description)
        )
    )


@router.get("/depots/{depot_id}", responses={**NOT_FOUND, **UNAVAILABLE})
def get_depot(user: DepotOwner, directory: Directory, depot_id: int) -> Depot:
    return _guarded(lambda: _depot(directory.get(user.id, depot_id)))


@router.put("/depots/{depot_id}", responses={**NOT_FOUND, **UNAVAILABLE, **WRITE})
def update_depot(user: DepotOwner, directory: Directory, depot_id: int, body: UpdateDepot) -> Depot:
    """Name und Beschreibung (neue Zeile, der Verlauf bleibt)."""
    return _guarded(
        lambda: _depot(
            directory.update(user.id, depot_id, name=body.name, description=body.description)
        )
    )


@router.post("/depots/{depot_id}/archive", responses={**NOT_FOUND, **UNAVAILABLE})
def archive_depot(user: DepotOwner, directory: Directory, depot_id: int) -> Depot:
    """Archivieren (DEP-06): schreibgeschuetzt und aus der Liste, geloescht wird nichts."""
    return _guarded(lambda: _depot(directory.archive(user.id, depot_id)))


@router.post("/depots/{depot_id}/restore", responses={**NOT_FOUND, **UNAVAILABLE})
def restore_depot(user: DepotOwner, directory: Directory, depot_id: int) -> Depot:
    return _guarded(lambda: _depot(directory.restore(user.id, depot_id)))


@router.get("/depots/{depot_id}/holdings", responses={**NOT_FOUND, **UNAVAILABLE})
def get_holdings(
    user: DepotOwner,
    directory: Directory,
    depot_id: int,
    response: Response,
    version: Annotated[int | None, Query(ge=0)] = None,
) -> Holdings:
    """Ein Depotstand, ohne ``version`` der neueste. ``ETag``: seine Version."""
    holdings = _guarded(lambda: _holdings(directory.holdings(user.id, depot_id, version)))
    response.headers["ETag"] = _etag(holdings.version)
    return holdings


@router.put("/depots/{depot_id}/holdings", responses={**NOT_FOUND, **UNAVAILABLE, **CONFLICT})
def save_holdings(
    user: DepotOwner,
    directory: Directory,
    depot_id: int,
    body: SaveHoldings,
    response: Response,
    if_match: Annotated[str | None, Header()] = None,
) -> Holdings:
    """Ein neuer, vollstaendiger Depotstand auf Grundlage des Stands aus ``If-Match``."""
    base = _base_version(if_match)
    lines = [HoldingLineV1.model_validate(line.model_dump()) for line in body.lines]
    cash = [CashLineV1.model_validate(c.model_dump()) for c in body.cash]
    holdings = _guarded(
        lambda: _holdings(
            directory.save(user.id, depot_id, base_version=base, lines=lines, cash=cash)
        )
    )
    response.headers["ETag"] = _etag(holdings.version)
    return holdings


@router.get("/depots/{depot_id}/history", responses={**NOT_FOUND, **UNAVAILABLE})
def depot_history(user: DepotOwner, directory: Directory, depot_id: int) -> list[HistoryEntry]:
    """Alle Depotstaende, neueste zuerst, mit dem Unterschied zum vorherigen."""
    return _guarded(
        lambda: [
            HistoryEntry.model_validate(e.model_dump())
            for e in directory.history(user.id, depot_id)
        ]
    )
