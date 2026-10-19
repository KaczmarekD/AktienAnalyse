"""get/write-Zugriffe auf das Schema reporting."""

from __future__ import annotations

from va_notification.adapters.postgres import ReportingRepository


class TestReporting:
    def test_report_and_deliveries(self, session):
        repo = ReportingRepository(session)
        rid = repo.write_report(
            run_id=1,
            scoring_run_id=2,
            subject="[ok 2/2] Test",
            html="<html></html>",
            csv_bytes=b"\xef\xbb\xbfsymbol;score\n",
            csv_filename="value_ranking_20261003.csv",
            top_n=20,
            bottom_n=10,
        )
        repo.write_delivery(
            run_id=1,
            report_id=rid,
            channel="mail",
            kind="report",
            recipient="a@example.com",
            subject="[ok 2/2] Test",
            success=True,
        )
        repo.write_delivery(
            run_id=1,
            report_id=None,
            channel="healthcheck",
            kind="ping_fail",
            recipient="hc-ping.com",
            subject=None,
            success=False,
            error="timeout",
        )
        session.commit()

        report = repo.get_report(rid)
        assert report is not None
        assert report.csv_bytes.startswith(b"\xef\xbb\xbf")
        assert repo.get_report_for_run(1).id == rid  # type: ignore[union-attr]
        deliveries = repo.get_deliveries(1)
        assert [(d.channel, d.success) for d in deliveries] == [
            ("mail", True),
            ("healthcheck", False),
        ]
