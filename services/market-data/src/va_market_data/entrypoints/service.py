"""market-data als eigener Service (P5.1a): ``python -m va_market_data``.

Baut die Adapter aus den eigenen Settings (Datenbank, iShares/Deka/CSV oder Replay, Yahoo) und
haengt den Handler fuer ``screening.run.requested`` an den ``ReliableBus``. Der Batch und der
Worker nutzen dieselben Funktionen (``src/composition.py``). Seit D2.1 beantwortet der Dienst
Suche und Aufloesung von Wertpapieren per Request/Reply (``rpc``).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from functools import cached_property, partial
from typing import TYPE_CHECKING, Any

from va_platform.messaging import ReliableBus
from va_platform.service import service_main

from ..adapters.csv_universe import load_fallback
from ..adapters.deka import DekaSource
from ..adapters.firds import FirdsSource
from ..adapters.ishares import IsharesSource
from ..adapters.openfigi import OpenFigiLookup, resolve_isins_openfigi
from ..adapters.postgres.models import MarketDataInbox, MarketDataOutbox
from ..adapters.postgres.securities import PostgresSecurityCatalog
from ..adapters.postgres.store import PostgresSnapshotStore
from ..adapters.replay import PROVIDER as REPLAY_PROVIDER
from ..adapters.replay import ReplayFundamentals, load_replay_rows, replay_universe
from ..adapters.yahoo import (
    PROVIDER,
    FetcherConfig,
    YahooFundamentals,
    YahooTextSearch,
    provider_version,
)
from ..application.fetch import fetch_all
from ..application.securities import SecurityService
from ..application.universe import load_universe as load_universe_chain
from ..domain.universe import UniverseConfig
from . import rpc
from .handlers import RunRequestedHandler
from .settings import MarketDataSettings

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping
    from pathlib import Path

    import pandas as pd
    from sqlalchemy import Engine

    from va_platform.bus import EventBus
    from va_platform.nats import NatsBus

    from ..application.coverage import CoverageStore
    from ..application.ports import Fetch, FundamentalsProvider, SnapshotStore
    from ..domain.fundamentals import Fundamentals
    from ..domain.history import HistoryState
    from ..domain.universe import Ticker, Universe


@dataclass(frozen=True)
class MarketDataAdapters:
    store: SnapshotStore
    load_universe: Callable[[], Universe]
    fetch: Fetch
    # D2.2: Abdeckung im Wochenlauf; ohne (Replay, Tests) nur das Referenzuniversum
    coverage: CoverageStore | None = None


def live_universe(
    fallback_csv: Path,
    cfg: UniverseConfig | None = None,
    *,
    force_fallback: bool = False,
    today: date | None = None,
) -> Universe:
    """DAX + MDAX aus der ersten gueltigen Quelle: iShares -> Deka -> Fallback-CSV."""
    return load_universe_chain(
        [IsharesSource(), DekaSource(resolver=resolve_isins_openfigi)],
        load_fallback(fallback_csv),
        cfg or UniverseConfig(),
        today or date.today(),
        force_fallback=force_fallback,
    )


class _ReplayFile:
    """Eine Replay-Fixture als Quelle (U5). Gelesen erst im Lauf: Ein Fehler in der Datei
    laesst dann den Lauf scheitern, statt wie eine ausgefallene Datenbank auszusehen."""

    def __init__(self, path: Path, fallback_csv: Path) -> None:
        self._path = path
        self._fallback_csv = fallback_csv

    @cached_property
    def _rows(self) -> list[dict[str, Any]]:
        return load_replay_rows(self._path)

    def universe(self) -> Universe:
        return replay_universe(self._rows, load_fallback(self._fallback_csv))

    def fundamentals(self) -> FundamentalsProvider:
        return ReplayFundamentals(self._rows)


def build_adapters(
    settings: MarketDataSettings, engine: Engine, *, fallback_csv: Path | None = None
) -> MarketDataAdapters:
    """Die echten Adapter; mit ``REPLAY_SOURCE`` (U5) kommen Universum und Daten aus der Datei."""
    csv = fallback_csv or settings.fallback_csv
    fetcher = FetcherConfig(default_tax_rate=settings.default_tax_rate)
    universe: Callable[[], Universe]
    if settings.replay_source is None:
        provider_name, version = PROVIDER, provider_version()
        universe, sleep_between = partial(live_universe, csv), fetcher.sleep_between
        provider: Callable[[], FundamentalsProvider] = partial(YahooFundamentals, fetcher)
    else:
        replay = _ReplayFile(settings.replay_source, csv)
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

    store = PostgresSnapshotStore(engine, provider=provider_name, provider_version=version)
    return MarketDataAdapters(
        store=store,
        load_universe=universe,
        fetch=fetch,
        # Eine Replay-Datei kennt nur das Universum: Abdeckung nur im echten Abruf
        coverage=store if settings.replay_source is None else None,
    )


def wire(bus: EventBus, adapters: MarketDataAdapters, settings: MarketDataSettings) -> None:
    RunRequestedHandler(
        bus,
        load_universe=adapters.load_universe,
        store=adapters.store,
        fetch=adapters.fetch,
        coverage=adapters.coverage,
        dax_only=settings.universe == "DAX_ONLY",
    ).subscribe()


def reliable(bus: EventBus, engine: Engine, settings: MarketDataSettings) -> EventBus:
    """Jedes Event einmal, Folge-Events ueber die Outbox (P4.3b)."""
    max_age = timedelta(minutes=settings.run_timeout_minutes)
    return ReliableBus(bus, engine, inbox=MarketDataInbox, outbox=MarketDataOutbox, max_age=max_age)


QUEUE = "market-data"  # Queue-Gruppe fuer Request/Reply (D2.1)


def securities(engine: Engine) -> SecurityService:
    """Suche und Aufloesung (D2.1): eigene Wertpapiere, OpenFIGI, Yahoo, ESMA FIRDS."""
    return SecurityService(
        catalog=PostgresSecurityCatalog(engine),
        lookup=OpenFigiLookup(),
        text=YahooTextSearch(),
        master=FirdsSource(),
    )


def serve(bus: NatsBus, service: rpc.Securities) -> None:
    for spec, handler in rpc.handlers(service).items():
        bus.serve(spec, handler, queue=QUEUE)


def setup(
    bus: NatsBus,
    engine: Engine,
    *,
    settings: MarketDataSettings,
    adapters: MarketDataAdapters | None = None,
    securities_service: rpc.Securities | None = None,
) -> None:
    wire(reliable(bus, engine, settings), adapters or build_adapters(settings, engine), settings)
    serve(bus, securities_service or securities(engine))


def main() -> int:
    return service_main(
        "market-data",
        MarketDataSettings,  # type: ignore[arg-type] - Pflichtfelder kommen aus der Umgebung
        lambda settings: partial(setup, settings=settings),  # type: ignore[arg-type]
    )
