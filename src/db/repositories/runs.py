"""Zugriffe auf ``batch``: Laeufe, Log-Zeilen, importierte Altdateien."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, insert, select, update

from ..log_handler import LogEntry
from ..models import ImportFile, Run, RunLog

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


class RunRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    # --- write -------------------------------------------------------------

    def write_run_start(
        self,
        *,
        kind: str,
        app_version: str,
        dry_run: bool,
        force_refresh: bool,
        universe_mode: str | None,
        settings: dict[str, Any] | None,
        started_at: datetime | None = None,
    ) -> int:
        values: dict[str, Any] = {
            "kind": kind,
            "status": "running",
            "app_version": app_version,
            "dry_run": dry_run,
            "force_refresh": force_refresh,
            "universe_mode": universe_mode,
            "settings": settings,
        }
        if started_at is not None:
            values["started_at"] = started_at
        return self.session.execute(insert(Run).values(**values).returning(Run.id)).scalar_one()

    def write_run_finish(
        self,
        run_id: int,
        *,
        status: str,
        exit_code: int,
        fetch_run_id: int | None = None,
        scoring_run_id: int | None = None,
        report_id: int | None = None,
        universe_size: int | None = None,
        scored_count: int | None = None,
        failed_count: int | None = None,
        error: str | None = None,
        finished_at: datetime | None = None,
    ) -> None:
        """Einmaliger Abschluss - danach verweigert die DB jede Aenderung."""
        self.session.execute(
            update(Run)
            .where(Run.id == run_id)
            .values(
                status=status,
                exit_code=exit_code,
                fetch_run_id=fetch_run_id,
                scoring_run_id=scoring_run_id,
                report_id=report_id,
                universe_size=universe_size,
                scored_count=scored_count,
                failed_count=failed_count,
                error=error,
                finished_at=finished_at or func.now(),
            )
        )

    def write_logs(self, run_id: int, entries: Sequence[LogEntry]) -> int:
        if not entries:
            return 0
        self.session.execute(
            insert(RunLog),
            [
                {
                    "run_id": run_id,
                    "ts": e.ts,
                    "level": e.level,
                    "logger": e.logger,
                    "message": e.message,
                }
                for e in entries
            ],
        )
        return len(entries)

    def write_import_file(
        self, *, file_name: str, sha256: str, kind: str, run_id: int | None
    ) -> int:
        stmt = insert(ImportFile).values(
            file_name=file_name, sha256=sha256, kind=kind, run_id=run_id
        )
        return self.session.execute(stmt.returning(ImportFile.id)).scalar_one()

    # --- get ---------------------------------------------------------------

    def get_run(self, run_id: int) -> Run | None:
        return self.session.get(Run, run_id)

    def get_runs(self, since: datetime | None = None, kind: str | None = None) -> list[Run]:
        stmt = select(Run).order_by(Run.started_at, Run.id)
        if since is not None:
            stmt = stmt.where(Run.started_at >= since)
        if kind is not None:
            stmt = stmt.where(Run.kind == kind)
        return list(self.session.scalars(stmt))

    def get_latest_run(self, kind: str | None = None, status: str | None = None) -> Run | None:
        stmt = select(Run).order_by(Run.started_at.desc(), Run.id.desc()).limit(1)
        if kind is not None:
            stmt = stmt.where(Run.kind == kind)
        if status is not None:
            stmt = stmt.where(Run.status == status)
        return self.session.scalars(stmt).first()

    def get_logs(self, run_id: int) -> list[RunLog]:
        stmt = select(RunLog).where(RunLog.run_id == run_id).order_by(RunLog.ts, RunLog.id)
        return list(self.session.scalars(stmt))

    def get_import_file(self, sha256: str) -> ImportFile | None:
        return self.session.scalars(select(ImportFile).where(ImportFile.sha256 == sha256)).first()
