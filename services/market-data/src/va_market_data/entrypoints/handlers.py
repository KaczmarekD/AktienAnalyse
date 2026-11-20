"""market-data am Bus: ``screening.run.requested`` -> ``marketdata.snapshot.completed``.

Jeder Fehler wird zu ``screening.run.failed`` (Stufe ``market-data``); der Handler selbst
wirft nicht, damit der Bus nicht den ganzen Abruf wiederholt.

Seit D2.2 ruft er nach dem Referenzuniversum die Aktien der Abdeckung ab und schickt sie in
``covered[]``. Ein Fehler dort kostet nur die Abdeckung, nicht den Lauf.

Seit D2.4 frischt er danach die Stammdaten der Abdeckung auf und schickt sie vor
``snapshot.completed`` als ``marketdata.securities.updated``, hoechstens 50 Wertpapiere je Event.
Auch ein Fehler dort kostet nur diese Events.
"""

from __future__ import annotations

import logging
import math
import traceback
from collections.abc import Callable
from datetime import date
from typing import TYPE_CHECKING

import pandas as pd

from va_contracts.events.v1 import (
    FETCH_PROGRESSED,
    PRICES_COMPLETED,
    PRICES_REQUESTED,
    RUN_FAILED,
    RUN_REQUESTED,
    SECURITIES_UPDATED,
    SNAPSHOT_COMPLETED,
    DailyCloseV1,
    FetchProgressedV1,
    FundamentalsV1,
    FxDailyV1,
    PricesCompletedV1,
    RunFailedV1,
    SecuritiesUpdatedV1,
    SnapshotCompletedV1,
    UniverseInfoV1,
    UniverseMemberV1,
)
from va_platform.bus import follow_up

from ..application.coverage import Covered, plan_coverage, take_coverage
from ..application.fetch import success_share
from ..application.snapshot import take_snapshot
from .mapping import security_v1

if TYPE_CHECKING:
    from va_contracts import Envelope
    from va_contracts.events.v1 import PricesRequestedV1, ScreeningRunRequestedV1
    from va_platform.bus import EventBus

    from ..application.coverage import CoverageStore
    from ..application.ports import Fetch, SnapshotStore
    from ..application.prices import PricesResult
    from ..application.securities import RefreshResult
    from ..domain.fundamentals import Fundamentals
    from ..domain.universe import Ticker, Universe

log = logging.getLogger(__name__)

CONSUMER = "market-data"
SOURCE = "va/market-data"
# D2.4: Ein ETF braucht im Event rund 4 KB; 50 bleiben weit unter 1 MB, der Grenze von NATS
SECURITIES_PER_EVENT = 50


def securities_updated(result: RefreshResult, as_of: date) -> list[SecuritiesUpdatedV1]:
    """Die Stammdaten eines Laufs in Events zu hoechstens ``SECURITIES_PER_EVENT``;
    ``missing`` im ersten. Ohne beides kein Event."""
    securities = [security_v1(resolved) for resolved in result.securities]
    chunks = [
        securities[start : start + SECURITIES_PER_EVENT]
        for start in range(0, len(securities), SECURITIES_PER_EVENT)
    ] or ([[]] if result.missing else [])
    return [
        SecuritiesUpdatedV1(
            as_of=as_of, securities=chunk, missing=list(result.missing) if i == 0 else []
        )
        for i, chunk in enumerate(chunks)
    ]


class RunRequestedHandler:
    def __init__(
        self,
        bus: EventBus,
        *,
        load_universe: Callable[[], Universe],
        store: SnapshotStore,
        fetch: Fetch,
        coverage: CoverageStore | None = None,
        securities: Callable[[], RefreshResult] | None = None,
        dax_only: bool = False,
        today: Callable[[], date] = date.today,
    ) -> None:
        self._bus = bus
        self._load_universe = load_universe
        self._store = store
        self._fetch = fetch
        self._coverage = coverage
        self._securities = securities
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
            # D2.2: vorab, damit der Fortschritt Universum und Abdeckung zusammen zaehlt; gegen das
            # volle Universum, auch bei DAX_ONLY
            planned = (
                [] if self._coverage is None else plan_coverage(self._coverage, universe.tickers)
            )
            progress = self._progress(env, len(tickers) + len(planned))
            snapshot = take_snapshot(
                tickers,
                source=universe.source,
                as_of=universe.as_of,
                store=self._store,
                fetch=self._fetch,
                today=today,
                force_refresh=request.options.force_refresh,
                on_result=progress,
            )
            covered = (
                Covered(pd.DataFrame())
                if self._coverage is None
                else take_coverage(
                    fetch_run_id=snapshot.fetch_run_id,
                    universe=tickers,
                    store=self._coverage,
                    fetch=self._fetch,
                    reused=snapshot.reused,
                    tickers=planned,
                    on_result=progress,
                )
            )
            covered_rows = covered.frame.to_dict("records")
            symbols = [
                str(s) for frame in (snapshot.frame, covered.frame) for s in frame.get("symbol", [])
            ]
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
                # P4.9: fuer die Titelseite im web-api, das keine Tabellen von market-data liest
                isins={t.symbol: t.isin for t in tickers if t.isin} | covered.isins,
                # P5.3: scoring liest market_data.instrument nicht mehr
                instrument_ids=dict(self._store.instrument_ids(symbols)),
                covered=[FundamentalsV1.from_flat(row) for row in covered_rows],
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
        for updated in self._refresh_securities(today):
            self._bus.publish(follow_up(env, SECURITIES_UPDATED, updated, source=SOURCE))
        self._bus.publish(follow_up(env, SNAPSHOT_COMPLETED, completed, source=SOURCE))

    def _refresh_securities(self, today: date) -> list[SecuritiesUpdatedV1]:
        """D2.4: Stammdaten der Abdeckung; ein Fehler kostet nur diese Events (WP-07)."""
        if self._securities is None:
            return []
        try:
            return securities_updated(self._securities(), today)
        except Exception:
            log.warning("Stammdaten nicht aufgefrischt - der Lauf geht weiter", exc_info=True)
            return []

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


class PricesRequestedHandler:
    """D2.3: ``marketdata.prices.requested`` -> Tageskurse der Abdeckung -> ``prices.completed``.

    ``collect`` holt und speichert die Kurse fuer den Handelstag (``collect_prices`` mit den
    Adaptern, verdrahtet in ``entrypoints.service``). Wirft er, stellt der Bus erneut zu; einen Run
    gibt es hier nicht.
    """

    def __init__(self, bus: EventBus, *, collect: Callable[[date], PricesResult]) -> None:
        self._bus = bus
        self._collect = collect

    def subscribe(self) -> None:
        self._bus.subscribe(PRICES_REQUESTED, CONSUMER, self)

    def __call__(self, env: Envelope[PricesRequestedV1]) -> None:
        result = self._collect(env.data.trade_date)
        completed = PricesCompletedV1(
            price_run_id=result.price_run_id,
            trade_date=result.trade_date,
            closes=[
                DailyCloseV1(
                    isin=c.isin,
                    symbol=c.symbol,
                    trade_date=c.trade_date,
                    close=c.close,
                    currency=c.currency,
                    percent_of_par=c.percent_of_par,
                )
                for c in result.closes
            ],
            fx=[
                FxDailyV1(currency=f.currency, trade_date=f.trade_date, rate_to_eur=f.rate_to_eur)
                for f in result.fx
            ],
            missing=result.missing,
            price_run_ids=result.price_run_ids or [result.price_run_id],
        )
        self._bus.publish(follow_up(env, PRICES_COMPLETED, completed, source=SOURCE))
