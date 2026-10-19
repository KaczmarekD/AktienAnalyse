"""Handler von notification am Bus (P1.8).

- ``scoring.run.completed``: Report bauen und speichern, verschicken (nicht bei ``dry_run``
  oder ``notify=False``), Healthcheck bei ``trigger=scheduled``, dann
  ``notification.report.sent``. Ein Rescore loest nichts aus.
- ``screening.run.failed``: Healthcheck ``/fail`` (nur ``scheduled``), Fehlermail (nicht bei
  ``dry_run``, ohne ``notify`` oder bei ``no_data``).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

import pytest

from va_contracts import Envelope, new_envelope
from va_contracts.events.v1 import (
    REPORT_SENT,
    RUN_FAILED,
    SCORING_RUN_COMPLETED,
    FundamentalsV1,
    IdentityV1,
    MarketDataV1,
    RankingRowV1,
    RunFailedV1,
    RunOptionsV1,
    ScoringRunCompletedV1,
    UniverseInfoV1,
    UniverseMemberV1,
)
from va_notification.domain.errors import ERROR_SUBJECT, error_mail_html
from va_notification.entrypoints.handlers import (
    NotificationConfig,
    NotificationHandler,
    notify_failure_without_run,
)
from va_platform.bus import InProcessBus

NOW = datetime(2026, 10, 17, 7, 30)


class FakeSender:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.sent: list[dict[str, Any]] = []

    def send(self, subject, html_body, attachment=None):
        self.sent.append({"subject": subject, "html": html_body, "attachment": attachment})
        if self.error:
            raise self.error


class FakeHeartbeat:
    def __init__(self, result: bool | None = True) -> None:
        self.result = result
        self.pings: list[tuple[bool, str | None]] = []

    def ping(self, success, message=None):
        self.pings.append((success, message))
        return self.result


class FakeStore:
    def __init__(self, fail_report: bool = False) -> None:
        self.fail_report = fail_report
        self.reports: list[tuple[int | None, int | None, Any]] = []
        self.deliveries: list[dict[str, Any]] = []

    def record_report(self, run_id, scoring_run_id, report):
        if self.fail_report:
            raise ConnectionError("db weg")
        self.reports.append((run_id, scoring_run_id, report))
        return 30

    def record_delivery(self, **kwargs):
        self.deliveries.append(kwargs)


class Setup:
    def __init__(self, tmp_path, *, sender=None, heartbeat=None, store=None) -> None:
        self.bus = InProcessBus(max_deliver=1)
        self.sender = sender or FakeSender()
        self.heartbeat = heartbeat or FakeHeartbeat()
        self.store = store or FakeStore()
        self.handler = NotificationHandler(
            self.bus,
            sender=self.sender,
            heartbeat=self.heartbeat,
            store=self.store,
            config=NotificationConfig(
                top_n=5,
                bottom_n=3,
                version="9.9.9",
                recipient="r@example.com",
                preview_dir=tmp_path / "data",
                heartbeat_target="hc-ping.com",
                clock=lambda: NOW,
            ),
        )
        self.handler.subscribe()
        self.seen: list[Envelope[Any]] = []
        self.bus.subscribe(REPORT_SENT, "probe-sent", self.seen.append)
        self.bus.subscribe(RUN_FAILED, "probe-failed", self.seen.append)

    def kinds(self) -> list[tuple[str, str, bool]]:
        return [(d["channel"], d["kind"], d["success"]) for d in self.store.deliveries]


@pytest.fixture
def setup(tmp_path) -> Setup:
    return Setup(tmp_path)


def _row(symbol: str, rank: int, composite: float | None) -> RankingRowV1:
    return RankingRowV1(
        fundamentals=FundamentalsV1(
            identity=IdentityV1(symbol=symbol, name=f"{symbol} AG", index="DAX"),
            market=MarketDataV1(market_cap=5e9, price=10.0),
        ),
        rank_overall=rank,
        value_score=composite,
        quality_score=composite,
        composite_score=composite,
    )


def _completed(
    run_id: int | None = 1, trigger: str = "scheduled", **options: bool
) -> ScoringRunCompletedV1:
    return ScoringRunCompletedV1(
        run_id=run_id,
        trigger=trigger,  # type: ignore[arg-type]
        options=RunOptionsV1(**options),
        scoring_run_id=20,
        fetch_run_id=10,
        as_of=date(2026, 10, 17),
        universe=UniverseInfoV1(
            source="iShares",
            as_of=date(2026, 10, 16),
            size=3,
            added=[UniverseMemberV1(symbol="NEU.DE", name="Neu AG", index="MDAX")],
        ),
        value_weight=0.6,
        quality_weight=0.4,
        ranking=[_row("AAA.DE", 1, 0.8), _row("BBB.DE", 2, 0.5), _row("CCC.DE", 3, None)],
    )


def _failed(
    reason: str = "yfinance down", trigger: str = "scheduled", **options: bool
) -> RunFailedV1:
    return RunFailedV1(
        run_id=None if trigger == "rescore" else 1,
        trigger=trigger,  # type: ignore[arg-type]
        options=RunOptionsV1(**options),
        stage="market-data",
        reason=reason,
        detail="Traceback ...\nRuntimeError: <b>yfinance down</b>",
    )


def _publish(setup: Setup, data: ScoringRunCompletedV1 | RunFailedV1) -> Envelope[Any]:
    if isinstance(data, ScoringRunCompletedV1):
        env: Envelope[Any] = new_envelope(
            SCORING_RUN_COMPLETED, data, source="va/test", correlationid="1"
        )
    else:
        env = new_envelope(RUN_FAILED, data, source="va/test", correlationid="1")
    setup.bus.publish(env)
    return env


class TestReport:
    def test_report_is_stored_sent_pinged_and_announced(self, setup):
        completed = _publish(setup, _completed())
        run_id, scoring_run_id, report = setup.store.reports[0]
        assert (run_id, scoring_run_id) == (1, 20)
        assert "[partial 2/3]" in report.subject
        assert "9.9.9" in report.html
        assert "Neu AG (NEU.DE, MDAX)" in report.html
        assert report.csv_filename == "value_ranking_20261017.csv"

        mail = setup.sender.sent[0]
        assert (mail["subject"], mail["html"]) == (report.subject, report.html)
        assert mail["attachment"] == (report.csv_filename, report.csv_bytes)
        assert setup.heartbeat.pings == [(True, "scored 2/3")]
        assert setup.kinds() == [("mail", "report", True), ("healthcheck", "ping_ok", True)]
        mail_delivery, ping_delivery = setup.store.deliveries
        assert (mail_delivery["report_id"], mail_delivery["recipient"]) == (30, "r@example.com")
        assert ping_delivery["recipient"] == "hc-ping.com"

        sent = setup.seen[0]
        assert sent.type == REPORT_SENT.type
        assert (sent.data.run_id, sent.data.report_id, sent.data.dry_run) == (1, 30, False)
        assert sent.data.subject == report.subject
        assert sent.causationid == completed.id

    def test_dry_run_writes_preview_without_mail_and_ping(self, setup, tmp_path):
        _publish(setup, _completed(dry_run=True))
        assert setup.sender.sent == []
        assert setup.heartbeat.pings == []
        assert setup.store.deliveries == []
        assert len(setup.store.reports) == 1
        assert "Value-Screening" in (tmp_path / "data" / "preview_latest.html").read_text(
            encoding="utf-8"
        )
        assert (tmp_path / "data" / "preview_value_ranking_20261017.csv").exists()
        assert setup.seen[0].data.dry_run is True

    def test_without_notify_no_mail(self, setup):
        _publish(setup, _completed(notify=False))
        assert setup.sender.sent == []
        assert setup.seen[0].type == REPORT_SENT.type

    def test_manual_run_sends_but_does_not_ping(self, setup):
        _publish(setup, _completed(trigger="manual"))
        assert len(setup.sender.sent) == 1
        assert setup.heartbeat.pings == []

    def test_rescore_triggers_nothing(self, setup):
        _publish(setup, _completed(run_id=None, trigger="rescore"))
        assert setup.store.reports == []
        assert setup.sender.sent == []
        assert setup.seen == []

    def test_unconfigured_heartbeat_is_not_recorded(self, tmp_path):
        setup = Setup(tmp_path, heartbeat=FakeHeartbeat(result=None))
        _publish(setup, _completed())
        assert setup.kinds() == [("mail", "report", True)]

    def test_mail_failure_is_recorded_and_fails_the_run(self, tmp_path):
        setup = Setup(tmp_path, sender=FakeSender(error=OSError("smtp down")))
        _publish(setup, _completed())
        report_delivery = setup.store.deliveries[0]
        assert (report_delivery["kind"], report_delivery["success"]) == ("report", False)
        assert "smtp down" in report_delivery["error"]
        failed = [e for e in setup.seen if e.type == RUN_FAILED.type]
        assert [(e.data.stage, e.data.reason) for e in failed] == [("notification", "smtp down")]
        assert not [e for e in setup.seen if e.type == REPORT_SENT.type]
        # ... und daraufhin wie jeder Fehlschlag: Ping /fail und Fehlermail (scheitert hier auch)
        assert setup.heartbeat.pings[-1] == (False, "smtp down")
        assert setup.sender.sent[-1]["subject"] == ERROR_SUBJECT
        assert ("mail", "error", False) in setup.kinds()

    def test_unstorable_report_fails_the_run(self, tmp_path):
        setup = Setup(tmp_path, store=FakeStore(fail_report=True))
        _publish(setup, _completed())
        assert [e.data.stage for e in setup.seen] == ["notification"]
        assert [m["subject"] for m in setup.sender.sent] == [ERROR_SUBJECT]


class TestFailure:
    def test_failure_pings_fail_and_sends_the_error_mail(self, setup):
        _publish(setup, _failed())
        assert setup.heartbeat.pings == [(False, "yfinance down")]
        mail = setup.sender.sent[0]
        assert mail["subject"] == ERROR_SUBJECT
        assert "&lt;b&gt;yfinance down&lt;/b&gt;" in mail["html"]
        assert mail["attachment"] is None
        assert setup.kinds() == [("healthcheck", "ping_fail", True), ("mail", "error", True)]
        error_delivery = setup.store.deliveries[1]
        assert (error_delivery["run_id"], error_delivery["report_id"]) == (1, None)

    def test_no_data_pings_fail_without_mail(self, setup):
        _publish(setup, _failed(reason="no_data"))
        assert setup.heartbeat.pings == [(False, "no scoreable data")]
        assert setup.sender.sent == []

    def test_dry_run_failure_pings_but_sends_no_mail(self, setup):
        _publish(setup, _failed(dry_run=True))
        assert setup.heartbeat.pings == [(False, "yfinance down")]
        assert setup.sender.sent == []

    def test_without_notify_no_error_mail(self, setup):
        _publish(setup, _failed(notify=False))
        assert setup.sender.sent == []

    def test_manual_failure_is_not_pinged(self, setup):
        _publish(setup, _failed(trigger="manual"))
        assert setup.heartbeat.pings == []
        assert len(setup.sender.sent) == 1

    def test_failed_rescore_triggers_nothing(self, setup):
        _publish(setup, _failed(trigger="rescore"))
        assert setup.heartbeat.pings == []
        assert setup.sender.sent == []

    def test_error_mail_that_fails_is_recorded(self, tmp_path):
        setup = Setup(tmp_path, sender=FakeSender(error=OSError("smtp down")))
        _publish(setup, _failed())
        error_delivery = setup.store.deliveries[-1]
        assert (error_delivery["kind"], error_delivery["success"]) == ("error", False)
        assert "smtp down" in error_delivery["error"]


class TestFailureWithoutRun:
    """Datenbank nicht erreichbar: Es gibt keinen Run, also nichts zu speichern."""

    def test_pings_and_mails_without_recording(self, setup):
        notify_failure_without_run(
            setup.sender,
            setup.heartbeat,
            "database unreachable",
            detail="Traceback ...",
            dry_run=False,
        )
        assert setup.heartbeat.pings == [(False, "database unreachable")]
        assert [m["subject"] for m in setup.sender.sent] == [ERROR_SUBJECT]
        assert setup.store.deliveries == []

    def test_dry_run_only_pings(self, setup):
        notify_failure_without_run(
            setup.sender, setup.heartbeat, "database unreachable", detail="x", dry_run=True
        )
        assert setup.heartbeat.pings == [(False, "database unreachable")]
        assert setup.sender.sent == []


def test_error_mail_escapes_the_traceback():
    body = error_mail_html("ValueError: <b>kaputt</b> & mehr")
    assert "&lt;b&gt;kaputt&lt;/b&gt; &amp; mehr" in body
    assert "<b>kaputt</b>" not in body
