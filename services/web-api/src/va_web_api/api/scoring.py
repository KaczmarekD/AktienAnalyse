"""``/scoring``: Faktor-Katalog, Scoring-Profile und ihre Vorschau (P3.3, ADR-0009).

Lesen geht wie ueberall ueber ``va_read``. Speichern, Aktivieren und die Vorschau rechnet der
Code von scoring hinter den Ports aus ``..ports``. Fehlen sie, antworten diese Endpunkte mit 503.

Speichern ist optimistisch: ``If-Match`` nennt die Version, auf der die Aenderung beruht (aus
dem ``ETag`` der Detail-Antwort). Hat ein anderer Tab inzwischen gespeichert, gibt es 409, und
das UI bietet Neuladen an.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response

from va_contracts.profile import ProfileParamsV1

from .. import read
from ..models import (
    ActivatedProfile,
    ActivateProfileVersion,
    ActiveProfileRef,
    Factor,
    Preview,
    PreviewRow,
    ProfileDetail,
    ProfileSummary,
    SavedProfileVersion,
    SaveProfileVersion,
)
from ..ports import (
    NoPreviewData,
    PreviewBasis,
    ProfileCommands,
    ProfileConflict,
    RankedTitle,
    ScoringPreview,
    UnknownProfile,
    UnknownVersion,
)
from .deps import NOT_FOUND, Conn, not_found

router = APIRouter(tags=["scoring"])

UNAVAILABLE: dict[int | str, dict[str, Any]] = {503: {"description": "Scoring nicht verfuegbar"}}
CONFLICT: dict[int | str, dict[str, Any]] = {
    409: {"description": "Version ist nicht mehr die neueste"},
    428: {"description": "If-Match fehlt"},
}


def _preview_port(request: Request) -> ScoringPreview:
    port = request.app.state.preview
    if port is None:
        raise HTTPException(status_code=503, detail="Vorschau nicht verfuegbar")
    return port


def _commands_port(request: Request) -> ProfileCommands:
    port = request.app.state.commands
    if port is None:
        # Ohne WEB_API_PROFILES_DATABASE_URL (Rolle va_profiles) kein Schreibzugang
        raise HTTPException(status_code=503, detail="Profile lassen sich hier nicht speichern")
    return port


PreviewPort = Annotated[ScoringPreview, Depends(_preview_port)]
CommandsPort = Annotated[ProfileCommands, Depends(_commands_port)]


@router.get("/scoring/factors", responses=UNAVAILABLE)
def list_factors(preview: PreviewPort) -> list[Factor]:
    """Der Faktor-Katalog mit Richtung und Methodik-Hinweis."""
    return preview.factors()


@router.get("/scoring/profiles")
def list_profiles(conn: Conn) -> list[ProfileSummary]:
    return read.list_profiles(conn)


@router.get("/scoring/profiles/{profile_id}", responses=NOT_FOUND)
def get_profile(profile_id: int, conn: Conn, response: Response) -> ProfileDetail:
    """Ein Profil mit allen Versionen, neueste zuerst. ``ETag``: die neueste Version."""
    profile = read.get_profile(conn, profile_id)
    if profile is None:
        raise not_found("Profil")
    if profile.latest_version is not None:
        response.headers["ETag"] = _etag(profile.latest_version)
    return profile


@router.put(
    "/scoring/profiles/{profile_id}",
    status_code=201,
    responses={**NOT_FOUND, **CONFLICT, **UNAVAILABLE},
)
def save_profile_version(
    profile_id: int,
    body: SaveProfileVersion,
    commands: CommandsPort,
    response: Response,
    if_match: Annotated[str | None, Header()] = None,
) -> SavedProfileVersion:
    """Neue Version auf Grundlage der Version aus ``If-Match``. Aktiviert sie nicht."""
    based_on = _based_on(if_match)
    try:
        version = commands.save_version(
            profile_id, body.params, based_on=based_on, comment=body.comment
        )
    except UnknownProfile as e:
        raise not_found("Profil") from e
    except ProfileConflict as e:
        detail = f"Version {based_on} ist nicht mehr die neueste (aktuell: {e.newest})"
        raise HTTPException(status_code=409, detail=detail) from e
    response.headers["ETag"] = _etag(version)
    return SavedProfileVersion(profile_id=profile_id, version=version, parent_version=based_on)


@router.post("/scoring/profiles/{profile_id}/activate", responses={**NOT_FOUND, **UNAVAILABLE})
def activate_profile_version(
    profile_id: int, body: ActivateProfileVersion, commands: CommandsPort
) -> ActivatedProfile:
    """Macht die Version aktiv, auch eine aeltere. Der naechste Lauf rechnet damit."""
    try:
        commands.activate(profile_id, body.version)
    except UnknownProfile as e:
        raise not_found("Profil") from e
    except UnknownVersion as e:
        raise not_found("Version") from e
    return ActivatedProfile(profile_id=profile_id, version=body.version)


@router.post("/scoring/preview", responses={**NOT_FOUND, **UNAVAILABLE})
def preview_profile(
    params: ProfileParamsV1,
    preview: PreviewPort,
    top: Annotated[int, Query(ge=1, le=100)] = 20,
) -> Preview:
    """Ranking mit ``params`` auf den Daten des juengsten Bewertungslaufs, verglichen mit dem
    aktiven Profil. Speichert nichts."""
    try:
        basis = preview.preview(params)
    except NoPreviewData as e:
        raise not_found("Bewertungslauf") from e
    return compare(basis, top=top)


def compare(basis: PreviewBasis, *, top: int) -> Preview:
    """Vorher und nachher je Titel, dazu was in die Top ``top`` kommt und was herausfaellt."""
    before = {t.symbol: t for t in basis.current}
    top_before = _top(basis.current, top)
    top_after = _top(basis.preview, top)
    rows = [_row(t, before.get(t.symbol)) for t in basis.preview]
    active = None
    if basis.active_profile_id is not None and basis.active_version is not None:
        active = ActiveProfileRef(
            profile_id=basis.active_profile_id,
            name=basis.active_name or f"#{basis.active_profile_id}",
            version=basis.active_version,
        )
    return Preview(
        scoring_run_id=basis.scoring_run_id,
        fetch_run_id=basis.fetch_run_id,
        fetched_on=basis.fetched_on,
        active=active,
        top=top,
        entered=[s for s in top_after if s not in top_before],
        left=[s for s in top_before if s not in top_after],
        trap_changed=[
            r.symbol
            for r in rows
            if r.value_trap_flag_active is not None
            and r.value_trap_flag is not None
            and r.value_trap_flag != r.value_trap_flag_active
        ],
        rows=rows,
    )


def _top(titles: list[RankedTitle], top: int) -> list[str]:
    ranked = [t for t in titles if t.rank is not None and t.composite_score is not None]
    return [t.symbol for t in sorted(ranked, key=lambda t: t.rank or 0)[:top]]


def _row(after: RankedTitle, before: RankedTitle | None) -> PreviewRow:
    return PreviewRow(
        symbol=after.symbol,
        name=after.name,
        index=after.index,
        passed_filter=after.passed_filter,
        rank=after.rank,
        rank_active=None if before is None else before.rank,
        composite_score=after.composite_score,
        value_score=after.value_score,
        quality_score=after.quality_score,
        value_trap_flag=after.value_trap_flag,
        value_trap_flag_active=None if before is None else before.value_trap_flag,
    )


def _etag(version: int) -> str:
    return f'"{version}"'


def _based_on(if_match: str | None) -> int:
    if if_match is None:
        raise HTTPException(
            status_code=428, detail="If-Match fehlt: die Version, auf der die Aenderung beruht"
        )
    value = if_match.strip().removeprefix("W/").strip('"')
    if not value.isdigit():
        raise HTTPException(status_code=400, detail='If-Match muss eine Version sein, z. B. "3"')
    return int(value)
