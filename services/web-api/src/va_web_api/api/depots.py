"""``/depots``: eigene Depots und Depotstaende (D3.2, docs/architecture/depot/depots.md).

portfolio beantwortet alles per Request/Reply (``rpc.va.portfolio.*``); das web-api haelt keine
Depots. Jede Anfrage nennt den angemeldeten Nutzer, portfolio prueft den Besitz noch einmal.

- Nur mit echter Sitzung, auch im Uebergang ohne Sitzungspflicht (``depot_owner``).
- Ein fremdes oder unbekanntes Depot ist 404, ohne portfolio 503.
- Speichern ist optimistisch wie bei den Profilen: ``If-Match`` nennt den Depotstand, auf dem die
  Aenderung beruht (aus dem ``ETag`` beim Lesen). Ist er nicht mehr der neueste: 409, ohne
  ``If-Match``: 428. Ein archiviertes Depot aendert sich erst nach dem Wiederherstellen (409).
- Datei im eigenen Format (D3.5): ``import/preview`` gleicht ab, ``import`` uebernimmt (mit
  ``If-Match``), ``holdings/csv`` liefert die Positionen. Lesen und Schreiben des Formats macht
  portfolio; das web-api prueft nur Base64 und Groesse (413) und nennt eine sichere Datei.
"""

from __future__ import annotations

import base64
import binascii
import re
from collections.abc import Callable
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Path, Query, Request, Response

from va_contracts.portfolio import (
    MAX_FILE_BYTES,
    MAX_HINT_KEY,
    CashLineV1,
    DepotSettingsV1,
    HintParamsV1,
    HoldingLineV1,
    TargetAllocationV1,
)
from va_contracts.securities import ISIN_PATTERN

from ..models import (
    CreateDepot,
    Depot,
    DepotAnalysis,
    DepotComparison,
    DepotHintParams,
    DepotHints,
    DepotTarget,
    HintRule,
    HistoryEntry,
    Holdings,
    ImportFile,
    ImportPreview,
    SaveHoldings,
    UpdateDepot,
)
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
FILE: dict[int | str, dict[str, Any]] = {
    413: {"description": "Datei groesser als 640 KiB"},
    422: {"description": "Kein Base64 oder Datei nicht lesbar; beim Uebernehmen: Zeilen abgelehnt"},
}
SAFE_FILENAME = re.compile(r"^[A-Za-z0-9._-]{1,100}$")


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


def _content(body: ImportFile) -> bytes:
    try:
        content = base64.b64decode(body.content_base64, validate=True)
    except (binascii.Error, ValueError) as e:
        raise HTTPException(status_code=422, detail="Die Datei ist kein gueltiges Base64") from e
    if len(content) > MAX_FILE_BYTES:
        raise HTTPException(status_code=413, detail="Die Datei ist groesser als 640 KiB")
    return content


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


@router.get("/depots/{depot_id}/analysis", responses={**NOT_FOUND, **UNAVAILABLE})
def depot_analysis(user: DepotOwner, directory: Directory, depot_id: int) -> DepotAnalysis:
    """D4.4: Allokation, Konzentration, Qualitaet, Kosten, Anleihen und Datenlage; 503, wenn
    portfolio die Marktdaten nicht lesen kann."""
    analysis = _guarded(lambda: directory.analysis(user.id, depot_id))
    if analysis is None:
        raise HTTPException(status_code=503, detail="Analyse ohne Marktdaten nicht moeglich")
    return DepotAnalysis.model_validate(analysis.model_dump())


@router.get("/depots/{depot_id}/hints", responses={**NOT_FOUND, **UNAVAILABLE})
def depot_hints(user: DepotOwner, directory: Directory, depot_id: int) -> DepotHints:
    """D5.2: Hinweise des juengsten Laufs mit Status und Texten des Katalogs; ohne Lauf rechnet
    portfolio zuerst einen. Beobachtungen, keine Anlageempfehlung."""
    hints = _guarded(lambda: directory.hints(user.id, depot_id))
    if hints is None:  # pragma: no cover - portfolio antwortet mit Hinweisen oder Fehler
        raise HTTPException(status_code=503, detail="Hinweise nicht verfuegbar")
    return DepotHints.model_validate(hints.model_dump())


def _params(settings: DepotSettingsV1, response: Response) -> DepotHintParams:
    response.headers["ETag"] = _etag(settings.hint_params_version)
    return DepotHintParams(version=settings.hint_params_version, params=settings.hint_params)


def _target(settings: DepotSettingsV1, response: Response) -> DepotTarget:
    response.headers["ETag"] = _etag(settings.target_version)
    return DepotTarget(version=settings.target_version, shares=dict(settings.target.shares))


@router.get("/depots/{depot_id}/hint-params", responses={**NOT_FOUND, **UNAVAILABLE})
def get_hint_params(
    user: DepotOwner, directory: Directory, depot_id: int, response: Response
) -> DepotHintParams:
    """D5.3: Schwellen der Hinweise (HIN-04), ohne gespeicherte die Standardwerte (Version 0)."""
    return _params(_guarded(lambda: directory.settings(user.id, depot_id)), response)


@router.put("/depots/{depot_id}/hint-params", responses={**NOT_FOUND, **UNAVAILABLE, **CONFLICT})
def save_hint_params(
    user: DepotOwner,
    directory: Directory,
    depot_id: int,
    body: HintParamsV1,
    response: Response,
    if_match: Annotated[str | None, Header()] = None,
) -> DepotHintParams:
    """Neue Schwellen auf die Version aus ``If-Match``; danach rechnet das Depot neu."""
    base = if_match_version(if_match, missing="die Version der Schwellen, auf der sie beruhen")
    settings = _guarded(
        lambda: directory.save_hint_params(user.id, depot_id, base_version=base, params=body)
    )
    return _params(settings, response)


