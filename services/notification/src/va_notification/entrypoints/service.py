"""notification als eigener Service (P5.1a): ``python -m va_notification``.

Baut Mailversand, Healthcheck und Report-Speicher aus den eigenen Settings, haengt den Handler fuer
``scoring.run.completed`` und ``screening.run.failed`` an den ``ReliableBus`` und beantwortet
Report und CSV per Request/Reply (``rpc``). Batch und Worker nutzen dieselben Funktionen.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from functools import partial
from importlib.metadata import version as package_version
from typing import TYPE_CHECKING

from va_platform.messaging import ReliableBus
from va_platform.service import service_main

from ..adapters.healthchecks import HealthchecksHeartbeat, ping_target
from ..adapters.postgres.models import ReportingInbox, ReportingOutbox
from ..adapters.postgres.store import PostgresReportStore
from ..adapters.smtp import SmtpConfig, SmtpSender
from . import rpc
from .handlers import NotificationConfig, NotificationHandler
from .settings import NotificationSettings

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy import Engine

    from va_platform.bus import EventBus
    from va_platform.nats import NatsBus

    from ..application.ports import Heartbeat, ReportSender, ReportStore

QUEUE = "notification"  # Queue-Gruppe fuer Request/Reply


@dataclass(frozen=True)
class NotificationAdapters:
    store: ReportStore
    sender: ReportSender
    heartbeat: Heartbeat
    clock: Callable[[], datetime] = field(default=datetime.now)


def smtp_config(settings: NotificationSettings) -> SmtpConfig:
    return SmtpConfig(
        host=settings.smtp_host,
        port=settings.smtp_port,
        user=settings.smtp_user,
        password=settings.smtp_password.get_secret_value(),
        use_tls=settings.smtp_use_tls,
        plain=settings.smtp_plain,
        mail_from=settings.effective_mail_from,
        mail_to=str(settings.mail_to),
        subject_prefix=settings.mail_subject_prefix,
    )


def alert_channels(settings: NotificationSettings) -> tuple[ReportSender, Heartbeat]:
    """Mail und Healthcheck - auch fuer den Fall, dass die anderen Adapter nicht entstehen."""
    return SmtpSender(smtp_config(settings)), HealthchecksHeartbeat(settings.healthcheck_url)


def build_adapters(settings: NotificationSettings, engine: Engine) -> NotificationAdapters:
    sender, heartbeat = alert_channels(settings)
    return NotificationAdapters(
        store=PostgresReportStore(engine), sender=sender, heartbeat=heartbeat
    )


def wire(
    bus: EventBus,
    adapters: NotificationAdapters,
    settings: NotificationSettings,
    *,
    version: str,
) -> None:
    NotificationHandler(
        bus,
        sender=adapters.sender,
        heartbeat=adapters.heartbeat,
        store=adapters.store,
        config=NotificationConfig(
            top_n=settings.top_n,
            bottom_n=settings.bottom_n,
            version=version,
            recipient=str(settings.mail_to),
            preview_dir=settings.data_dir,
            heartbeat_target=ping_target(settings.healthcheck_url),
            clock=adapters.clock,
        ),
    ).subscribe()


def reliable(bus: EventBus, engine: Engine, settings: NotificationSettings) -> EventBus:
    """Jedes Event einmal, Folge-Events ueber die Outbox (P4.3b)."""
    max_age = timedelta(minutes=settings.run_timeout_minutes)
    return ReliableBus(bus, engine, inbox=ReportingInbox, outbox=ReportingOutbox, max_age=max_age)


def serve(bus: NatsBus, engine: Engine) -> None:
    for spec, handler in rpc.handlers(engine).items():
        bus.serve(spec, handler, queue=QUEUE)


def setup(
    bus: NatsBus,
    engine: Engine,
    *,
    settings: NotificationSettings,
    adapters: NotificationAdapters | None = None,
    version: str | None = None,
) -> None:
    wire(
        reliable(bus, engine, settings),
        adapters or build_adapters(settings, engine),
        settings,
        version=version or package_version("va-notification"),
    )
    serve(bus, engine)


def main() -> int:
    return service_main(
        "notification",
        NotificationSettings,  # type: ignore[arg-type] - Pflichtfelder kommen aus der Umgebung
        lambda settings: partial(setup, settings=settings),  # type: ignore[arg-type]
    )
