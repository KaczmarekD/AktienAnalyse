"""market-data am Bus: ``screening.run.requested`` -> ``marketdata.snapshot.completed``.

Jeder Fehler wird zu ``screening.run.failed`` (Stufe ``market-data``); der Handler selbst
wirft nicht, damit der Bus nicht den ganzen Abruf wiederholt.
"""

from __future__ import annotations

import logging
import math
import traceback
from collections.abc import Callable
from datetime import date
from typing import TYPE_CHECKING

from va_contracts.events.v1 import (
    FETCH_PROGRESSED,
    RUN_FAILED,
    RUN_REQUESTED,
    SNAPSHOT_COMPLETED,
    FetchProgressedV1,
    FundamentalsV1,
    RunFailedV1,
    SnapshotCompletedV1,
    UniverseInfoV1,
    UniverseMemberV1,
)
from va_platform.bus import follow_up

from ..application.fetch import success_share
from ..application.snapshot import take_snapshot

if TYPE_CHECKING:
    from va_contracts import Envelope
    from va_contracts.events.v1 import ScreeningRunRequestedV1
    from va_platform.bus import EventBus

    from ..application.ports import Fetch, SnapshotStore
    from ..domain.fundamentals import Fundamentals
    from ..domain.universe import Ticker, Universe

log = logging.getLogger(__name__)

CONSUMER = "market-data"
SOURCE = "va/market-data"


class RunRequestedHandler:
    def __init__(
        self,
        bus: EventBus,
        *,
        load_universe: Callable[[], Universe],
        store: SnapshotStore,
        fetch: Fetch,
        dax_only: bool = False,
        today: Callable[[], date] = date.today,
    ) -> None:
        self._bus = bus
        self._load_universe = load_universe
        self._store = store
        self._fetch = fetch
        self._dax_only = dax_only
        self._today = today

    def subscribe(self) -> None:
        self._bus.subscribe(RUN_REQUESTED, CONSUMER, self)

    def __call__(self, env: Envelope[ScreeningRunRequestedV1]) -> None:
        request = env.data
        try:
            universe = self._load_universe()
            tickers = universe.tickers
            if self._dax_only:
                tickers = [t for t in tickers if t.index == "DAX"]
            today = self._today()
            snapshot = take_snapshot(
                tickers,
                source=universe.source,
                as_of=universe.as_of,
                store=self._store,
                fetch=self._fetch,
                today=today,
                force_refresh=request.options.force_refresh,
                on_result=self._progress(env, len(tickers)),
            )
            completed = SnapshotCompletedV1(
                run_id=request.run_id,
                trigger=request.trigger,
                options=request.options,
                fetch_run_id=snapshot.fetch_run_id,
                as_of=today,
                success_share=success_share(snapshot.frame),
                universe=UniverseInfoV1(
                    source=universe.source,
                    as_of=universe.as_of,
                    size=len(tickers),
                    added=[_member(t) for t in universe.added],
                    removed=[_member(t) for t in universe.removed],
                ),
                fundamentals=[
                    FundamentalsV1.from_flat(row) for row in snapshot.frame.to_dict("records")
                ],
            )
        except Exception as e:
            log.exception("Abruf fehlgeschlagen")
            failed = RunFailedV1(
                run_id=request.run_id,
                trigger=request.trigger,
                options=request.options,
                stage="market-data",
                reason=str(e) or type(e).__name__,
                detail=traceback.format_exc(),
            )
            self._bus.publish(follow_up(env, RUN_FAILED, failed, source=SOURCE))
            return
        self._bus.publish(follow_up(env, SNAPSHOT_COMPLETED, completed, source=SOURCE))

    def _progress(
        self, env: Envelope[ScreeningRunRequestedV1], total: int
    ) -> Callable[[Fundamentals], None]:
        done = 0

        def report(fund: Fundamentals) -> None:
            nonlocal done
            done += 1
            progress = FetchProgressedV1(
                run_id=env.data.run_id,
                done=min(done, total),
                total=total,
                symbol=fund.symbol,
                ok=_has_value(fund.market.market_cap),
            )
            self._bus.publish(follow_up(env, FETCH_PROGRESSED, progress, source=SOURCE))

        return report


def _member(t: Ticker) -> UniverseMemberV1:
    return UniverseMemberV1(symbol=t.symbol, name=t.name, index=t.index)


def _has_value(value: float | None) -> bool:
    return value is not None and not math.isnan(value)
