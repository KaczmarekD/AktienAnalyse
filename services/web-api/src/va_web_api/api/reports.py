"""``/reports``: die gerenderte Mail und ihre CSV, auch von Dry-Runs."""

from __future__ import annotations

from fastapi import APIRouter, Response

from ..models import Report
from .deps import NOT_FOUND, Reader, not_found

router = APIRouter(tags=["reports"])


@router.get("/reports/{report_id}", responses=NOT_FOUND)
def get_report(report_id: int, reader: Reader) -> Report:
    report = reader.get_report(report_id)
    if report is None:
        raise not_found("Report")
    return report


@router.get(
    "/reports/{report_id}/csv",
    response_class=Response,
    responses={200: {"content": {"text/csv": {}}, "description": "Die CSV der Mail"}, **NOT_FOUND},
)
def get_report_csv(report_id: int, reader: Reader) -> Response:
    found = reader.get_report_csv(report_id)
    if found is None:
        raise not_found("Report")
    filename, data = found
    return Response(
        content=data,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
