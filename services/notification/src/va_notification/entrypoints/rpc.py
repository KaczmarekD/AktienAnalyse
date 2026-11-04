"""Request/Reply von notification (P4.9, beim Besitzer seit P5.1a): Report und CSV lesen.

Liest nur das Schema ``reporting``. Nicht gefunden ist eine leere Antwort; das web-api macht
daraus 404.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from va_contracts.rpc.v1 import (
    REPORT_CSV,
    REPORT_GET,
    ReportCsvReplyV1,
    ReportReplyV1,
    ReportRequestV1,
    ReportV1,
)
from va_platform.db import session_scope

from ..adapters.postgres import ReportingRepository

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy import Engine

    from va_contracts.rpc.v1 import RpcReplyV1, RpcSpec


def handlers(engine: Engine) -> dict[RpcSpec[Any, Any], Callable[[Any], RpcReplyV1]]:
    def report(request: ReportRequestV1) -> ReportReplyV1:
        with session_scope(engine) as s:
            found = ReportingRepository(s).get_report(request.report_id)
            if found is None:
                return ReportReplyV1()
            return ReportReplyV1(
                report=ReportV1(
                    id=found.id,
                    run_id=found.run_id,
                    scoring_run_id=found.scoring_run_id,
                    subject=found.subject,
                    generated_at=found.generated_at,
                    csv_filename=found.csv_filename,
                    html=found.html,
                )
            )

    def report_csv(request: ReportRequestV1) -> ReportCsvReplyV1:
        with session_scope(engine) as s:
            found = ReportingRepository(s).get_report(request.report_id)
            if found is None:
                return ReportCsvReplyV1()
            return ReportCsvReplyV1(filename=found.csv_filename, content=bytes(found.csv_bytes))

    return {REPORT_GET: report, REPORT_CSV: report_csv}
