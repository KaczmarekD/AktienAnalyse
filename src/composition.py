"""Composition Root des Batches: Adapter bauen, Handler der Module an den Bus haengen (P1.8).

``Adapters`` buendelt alles, was nach aussen geht. Tests tauschen einzelne Teile per
``dataclasses.replace`` oder bauen eigene; die Handler sehen nur ihre Ports.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from functools import cached_property, partial
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from va_market_data.adapters.csv_universe import load_fallback
from va_market_data.adapters.deka import DekaSource
from va_market_data.adapters.ishares import IsharesSource
from va_market_data.adapters.openfigi import resolve_isins_openfigi
from va_market_data.adapters.postgres.store import PostgresSnapshotStore
from va_market_data.adapters.replay import PROVIDER as REPLAY_PROVIDER
from va_market_data.adapters.replay import ReplayFundamentals, replay_universe
from va_market_data.adapters.yahoo import (
    PROVIDER,
    FetcherConfig,
    YahooFundamentals,
    provider_version,
)
from va_market_data.application.fetch import fetch_all
from va_market_data.application.universe import load_universe as load_universe_chain
from va_market_data.domain.universe import UniverseConfig
from va_market_data.entrypoints.handlers import RunRequestedHandler
from va_notification.adapters.healthchecks import HealthchecksHeartbeat, ping_target
from va_notification.adapters.postgres.store import PostgresReportStore
from va_notification.adapters.smtp import SmtpConfig, SmtpSender
from va_notification.entrypoints.handlers import NotificationConfig, NotificationHandler
from va_platform.db import create_db_engine
from va_scoring.adapters.postgres.store import PostgresScoringStore
from va_scoring.domain.scoring import ScoringConfig
from va_scoring.entrypoints.handlers import SnapshotCompletedHandler

from . import __version__
from .db.recorder import BatchRecorder
from .regression.case import ReplayCase

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    import pandas as pd

    from va_market_data.application.ports import Fetch, FundamentalsProvider, SnapshotStore
    from va_market_data.domain.fundamentals import Fundamentals
    from va_market_data.domain.history import HistoryState
    from va_market_data.domain.universe import Ticker, Universe
    from va_notification.application.ports import Heartbeat, ReportSender, ReportStore
    from va_platform.bus import EventBus
    from va_scoring.application.ports import ScoringStore

    from .config import Settings
    from .db.log_handler import LogEntry


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
class Adapters:
    batch: BatchStore
    market_data: SnapshotStore
    scoring: ScoringStore
    reporting: ReportStore
    load_universe: Callable[[], Universe]
    fetch: Fetch
    sender: ReportSender
    heartbeat: Heartbeat
    clock: Callable[[], datetime] = field(default=datetime.now)


def build_adapters(settings: Settings) -> Adapters:
    """Die echten Adapter: PostgreSQL, Yahoo, iShares/Deka/CSV, SMTP, Healthchecks.io.

    Mit ``REPLAY_SOURCE`` (U5) kommen Universum und Fundamentaldaten aus einer Replay-Fixture
    statt aus dem Netz. Die Engine verbindet sich erst beim ersten Zugriff - ein DB-Ausfall
    zeigt sich also beim Start des Laufs, nicht hier.
    """
    engine = create_db_engine(settings.database_url.get_secret_value())
    fetcher = FetcherConfig(default_tax_rate=settings.default_tax_rate)
    sender, heartbeat = alert_channels(settings)

    universe: Callable[[], Universe]
    if settings.replay_source is None:
        provider_name, version = PROVIDER, provider_version()
        universe, sleep_between = load_universe, fetcher.sleep_between
        provider: Callable[[], FundamentalsProvider] = partial(YahooFundamentals, fetcher)
    else:
        replay = _ReplayFile(settings.replay_source)
        provider_name, version = REPLAY_PROVIDER, settings.replay_source.name
        universe, sleep_between = replay.universe, 0.0
        provider = replay.fundamentals

    def fetch(
        tickers: list[Ticker],
        *,
        on_result: Callable[[Fundamentals], None],
        history: Mapping[str, HistoryState],
    ) -> pd.DataFrame:
        return fetch_all(
            tickers,
            provider(),
            sleep_between=sleep_between,
            on_result=on_result,
            history=history,
        )

    return Adapters(
        batch=BatchRecorder(engine),
        market_data=PostgresSnapshotStore(engine, provider=provider_name, provider_version=version),
        scoring=PostgresScoringStore(engine, app_version=__version__),
        reporting=PostgresReportStore(engine),
        load_universe=universe,
        fetch=fetch,
        sender=sender,
        heartbeat=heartbeat,
    )


class _ReplayFile:
    """Eine Replay-Fixture als Quelle (U5). Gelesen erst im Lauf: Ein Fehler in der Datei
    laesst dann den Lauf scheitern, statt wie eine ausgefallene Datenbank auszusehen."""

    def __init__(self, path: Path) -> None:
        self._path = path

    @cached_property
    def _rows(self) -> list[dict[str, Any]]:
        case = ReplayCase.from_json(self._path.read_text(encoding="utf-8"))
        return [{str(k): v for k, v in row.items()} for row in case.snapshots.to_dict("records")]

    def universe(self) -> Universe:
        return replay_universe(self._rows, load_fallback(DEFAULT_FALLBACK_CSV))

    def fundamentals(self) -> FundamentalsProvider:
        return ReplayFundamentals(self._rows)


def load_universe(
    cfg: UniverseConfig | None = None,
    fallback_csv: Path | None = None,
    force_fallback: bool = False,
    today: date | None = None,
) -> Universe:
    """DAX + MDAX aus der ersten gueltigen Quelle: iShares -> Deka -> Fallback-CSV."""
    return load_universe_chain(
        [IsharesSource(), DekaSource(resolver=resolve_isins_openfigi)],
        load_fallback(fallback_csv or DEFAULT_FALLBACK_CSV),
        cfg or UniverseConfig(),
        today or date.today(),
        force_fallback=force_fallback,
    )


def smtp_config(settings: Settings) -> SmtpConfig:
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


def alert_channels(settings: Settings) -> tuple[ReportSender, Heartbeat]:
    """Mail und Healthcheck - auch fuer den Fall, dass die anderen Adapter nicht entstehen."""
    return SmtpSender(smtp_config(settings)), HealthchecksHeartbeat(settings.healthcheck_url)


def scoring_config(settings: Settings) -> ScoringConfig:
    """Die Bewertung aus den Settings - fuer den Batch und die Replay-Regression gleich."""
    return ScoringConfig(
        min_market_cap=settings.min_market_cap,
        value_weight=settings.value_weight,
        quality_weight=settings.quality_weight,
    )


def wire(bus: EventBus, adapters: Adapters, settings: Settings, *, version: str) -> None:
    """Haengt die Handler aller Module an den Bus. Reihenfolge = Reihenfolge der Kette."""
    RunRequestedHandler(
        bus,
        load_universe=adapters.load_universe,
        store=adapters.market_data,
        fetch=adapters.fetch,
        dax_only=settings.universe == "DAX_ONLY",
    ).subscribe()
    SnapshotCompletedHandler(
        bus, store=adapters.scoring, config=scoring_config(settings)
    ).subscribe()
    NotificationHandler(
        bus,
        sender=adapters.sender,
        heartbeat=adapters.heartbeat,
        store=adapters.reporting,
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
