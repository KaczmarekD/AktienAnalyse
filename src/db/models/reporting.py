"""Schema ``reporting``: erzeugte Reports und jeder Versandversuch."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Identity, LargeBinary, func
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, in_values

CHANNELS = ("mail", "healthcheck")
DELIVERY_KINDS = ("report", "error", "ping_ok", "ping_fail")


class Report(Base):
    __tablename__ = "report"
    __table_args__ = {"schema": "reporting"}  # noqa: RUF012

    id: Mapped[int] = mapped_column(Identity(always=True), primary_key=True)
    run_id: Mapped[int | None] = mapped_column(index=True)  # -> batch.run (logisch)
    scoring_run_id: Mapped[int | None]  # -> scoring.scoring_run (logisch)
    subject: Mapped[str]
    html: Mapped[str]
    csv_bytes: Mapped[bytes] = mapped_column(LargeBinary)
    csv_filename: Mapped[str]
    top_n: Mapped[int]
    bottom_n: Mapped[int]
    generated_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Delivery(Base):
    """Mail- und Healthcheck-Versand. Bei Healthchecks nur der Host, nie die UUID."""

    __tablename__ = "delivery"
    __table_args__ = (
        CheckConstraint(in_values("channel", CHANNELS), name="channel"),
        CheckConstraint(in_values("kind", DELIVERY_KINDS), name="kind"),
        {"schema": "reporting"},
    )

    id: Mapped[int] = mapped_column(Identity(always=True), primary_key=True)
    run_id: Mapped[int | None] = mapped_column(index=True)
    report_id: Mapped[int | None] = mapped_column(ForeignKey("reporting.report.id"))
    channel: Mapped[str]
    kind: Mapped[str]
    recipient: Mapped[str | None]
    subject: Mapped[str | None]
    success: Mapped[bool]
    error: Mapped[str | None]
    sent_at: Mapped[datetime] = mapped_column(server_default=func.now())
