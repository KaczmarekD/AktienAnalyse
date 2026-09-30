"""Schema ``batch``: Laeufe, deren Logs und importierte Altdateien."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Identity, func
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, in_values

RUN_KINDS = ("batch", "rescore", "import")
RUN_STATUSES = ("running", "success", "partial", "no_data", "failed")


class Run(Base):
    """Ein Batch-Lauf. Einziges UPDATE: der einmalige Abschluss (finished_at)."""

    __tablename__ = "run"
    __table_args__ = (
        CheckConstraint(in_values("kind", RUN_KINDS), name="kind"),
        CheckConstraint(in_values("status", RUN_STATUSES), name="status"),
        {"schema": "batch"},
    )

    id: Mapped[int] = mapped_column(Identity(always=True), primary_key=True)
    kind: Mapped[str]
    status: Mapped[str]
    started_at: Mapped[datetime] = mapped_column(server_default=func.now())
    finished_at: Mapped[datetime | None]
    app_version: Mapped[str]
    dry_run: Mapped[bool]
    force_refresh: Mapped[bool]
    universe_mode: Mapped[str | None]
    settings: Mapped[dict[str, Any] | None]  # ohne Passwoerter/URLs
    # Logische Verweise in andere Schemas (bewusst ohne Fremdschluessel)
    fetch_run_id: Mapped[int | None]
    scoring_run_id: Mapped[int | None]
    report_id: Mapped[int | None]
    universe_size: Mapped[int | None]
    scored_count: Mapped[int | None]
    failed_count: Mapped[int | None]
    exit_code: Mapped[int | None]
    error: Mapped[str | None]


class RunLog(Base):
    __tablename__ = "run_log"
    __table_args__ = {"schema": "batch"}  # noqa: RUF012

    id: Mapped[int] = mapped_column(Identity(always=True), primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("batch.run.id"), index=True)
    ts: Mapped[datetime]
    level: Mapped[str]
    logger: Mapped[str]
    message: Mapped[str]


class ImportFile(Base):
    """Register importierter Altdateien - verhindert Doppelimporte."""

    __tablename__ = "import_file"
    __table_args__ = {"schema": "batch"}  # noqa: RUF012

    id: Mapped[int] = mapped_column(Identity(always=True), primary_key=True)
    file_name: Mapped[str]
    sha256: Mapped[str] = mapped_column(unique=True)
    kind: Mapped[str]
    run_id: Mapped[int | None] = mapped_column(ForeignKey("batch.run.id"))
    imported_at: Mapped[datetime] = mapped_column(server_default=func.now())
