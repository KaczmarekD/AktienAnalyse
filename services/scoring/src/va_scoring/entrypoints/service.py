"""scoring als eigener Service (P5.1a): ``python -m va_scoring``.

Haengt den Handler fuer ``marketdata.snapshot.completed`` an den ``ReliableBus`` und beantwortet
Faktoren, Vorschau und Profil-Befehle per Request/Reply (``rpc``). Die ENV-Werte sind nur
Startwerte fuer das Profil "Standard" (ADR-0009). Batch und Worker nutzen dieselben Funktionen.
"""

from __future__ import annotations

from datetime import timedelta
from functools import partial
from importlib.metadata import version as package_version
from typing import TYPE_CHECKING

from va_platform.messaging import ReliableBus
from va_platform.service import service_main

from ..adapters.postgres.models import ScoringInbox, ScoringOutbox
from ..adapters.postgres.store import PostgresScoringStore
from ..application.profiles import StoredProfile
from ..domain.profile import profile_params
from ..domain.scoring import ScoringConfig
from . import rpc
from .handlers import SnapshotCompletedHandler
from .settings import ScoringSettings

if TYPE_CHECKING:
    from sqlalchemy import Engine

    from va_platform.bus import EventBus
    from va_platform.nats import NatsBus

    from ..application.ports import ScoringAdapter

QUEUE = "scoring"  # Queue-Gruppe fuer Request/Reply


def scoring_config(settings: ScoringSettings) -> ScoringConfig:
    """Die Bewertung aus den Settings - Startwerte fuer "Standard", auch fuer die Regression."""
    return ScoringConfig(
        min_market_cap=settings.min_market_cap,
        value_weight=settings.value_weight,
        quality_weight=settings.quality_weight,
    )


def wire(bus: EventBus, store: ScoringAdapter, settings: ScoringSettings) -> None:
    start_params = profile_params(scoring_config(settings))
    SnapshotCompletedHandler(
        bus, store=store, profile=StoredProfile(store, start_params)
    ).subscribe()


def reliable(bus: EventBus, engine: Engine, settings: ScoringSettings) -> EventBus:
    """Jedes Event einmal, Folge-Events ueber die Outbox (P4.3b)."""
    max_age = timedelta(minutes=settings.run_timeout_minutes)
    return ReliableBus(bus, engine, inbox=ScoringInbox, outbox=ScoringOutbox, max_age=max_age)


def serve(bus: NatsBus, engine: Engine) -> None:
    """Request/Reply von scoring; Profil-Events gehen direkt an den Bus."""
    for spec, handler in rpc.handlers(engine, notify=bus.publish).items():
        bus.serve(spec, handler, queue=QUEUE)


def setup(
    bus: NatsBus,
    engine: Engine,
    *,
    settings: ScoringSettings,
    store: ScoringAdapter | None = None,
) -> None:
    store = store or PostgresScoringStore(engine, app_version=package_version("va-scoring"))
    wire(reliable(bus, engine, settings), store, settings)
    serve(bus, engine)


def main() -> int:
    return service_main(
        "scoring",
        ScoringSettings,  # type: ignore[arg-type] - Pflichtfelder kommen aus der Umgebung
        lambda settings: partial(setup, settings=settings),  # type: ignore[arg-type]
    )
