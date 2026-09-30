"""Zugriffe auf ``reporting``: erzeugte Reports und Versandprotokoll."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import insert, select

from ..models import Delivery, Report

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


class ReportingRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    # --- write -------------------------------------------------------------

    def write_report(
        self,
        *,
        run_id: int | None,
        scoring_run_id: int | None,
        subject: str,
        html: str,
        csv_bytes: bytes,
        csv_filename: str,
        top_n: int,
        bottom_n: int,
    ) -> int:
        stmt = insert(Report).values(
            run_id=run_id,
            scoring_run_id=scoring_run_id,
            subject=subject,
            html=html,
            csv_bytes=csv_bytes,
            csv_filename=csv_filename,
            top_n=top_n,
            bottom_n=bottom_n,
        )
        return self.session.execute(stmt.returning(Report.id)).scalar_one()

    def write_delivery(
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
    ) -> int:
        stmt = insert(Delivery).values(
            run_id=run_id,
            report_id=report_id,
            channel=channel,
            kind=kind,
            recipient=recipient,
            subject=subject,
            success=success,
            error=error,
        )
        return self.session.execute(stmt.returning(Delivery.id)).scalar_one()

    # --- get ---------------------------------------------------------------

    def get_report(self, report_id: int) -> Report | None:
        return self.session.get(Report, report_id)

    def get_report_for_run(self, run_id: int) -> Report | None:
        stmt = select(Report).where(Report.run_id == run_id).order_by(Report.id.desc()).limit(1)
        return self.session.scalars(stmt).first()

    def get_deliveries(self, run_id: int) -> list[Delivery]:
        stmt = (
            select(Delivery)
            .where(Delivery.run_id == run_id)
            .order_by(Delivery.sent_at, Delivery.id)
        )
        return list(self.session.scalars(stmt))
