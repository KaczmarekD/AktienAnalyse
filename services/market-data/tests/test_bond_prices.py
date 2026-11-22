"""Kurse der Bundesanleihen im Abruf der Tageskurse (D2.5, WP-06, WP-07, WP-08).

- Alle Anleihen der Abdeckung, ein eigener ``price_run`` mit Quelle ``bundesbank``.
- Der Kurs in Prozent vom Nennwert, Notierung ``%``, Waehrung EUR.
- Nicht in der Liste (Unternehmensanleihen): ``missing``. Ein Ausfall der Bundesbank ist ein
  ``price_run`` mit ``failed`` und kostet nur diese Kurse. Ohne Anleihen kein Abruf.
- Zusammen mit den Kursen von Yahoo: ein Event mit allen Abrufen des Termins.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

from va_contracts import Envelope, new_envelope
from va_contracts.events.v1 import PRICES_COMPLETED, PRICES_REQUESTED, PricesRequestedV1
from va_market_data.application.prices import (
    BOND_SOURCE,
    BondQuotes,
    PricesResult,
    collect_bond_prices,
    with_bonds,
)
from va_market_data.domain.coverage import CoverageItem
from va_market_data.domain.prices import PERCENT_OF_PAR, DailyClose
from va_market_data.entrypoints.handlers import PricesRequestedHandler
from va_platform.bus import InProcessBus

NOW = datetime(2026, 11, 20, 21, 35, tzinfo=UTC)
FRIDAY = date(2026, 11, 20)
BOBL = CoverageItem("DE0001141851", "bond", None, None, "Bobl 0 % 2027")
DBR = CoverageItem("DE0001102416", "bond", None, None, "Bund 0,25 % 2027")
CORP = CoverageItem("DE000A383J95", "bond", None, None, "DB 4 % 2028")
APPLE = CoverageItem("US0378331005", "equity", "AAPL", "APC.DE", "Apple")


@dataclass
class FakePriceStore:
    written: list[dict[str, Any]] = field(default_factory=list)

    def known_currencies(self, symbols):
        return {}

    def write_prices(self, *, source, started_at, finished_at, status, closes, fx):
        self.written.append(
            {"source": source, "status": status, "closes": list(closes), "fx": list(fx)}
        )
        return 10 + len(self.written)


def _collect(store, items, quotes=None, error: Exception | None = None):
    asked: list[date] = []

    def bundesbank(trade_date: date) -> BondQuotes | None:
        asked.append(trade_date)
        if error:
            raise error
        return quotes

    result = collect_bond_prices(
        items, store=store, quotes=bundesbank, trade_date=FRIDAY, clock=lambda: NOW
    )
    return result, asked


class TestCollect:
    def test_bonds_of_the_coverage_in_percent(self):
        store = FakePriceStore()
        quotes = BondQuotes(FRIDAY, {BOBL.isin: 98.94, DBR.isin: 99.445, "DE0001030583": 95.2})
        result, asked = _collect(store, [APPLE, BOBL, DBR, CORP], quotes)
        assert result is not None
        assert asked == [FRIDAY]
        assert result.price_run_id == 11
        assert sorted((c.isin, c.close) for c in result.closes) == [
            (DBR.isin, 99.445),
            (BOBL.isin, 98.94),
        ]
        close = result.closes[0]
        assert (close.symbol, close.currency, close.quote_currency) == (None, "EUR", "%")
        assert close.percent_of_par
        assert result.missing == [CORP.isin]  # keine Bundesanleihe
        [written] = store.written
        assert (written["source"], written["status"], written["fx"]) == (BOND_SOURCE, "ok", [])

    def test_the_day_of_the_list_counts(self):
        """Vor der Veroeffentlichung am Abend: der Kurs des Vortags mit dessen Datum."""
        thursday = date(2026, 11, 19)
        result, _ = _collect(FakePriceStore(), [BOBL], BondQuotes(thursday, {BOBL.isin: 98.93}))
        assert result is not None
        assert result.closes[0].trade_date == thursday

    def test_a_failure_is_a_failed_run(self):
        store = FakePriceStore()
        result, _ = _collect(store, [BOBL, DBR], error=ConnectionError("Bundesbank weg"))
        assert result is not None
        assert (result.closes, result.missing) == ([], [DBR.isin, BOBL.isin])
        assert store.written[0]["status"] == "failed"

    def test_no_list_found_is_a_failed_run(self):
        store = FakePriceStore()
        result, _ = _collect(store, [BOBL], None)
        assert result is not None
        assert result.missing == [BOBL.isin]
        assert store.written[0]["status"] == "failed"

    def test_without_bonds_no_request(self):
        store = FakePriceStore()
        result, asked = _collect(store, [APPLE], BondQuotes(FRIDAY, {}))
        assert (result, asked, store.written) == (None, [], [])


class TestTogether:
    def _yahoo(self) -> PricesResult:
        return PricesResult(
            price_run_id=7,
            trade_date=FRIDAY,
            closes=[DailyClose(APPLE.isin, "APC.DE", FRIDAY, 231.5, "EUR", "EUR")],
            missing=[BOBL.isin, CORP.isin],  # ohne Kurs-Listing
        )

    def test_one_result_with_both_runs(self):
        bonds = PricesResult(
            price_run_id=8,
            trade_date=FRIDAY,
            closes=[DailyClose(BOBL.isin, None, FRIDAY, 98.94, "EUR", PERCENT_OF_PAR)],
            missing=[CORP.isin],
        )
        together = with_bonds(self._yahoo(), bonds)
        assert together.price_run_id == 7
        assert together.price_run_ids == [7, 8]
        assert [c.isin for c in together.closes] == [APPLE.isin, BOBL.isin]
        assert together.missing == [CORP.isin]

    def test_without_bonds_unchanged(self):
        yahoo = self._yahoo()
        assert with_bonds(yahoo, None) == yahoo


def test_the_event_marks_percent_and_names_all_runs():
    bus = InProcessBus(max_deliver=1)
    seen: list[Envelope[Any]] = []
    bus.subscribe(PRICES_COMPLETED, "probe", seen.append)
    result = PricesResult(
        price_run_id=7,
        trade_date=FRIDAY,
        closes=[
            DailyClose(APPLE.isin, "APC.DE", FRIDAY, 231.5, "EUR", "EUR"),
            DailyClose(BOBL.isin, None, FRIDAY, 98.94, "EUR", PERCENT_OF_PAR),
        ],
        price_run_ids=[7, 8],
    )
    PricesRequestedHandler(bus, collect=lambda _: result).subscribe()
    bus.publish(
        new_envelope(
            PRICES_REQUESTED, PricesRequestedV1(slot=NOW, trade_date=FRIDAY), source="va/web-api"
        )
    )
    [completed] = seen
    assert [c.percent_of_par for c in completed.data.closes] == [False, True]
    assert completed.data.price_run_ids == [7, 8]


def test_a_yahoo_only_run_names_its_run():
    bus = InProcessBus(max_deliver=1)
    seen: list[Envelope[Any]] = []
    bus.subscribe(PRICES_COMPLETED, "probe", seen.append)
    PricesRequestedHandler(
        bus, collect=lambda _: PricesResult(price_run_id=7, trade_date=FRIDAY)
    ).subscribe()
    bus.publish(
        new_envelope(
            PRICES_REQUESTED, PricesRequestedV1(slot=NOW, trade_date=FRIDAY), source="va/web-api"
        )
    )
    assert seen[0].data.price_run_ids == [7]
