"""``/ranking``: alle Titel eines Bewertungslaufs."""

from __future__ import annotations

from fastapi import APIRouter

from .. import read
from ..models import Ranking
from .deps import NOT_FOUND, Conn, not_found

router = APIRouter(tags=["ranking"])


@router.get("/ranking/latest", responses=NOT_FOUND)
def latest_ranking(conn: Conn) -> Ranking:
    """Juengster Bewertungslauf ausser Rescores."""
    scoring_run_id = read.latest_scoring_run_id(conn)
    ranking = None if scoring_run_id is None else read.get_ranking(conn, scoring_run_id)
    if ranking is None:
        raise not_found("Bewertungslauf")
    return ranking


@router.get("/ranking/{scoring_run_id}", responses=NOT_FOUND)
def get_ranking(scoring_run_id: int, conn: Conn) -> Ranking:
    ranking = read.get_ranking(conn, scoring_run_id)
    if ranking is None:
        raise not_found("Bewertungslauf")
    return ranking