@router.get("/depots/{depot_id}/target-allocation", responses={**NOT_FOUND, **UNAVAILABLE})
def get_target_allocation(
    user: DepotOwner, directory: Directory, depot_id: int, response: Response
) -> DepotTarget:
    """D5.3: Zielallokation je Anlageklasse (DEP-10); ohne Ziel leer (Version 0)."""
    return _target(_guarded(lambda: directory.settings(user.id, depot_id)), response)


@router.put(
    "/depots/{depot_id}/target-allocation", responses={**NOT_FOUND, **UNAVAILABLE, **CONFLICT}
)
def save_target_allocation(
    user: DepotOwner,
    directory: Directory,
    depot_id: int,
    body: TargetAllocationV1,
    response: Response,
    if_match: Annotated[str | None, Header()] = None,
) -> DepotTarget:
    """Neue Zielallokation auf die Version aus ``If-Match`` (leer: ohne Ziel)."""
    base = if_match_version(if_match, missing="die Version der Zielallokation, auf der sie beruht")
    settings = _guarded(
        lambda: directory.save_target(user.id, depot_id, base_version=base, target=body)
    )
    return _target(settings, response)


@router.get(
    "/depots/{depot_id}/positions/{isin}/comparison", responses={**NOT_FOUND, **UNAVAILABLE}
)
def depot_comparison(
    user: DepotOwner,
    directory: Directory,
    depot_id: int,
    isin: Annotated[str, Path(pattern=ISIN_PATTERN)],
) -> DepotComparison:
    """D5.5 (HIN-06): bis zu drei Titel zum Vergleich im selben Sektor; 404, wenn die Aktie
    nicht im Depot steht, 503 ohne Marktdaten. Aus, solange die Schwellen es nicht einschalten."""
    comparison = _guarded(lambda: directory.comparison(user.id, depot_id, isin))
    if comparison is None:
        raise HTTPException(status_code=503, detail="Vergleich ohne Marktdaten nicht moeglich")
    return DepotComparison.model_validate(comparison.model_dump())


@router.get("/hints/catalog", responses=UNAVAILABLE)
def hint_catalog(user: DepotOwner, directory: Directory) -> list[HintRule]:
    """D5.4: die Regeln der Hinweise mit ihren Texten, fuer die Einstellungen im UI."""
    del user  # nur mit echter Sitzung, wie die Depots
    rules = _guarded(directory.catalog)
    return [HintRule.model_validate(rule.model_dump()) for rule in rules]


@router.post("/depots/{depot_id}/hints/{key}/ack", responses={**NOT_FOUND, **UNAVAILABLE})
def acknowledge_hint(
    user: DepotOwner,
    directory: Directory,
    depot_id: int,
    key: Annotated[str, Path(max_length=MAX_HINT_KEY)],
) -> DepotHints:
    """D5.3, HIN-05: einen Hinweis des juengsten Laufs zur Kenntnis nehmen; 404 ohne ihn."""
    hints = _guarded(lambda: directory.acknowledge(user.id, depot_id, key))
    if hints is None:  # pragma: no cover - portfolio antwortet mit Hinweisen oder Fehler
        raise HTTPException(status_code=503, detail="Hinweise nicht verfuegbar")
    return DepotHints.model_validate(hints.model_dump())


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


@router.post(
    "/depots/{depot_id}/import/preview",
    responses={**NOT_FOUND, **UNAVAILABLE, **WRITE, **FILE},
)
def preview_import(
    user: DepotOwner, directory: Directory, depot_id: int, body: ImportFile
) -> ImportPreview:
    """Abgleich einer Datei im eigenen Format mit dem aktuellen Depotstand; speichert nichts."""
    content = _content(body)
    return _guarded(
        lambda: ImportPreview.model_validate(
            directory.preview_import(user.id, depot_id, content).model_dump()
        )
    )


@router.post(
    "/depots/{depot_id}/import",
    responses={**NOT_FOUND, **UNAVAILABLE, **CONFLICT, **FILE},
)
def import_holdings(
    user: DepotOwner,
    directory: Directory,
    depot_id: int,
    body: ImportFile,
    response: Response,
    if_match: Annotated[str | None, Header()] = None,
) -> Holdings:
    """Die Datei als neuer Depotstand (Herkunft ``import``) auf den Stand aus ``If-Match``; die
    Kasse bleibt. Mit abgelehnten Zeilen 422."""
    base = _base_version(if_match)
    content = _content(body)
    holdings = _guarded(
        lambda: _holdings(
            directory.import_file(user.id, depot_id, base_version=base, content=content)
        )
    )
    response.headers["ETag"] = _etag(holdings.version)
    return holdings


@router.get(
    "/depots/{depot_id}/holdings/csv",
    response_class=Response,
    responses={
        200: {"content": {"text/csv": {}}, "description": "Die Positionen im eigenen Format"},
        **NOT_FOUND,
        **UNAVAILABLE,
    },
)
def holdings_csv(
    user: DepotOwner,
    directory: Directory,
    depot_id: int,
    version: Annotated[int | None, Query(ge=0)] = None,
) -> Response:
    """Die Positionen eines Depotstands (ohne ``version`` des neuesten) als CSV."""
    filename, content = _guarded(lambda: directory.holdings_file(user.id, depot_id, version))
    if not SAFE_FILENAME.match(filename):  # portfolio nennt nur Zahlen; sicher ist sicher
        filename = f"depot-{depot_id}.csv"
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
