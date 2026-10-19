"""``ReportStore`` ueber PostgreSQL (Schema ``reporting``), vorher Teil des BatchRecorders."""

from __future__ import annotations

from typing import TYPE_CHECKING

from va_platform.db import session_scope

from .repository import ReportingRepository

if TYPE_CHECKING:
    from sqlalchemy import Engine

    from ...domain.report import ReportArtifacts


class PostgresReportStore:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def record_report(
        self, run_id: int | None, scoring_run_id: int | None, report: ReportArtifacts
    ) -> int:
        with session_scope(self._engine) as s:
            return ReportingRepository(s).write_report(
                run_id=run_id,
                scoring_run_id=scoring_run_id,
                subject=report.subject,
                html=report.html,
                csv_bytes=report.csv_bytes,
                csv_filename=report.csv_filename,
                top_n=report.top_count,
                bottom_n=report.bottom_count,
            )

    def record_delivery(
        self,
        *,
        run_id: int | None,
        report_id: int | None,
        channel: str,
        kind: str,
        recipient: str | None,
        subject: str | None,
        success: bool,
        error: str | None = None,
    ) -> None:
        with session_scope(self._engine) as s:
            ReportingRepository(s).write_delivery(
                run_id=run_id,
                report_id=report_id,
                channel=channel,
                kind=kind,
                recipient=recipient,
                subject=subject,
                success=success,
                error=error,
            )
