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


def _report(repo: ReportingRepository, scoring_run_id: int, subject: str) -> int:
    return repo.write_report(
        run_id=1,
        scoring_run_id=scoring_run_id,
        subject=subject,
        html="<html></html>",
        csv_bytes=b"symbol\n",
        csv_filename="value_ranking_20261003.csv",
        top_n=20,
        bottom_n=10,
    )


def _mail(repo: ReportingRepository, report_id: int, *, success: bool, kind: str = "report"):
    repo.write_delivery(
        run_id=1,
        report_id=report_id,
        channel="mail",
        kind=kind,
        recipient="a@example.com",
        subject="x",
        success=success,
        error=None if success else "smtp",
    )


class TestDeliveredReport:
    """P4.3b: notification verschickt fuer einen Bewertungslauf hoechstens eine Report-Mail."""

    def test_only_a_successful_report_mail_counts(self, session):
        repo = ReportingRepository(session)
        failed = _report(repo, 20, "[ok 2/2] erster Versuch")
        _mail(repo, failed, success=False)
        session.commit()
        assert repo.get_delivered_report(20) is None

        sent = _report(repo, 20, "[ok 2/2] zweiter Versuch")
        _mail(repo, sent, success=True)
        session.commit()
        report = repo.get_delivered_report(20)
        assert report is not None
        assert (report.id, report.subject) == (sent, "[ok 2/2] zweiter Versuch")

    def test_other_scoring_runs_and_error_mails_do_not_count(self, session):
        repo = ReportingRepository(session)
        other = _report(repo, 21, "[ok] anderer Lauf")
        _mail(repo, other, success=True)
        own = _report(repo, 20, "[ok] dieser Lauf")
        _mail(repo, own, success=True, kind="error")
        session.commit()
        assert repo.get_delivered_report(20) is None

    def test_store_returns_id_and_subject(self, engine):
        from va_notification.adapters.postgres.store import PostgresReportStore
        from va_platform.db import session_scope

        with session_scope(engine) as s:
            repo = ReportingRepository(s)
            rid = _report(repo, 20, "[ok 2/2] Test")
            _mail(repo, rid, success=True)
        store = PostgresReportStore(engine)
        assert store.delivered_report(20) == (rid, "[ok 2/2] Test")
        assert store.delivered_report(99) is None
