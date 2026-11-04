"""``/ranking``: alle Titel eines Bewertungslaufs."""

from __future__ import annotations

from fastapi import APIRouter

from ..models import Ranking
from .deps import NOT_FOUND, Reader, not_found

router = APIRouter(tags=["ranking"])


@router.get("/ranking/latest", responses=NOT_FOUND)
def latest_ranking(reader: Reader) -> Ranking:
    """Juengster Bewertungslauf ausser Rescores."""
    scoring_run_id = reader.latest_scoring_run_id()
    ranking = None if scoring_run_id is None else reader.get_ranking(scoring_run_id)
    if ranking is None:
        raise not_found("Bewertungslauf")
    return ranking


@router.get("/ranking/{scoring_run_id}", responses=NOT_FOUND)
def get_ranking(scoring_run_id: int, reader: Reader) -> Ranking:
    ranking = reader.get_ranking(scoring_run_id)
    if ranking is None:
        raise not_found("Bewertungslauf")
    return ranking
