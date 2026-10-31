"""Replay-Quelle (U5.1): Universum und Fundamentaldaten aus gespeicherten Snapshot-Zeilen.

Fuer den lokalen End-to-End-Test. Kein Netz, das Ergebnis steht fest.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from va_market_data.adapters.replay import (
    PROVIDER,
    SOURCE,
    ReplayFundamentals,
    fundamentals_from_flat,
    replay_universe,
)
from va_market_data.domain.fundamentals import (
    Fundamentals,
    Growth,
    Identity,
    MarketData,
    Provenance,
    QualityMetrics,
    ValueMetrics,
)
from va_market_data.domain.universe import Ticker

FULL = Fundamentals(
    identity=Identity(
        symbol="SAP.DE",
        name="SAP",
        index="DAX",
        sector="Technology",
        industry="Software",
        currency="EUR",
        financial_currency="EUR",
    ),
    market=MarketData(
        price=200.0, market_cap=2.4e11, enterprise_value=2.3e11, shares_outstanding=1.2e9
    ),
    value=ValueMetrics(
        ev_ebit=25.0,
        pe_ratio=40.0,
        pb_ratio=8.0,
        p_fcf=30.0,
        dividend_yield=0.01,
        buyback_yield=0.02,
        shareholder_yield=0.03,
    ),
    quality=QualityMetrics(
        roic=0.2,
        roa=0.1,
        fcf_margin=0.25,
        gross_margin=0.7,
        operating_margin=0.3,
        net_debt_ebitda=-0.5,
        debt_to_equity=0.3,
        earnings_stability=0.8,
    ),
    growth=Growth(revenue_growth_5y=0.08, eps_growth_5y=0.1),
    provenance=Provenance(
        fetched_at=datetime(2026, 10, 30, 21, 8, 2, tzinfo=UTC),
        fiscal_period_end=date(2025, 12, 31),
        statement_fx=1.0,
    ),
    errors=["info: Timeout", "cashflow: leer"],
)


def _row(symbol: str, name: str, index: str, **values: object) -> dict[str, object]:
    """Eine Zeile wie in einer Replay-Fixture: JSON-Werte, ``fetch_ok`` als Zusatzspalte."""
    return {
        "symbol": symbol,
        "name": name,
        "index": index,
        "market_cap": 5e9,
        "ev_ebit": float("nan"),
        "fetched_at": "2026-10-30T21:08:02.946406+00:00",
        "fiscal_period_end": "2025-12-31",
        "fetch_ok": True,
        "errors": "",
        **values,
    }


FALLBACK = [
    Ticker("ALV.DE", "Allianz SE", "DAX", "DE0008404005"),
    Ticker("SAP.DE", "SAP", "DAX", "DE0007164600"),
]
ROWS = [
    _row("ALV.DE", "Allianz", "DAX"),
    _row("8TRA.DE", "Traton", "MDAX", errors="info: leer"),
    _row("ALV.DE", "Allianz doppelt", "DAX"),
]


class TestFundamentalsFromFlat:
    def test_round_trip_through_the_flat_row(self):
        assert fundamentals_from_flat(FULL.to_flat_dict()) == FULL

    def test_fixture_row_is_typed_and_nan_becomes_none(self):
        fund = fundamentals_from_flat(ROWS[1])
        assert fund.identity == Identity("8TRA.DE", "Traton", "MDAX")
        assert fund.market.market_cap == 5e9
        assert fund.value.ev_ebit is None
        assert fund.provenance.fetched_at == datetime(2026, 10, 30, 21, 8, 2, 946406, tzinfo=UTC)
        assert fund.provenance.fiscal_period_end == date(2025, 12, 31)
        assert fund.errors == ["info: leer"]
        assert fund.raw is None


class TestReplayFundamentals:
    def test_returns_the_stored_row_of_the_symbol(self):
        provider = ReplayFundamentals(ROWS)
        fund = provider.fetch(Ticker("8TRA.DE", "Traton", "MDAX"))
        assert fund.symbol == "8TRA.DE"
        assert fund.market.market_cap == 5e9
        assert fund.errors == ["info: leer"]

    def test_unknown_symbol_is_a_failed_fetch_not_an_exception(self):
        fund = ReplayFundamentals(ROWS).fetch(Ticker("NEU.DE", "Neu AG", "MDAX"))
        assert fund.identity == Identity("NEU.DE", "Neu AG", "MDAX")
        assert fund.market.market_cap is None
        assert fund.errors == ["replay: kein Snapshot fuer NEU.DE"]

    def test_each_fetch_is_a_fresh_object(self):
        provider = ReplayFundamentals(ROWS)
        first = provider.fetch(Ticker("ALV.DE", "Allianz", "DAX"))
        first.errors.append("veraendert")
        assert provider.fetch(Ticker("ALV.DE", "Allianz", "DAX")).errors == []


class TestReplayUniverse:
    def test_titles_in_order_of_the_rows_without_duplicates(self):
        universe = replay_universe(ROWS, FALLBACK)
        assert [t.symbol for t in universe.tickers] == ["ALV.DE", "8TRA.DE"]
        assert universe.tickers[0] == Ticker("ALV.DE", "Allianz", "DAX", "DE0008404005")

    def test_isin_from_the_fallback_csv_if_known(self):
        universe = replay_universe(ROWS, FALLBACK)
        assert universe.tickers[1].isin is None

    def test_source_is_marked_and_not_compared_with_the_csv(self):
        universe = replay_universe(ROWS, FALLBACK)
        assert universe.source == SOURCE == "Replay"
        assert universe.as_of is None
        assert universe.added == []
        assert universe.removed == []


def test_provider_name_marks_replayed_fetches():
    assert PROVIDER == "replay"
