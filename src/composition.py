"""Composition Root des Batches: Adapter bauen, Handler der Module an den Bus haengen (P1.8).

``Adapters`` buendelt alles, was nach aussen geht. Tests tauschen einzelne Teile per
``dataclasses.replace`` oder bauen eigene; die Handler sehen nur ihre Ports.

Seit P5.1a baut jeder Service seine Adapter und Handler selbst (``va_<service>.entrypoints
.service``); hier werden dieselben Funktionen mit den Settings des Batches aufgerufen. So laeuft
die Kette im Batch, im Worker und in getrennten Services mit demselben Code.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from va_market_data.adapters.postgres.models import MarketDataInbox, MarketDataOutbox
from va_market_data.entrypoints import service as market_data_service
from va_notification.adapters.postgres.models import ReportingInbox, ReportingOutbox
from va_notification.entrypoints import service as notification_service
from va_notification.entrypoints.service import alert_channels, smtp_config
from va_platform.db import create_db_engine
from va_platform.messaging import ReliableBus
from va_scoring.adapters.postgres.models import ScoringInbox, ScoringOutbox
from va_scoring.adapters.postgres.store import PostgresScoringStore
from va_scoring.application.ports import ScoringAdapter
from va_scoring.entrypoints import service as scoring_service
from va_scoring.entrypoints.service import scoring_config

from . import __version__
from .db.recorder import BatchRecorder

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy import Engine

    from va_market_data.application.ports import Fetch, SnapshotStore
    from va_market_data.domain.universe import Universe, UniverseConfig
    from va_notification.application.ports import Heartbeat, ReportSender, ReportStore
    from va_platform.bus import EventBus
    from va_platform.messaging import InboxMixin, OutboxMixin

    from .config import Settings
    from .db.log_handler import LogEntry

__all__ = [
    "DEFAULT_FALLBACK_CSV",
    "Adapters",
    "BatchStore",
    "Messaging",
    "ScoringAdapter",
    "alert_channels",
    "build_adapters",
    "load_universe",
    "scoring_config",
    "smtp_config",
    "wire",
]

# Von Hand gepflegt, liegt im Repo (im Image unter /app/data). Das Paket market-data liegt
# installiert in site-packages und kennt den Pfad deshalb nicht selbst.
DEFAULT_FALLBACK_CSV = Path(__file__).resolve().parent.parent / "data" / "dax_mdax_fallback.csv"


class BatchStore(Protocol):
    """Schema ``batch``: Start, Abschluss und Log-Zeilen eines Laufs."""

    def start_run(
        self,
        *,
        kind: str,
        dry_run: bool,
        force_refresh: bool,
        universe_mode: str | None,
        settings: dict[str, Any] | None,
    ) -> int: ...

    def finish_run(self, run_id: int, **kwargs: Any) -> None: ...

    def record_logs(self, run_id: int, entries: Sequence[LogEntry]) -> None: ...


@dataclass(frozen=True)
class Messaging:
    """Inbox und Outbox der Services (P4.3b): je Service ein ``ReliableBus``.

    ``max_age``: aelter ist ein Event der Rest eines abgebrochenen Laufs (``RUN_TIMEOUT_MINUTES``).
    """

    engine: Engine
    max_age: timedelta

    def wrap(
        self, bus: EventBus, *, inbox: type[InboxMixin], outbox: type[OutboxMixin]
    ) -> EventBus:
        return ReliableBus(bus, self.engine, inbox=inbox, outbox=outbox, max_age=self.max_age)


@dataclass(frozen=True)
class Adapters:
    batch: BatchStore
    market_data: SnapshotStore
    scoring: ScoringAdapter
    reporting: ReportStore
    load_universe: Callable[[], Universe]
    fetch: Fetch
    sender: ReportSender
    heartbeat: Heartbeat
    clock: Callable[[], datetime] = field(default=datetime.now)
    # Ohne (Tests mit Fakes) haengen die Handler direkt am Bus
    messaging: Messaging | None = None


def _fallback_csv(settings: Settings) -> Path:
    """Die CSV im Repo, ausser ``FALLBACK_CSV`` ist ausdruecklich gesetzt (Tests wechseln cwd)."""
    return (
        settings.fallback_csv
        if "fallback_csv" in settings.model_fields_set
        else (DEFAULT_FALLBACK_CSV)
    )


def build_adapters(settings: Settings) -> Adapters:
    """Die echten Adapter: PostgreSQL, Yahoo, iShares/Deka/CSV, SMTP, Healthchecks.io.

    Mit ``REPLAY_SOURCE`` (U5) kommen Universum und Fundamentaldaten aus einer Replay-Fixture
    statt aus dem Netz. Die Engine verbindet sich erst beim ersten Zugriff - ein DB-Ausfall
    zeigt sich also beim Start des Laufs, nicht hier.
    """
    engine = create_db_engine(settings.database_url.get_secret_value())
    market = market_data_service.build_adapters(
        settings, engine, fallback_csv=_fallback_csv(settings)
    )
    reporting = notification_service.build_adapters(settings, engine)
    return Adapters(
        batch=BatchRecorder(engine),
        market_data=market.store,
        scoring=PostgresScoringStore(engine, app_version=__version__),
        reporting=reporting.store,
        load_universe=market.load_universe,
        fetch=market.fetch,
        sender=reporting.sender,
        heartbeat=reporting.heartbeat,
        messaging=Messaging(engine, timedelta(minutes=settings.run_timeout_minutes)),
    )


def load_universe(
    cfg: UniverseConfig | None = None,
    fallback_csv: Path | None = None,
    force_fallback: bool = False,
    today: date | None = None,
) -> Universe:
    """DAX + MDAX aus der ersten gueltigen Quelle: iShares -> Deka -> Fallback-CSV."""
    return market_data_service.live_universe(
        fallback_csv or DEFAULT_FALLBACK_CSV, cfg, force_fallback=force_fallback, today=today
    )


def wire(bus: EventBus, adapters: Adapters, settings: Settings, *, version: str) -> None:
    """Haengt die Handler aller Module an den Bus. Reihenfolge = Reihenfolge der Kette.

    Mit ``adapters.messaging`` (P4.3b) bekommt jeder Service seinen ``ReliableBus``: Er
    verarbeitet ein Event einmal und schickt Folge-Events ueber seine Outbox.
    """

    def service_bus(inbox: type[InboxMixin], outbox: type[OutboxMixin]) -> EventBus:
        if adapters.messaging is None:
            return bus
        return adapters.messaging.wrap(bus, inbox=inbox, outbox=outbox)

    market_data_service.wire(
        service_bus(MarketDataInbox, MarketDataOutbox),
        market_data_service.MarketDataAdapters(
            store=adapters.market_data, load_universe=adapters.load_universe, fetch=adapters.fetch
        ),
        settings,
    )
    # Die ENV-Werte sind nur Startwerte fuer das Profil "Standard" (ADR-0009, P2b.3)
    scoring_service.wire(service_bus(ScoringInbox, ScoringOutbox), adapters.scoring, settings)
    notification_service.wire(
        service_bus(ReportingInbox, ReportingOutbox),
        notification_service.NotificationAdapters(
            store=adapters.reporting,
            sender=adapters.sender,
            heartbeat=adapters.heartbeat,
            clock=adapters.clock,
        ),
        settings,
        version=version,
    )
