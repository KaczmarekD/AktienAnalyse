"""``marketdata.securities.updated`` im Wochenlauf (D2.4, WP-04, WP-07, WP-10).

Nach Universum und Abdeckung frischt der Wochenlauf die Stammdaten der Abdeckung auf und schickt
sie vor ``snapshot.completed``: hoechstens 50 Wertpapiere je Event, ETFs mit Fondsdaten, Gewichten
und den groessten Positionen, ohne die ganze Liste. Scheitert die Aktualisierung, laeuft der
Wochenlauf ohne sie weiter.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd
import pytest

from va_contracts import Envelope, new_envelope
from va_contracts.events.v1 import (
    RUN_REQUESTED,
    SECURITIES_UPDATED,
    SNAPSHOT_COMPLETED,
    RunOptionsV1,
    ScreeningRunRequestedV1,
)
from va_market_data.application.securities import RefreshResult, ResolvedSecurity
from va_market_data.domain.etf import EtfComposition, FundFacts, Holding
from va_market_data.domain.fundamentals import Fundamentals, Identity, MarketData
from va_market_data.domain.securities import BondTerms, Listing, SecurityMaster
from va_market_data.domain.universe import Ticker, Universe
from va_market_data.entrypoints.handlers import SECURITIES_PER_EVENT, RunRequestedHandler
from va_market_data.entrypoints.mapping import security_v1
from va_platform.bus import InProcessBus

TODAY = date(2026, 11, 21)
UNIVERSE = [Ticker("SAP.DE", "SAP SE", "DAX", "DE0007164600")]
WORLD = "IE00B4L5Y983"


def _holding(i: int) -> Holding:
    return Holding(f"Titel {i}", 10.0 - i * 0.1, ticker=f"T{i}", sector="IT", country="USA")


WORLD_ETF = EtfComposition(
    isin=WORLD,
    source="ishares",
    as_of=date(2026, 11, 19),
    complete=True,
    facts=FundFacts(
        name="iShares Core MSCI World UCITS ETF",
        ter=0.2,
        fund_size=142076.32,
        currency="USD",
        distribution="accumulating",
        provider="iShares",
    ),
    holdings=tuple(_holding(i) for i in range(30)),
    sectors={"IT": 70.0},
    countries={"USA": 70.0},
    asset_classes={"Aktien": 70.0},
)


def _resolved(isin: str, **kwargs: Any) -> ResolvedSecurity:
    listing = Listing("EUNL.DE", "EUNL", "GY", "EUR")
    return ResolvedSecurity(
        master=SecurityMaster(isin, kwargs.pop("name", "Fonds"), kwargs.pop("asset_class", "etf")),
        listings=(listing,),
        listing=listing,
        **kwargs,
    )


class FakeStore:
    def find_reusable_fetch(self, day, symbols):
        return None

    def start_fetch(self, tickers, source, as_of=None):
        return 10

    def history_state(self, symbols):
        return {}

    def record_fundamentals(self, fetch_run_id, fund):
        return None

    def finish_fetch(self, fetch_run_id, df):
        return None

    def load_snapshots(self, fetch_run_id, symbols):
        raise AssertionError  # kein Abruf des Tages zum Wiederverwenden

    def instrument_ids(self, symbols):
        return {s: i for i, s in enumerate(sorted(symbols), start=101)}


def _fetch(tickers, *, on_result, history):
    rows = []
    for t in tickers:
        fund = Fundamentals(
            identity=Identity(t.symbol, t.name, t.index), market=MarketData(market_cap=5e9)
        )
        on_result(fund)
        rows.append(fund.to_flat_dict())
    return pd.DataFrame(rows)


def _run(bus: InProcessBus, securities) -> list[Envelope[Any]]:
    seen: list[Envelope[Any]] = []
    bus.subscribe(SECURITIES_UPDATED, "probe-securities", seen.append)
    bus.subscribe(SNAPSHOT_COMPLETED, "probe-snapshot", seen.append)
    RunRequestedHandler(
        bus,
        load_universe=lambda: Universe(tickers=UNIVERSE, source="Replay"),
        store=FakeStore(),
        fetch=_fetch,
        securities=securities,
        today=lambda: TODAY,
    ).subscribe()
    bus.publish(
        new_envelope(
            RUN_REQUESTED,
            ScreeningRunRequestedV1(run_id=1, trigger="scheduled", options=RunOptionsV1()),
            source="va/test",
            correlationid="1",
        )
    )
    return seen


@pytest.fixture
def bus() -> InProcessBus:
    return InProcessBus(max_deliver=1)


class TestWeeklyRun:
    def test_master_data_before_the_snapshot(self, bus):
        result = RefreshResult([_resolved(WORLD, etf=WORLD_ETF)], missing=["DE000A383J95"])
        updated, completed = _run(bus, lambda: result)
        assert (updated.type, completed.type) == (SECURITIES_UPDATED.type, SNAPSHOT_COMPLETED.type)
        assert updated.correlationid == "1"
        data = updated.data
        assert data.as_of == TODAY
        assert [s.isin for s in data.securities] == [WORLD]
        assert data.missing == ["DE000A383J95"]

    def test_at_most_50_securities_per_event(self, bus):
        isins = [f"IE00B4L5Y{i:03d}" for i in range(SECURITIES_PER_EVENT + 5)]
        result = RefreshResult([_resolved(isin) for isin in isins], missing=["DE000A383J95"])
        events = _run(bus, lambda: result)
        updated = [e for e in events if e.type == SECURITIES_UPDATED.type]
        assert [len(e.data.securities) for e in updated] == [SECURITIES_PER_EVENT, 5]
        assert [e.data.missing for e in updated] == [["DE000A383J95"], []]
        assert [s.isin for e in updated for s in e.data.securities] == isins

    def test_only_missing_isins_are_still_reported(self, bus):
        updated, _ = _run(bus, lambda: RefreshResult([], missing=["DE000A383J95"]))
        assert (updated.data.securities, updated.data.missing) == ([], ["DE000A383J95"])

    def test_nothing_to_report_no_event(self, bus):
        [completed] = _run(bus, lambda: RefreshResult([], missing=[]))
        assert completed.type == SNAPSHOT_COMPLETED.type

    def test_a_failing_refresh_does_not_stop_the_run(self, bus):
        def broken() -> RefreshResult:
            raise ConnectionError("FIRDS und Datenbank weg")

        [completed] = _run(bus, broken)
        assert completed.type == SNAPSHOT_COMPLETED.type

    def test_without_refresh_as_before(self, bus):
        [completed] = _run(bus, None)
        assert completed.type == SNAPSHOT_COMPLETED.type


class TestSecurityV1:
    def test_an_etf_with_its_largest_holdings(self):
        security = security_v1(_resolved(WORLD, name="ISHSIII-CORE MSCI WORLD", etf=WORLD_ETF))
        etf = security.etf
        assert etf is not None
        assert (etf.source, etf.as_of, etf.complete, etf.holdings_count) == (
            "ishares",
            date(2026, 11, 19),
            True,
            30,
        )
        assert (etf.ter, etf.fund_size, etf.fund_currency, etf.distribution, etf.provider) == (
            0.2,
            142076.32,
            "USD",
            "accumulating",
            "iShares",
        )
        # Der Name des Anbieters; der aus FIRDS ist gekuerzt und gross geschrieben
        assert etf.name == "iShares Core MSCI World UCITS ETF"
        assert security.name == "ISHSIII-CORE MSCI WORLD"
        assert [h.ticker for h in etf.top_holdings] == [f"T{i}" for i in range(10)]
        assert (etf.sectors, etf.countries, etf.asset_classes) == (
            {"IT": 70.0},
            {"USA": 70.0},
            {"Aktien": 70.0},
        )
        assert security.listing is not None
        assert security.listing.symbol == "EUNL.DE"

    def test_a_bond_keeps_its_terms(self):
        bond = ResolvedSecurity(
            master=SecurityMaster(
                "DE0001102580",
                "Bund 0% 2030",
                "bond",
                "EUR",
                bond=BondTerms(0.0, date(2030, 2, 15)),
            ),
            listings=(),
            listing=None,
        )
        security = security_v1(bond)
        assert (security.etf, security.listing) == (None, None)
        assert security.bond is not None
        assert security.bond.maturity == date(2030, 2, 15)

    def test_an_event_of_50_large_etfs_stays_well_below_one_megabyte(self):
        """NATS nimmt hoechstens 1 MB je Nachricht; ein ETF mit 70 Laendern und 11 Sektoren."""
        from va_contracts.events.v1 import SecuritiesUpdatedV1

        big = EtfComposition(
            **{
                **vars(WORLD_ETF),
                "countries": {f"Land {i}": 1.0 for i in range(70)},
                "sectors": {f"Sektor {i}": 1.0 for i in range(11)},
                "holdings": tuple(_holding(i) for i in range(4000)),
            }
        )
        securities = [
            security_v1(_resolved(f"IE00B4L5Y{i:03d}", etf=big))
            for i in range(SECURITIES_PER_EVENT)
        ]
        payload = SecuritiesUpdatedV1(as_of=TODAY, securities=securities).model_dump_json()
        assert len(payload.encode()) < 400_000
