"""Tageskurse (D2.3, WP-06, WP-07, WP-11; docs/architecture/depot/wertpapiere.md#abdeckung-und-abrufe).

- An jedem Handelstag die Schlusskurse aller Wertpapiere der Abdeckung mit Kurs-Listing, ueber
  einen Sammelabruf, und die Waehrungskurse nach EUR.
- London notiert in Pence (``GBp``): durch 100, Waehrung GBP.
- Ein Titel ohne Kurs fehlt mit seiner ISIN, die anderen laufen weiter. Ein Feiertag bringt keine
  neuen Kurse, der letzte bleibt (gespeichert wird je Tag nur einmal).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

import pandas as pd
import pytest

from va_contracts import Envelope, new_envelope
from va_contracts.events.v1 import PRICES_COMPLETED, PRICES_REQUESTED, PricesRequestedV1
from va_market_data.adapters.yahoo import quotes_from_download
from va_market_data.application.prices import collect_prices
from va_market_data.domain.coverage import CoverageItem
from va_market_data.domain.prices import DailyClose, FxDaily, Quote, to_major_unit
from va_market_data.entrypoints.handlers import PricesRequestedHandler
from va_platform.bus import InProcessBus

NOW = datetime(2026, 11, 6, 21, 35, tzinfo=UTC)
FRIDAY = date(2026, 11, 6)
APPLE = CoverageItem("US0378331005", "equity", "AAPL", "APC.DE", "Apple")
WORLD = CoverageItem("IE00B4L5Y983", "etf", None, "IWDA.L", "iShares Core MSCI World")
SHELL = CoverageItem("GB00BP6MXD84", "equity", "SHEL.L", "SHEL.L", "Shell")
BOND = CoverageItem("DE000A383J95", "bond", None, None, "DB 4 % 2028")


class TestUnits:
    @pytest.mark.parametrize(
        ("close", "currency", "expected"),
        [
            (2650.0, "GBp", (26.5, "GBP")),
            (2650.0, "GBX", (26.5, "GBP")),
            (1250.0, "ZAc", (12.5, "ZAR")),
            (231.5, "EUR", (231.5, "EUR")),
            (98.2, "USD", (98.2, "USD")),
        ],
    )
    def test_minor_units(self, close, currency, expected):
        assert to_major_unit(close, currency) == expected


class TestDownload:
    def test_latest_close_per_symbol(self):
        index = pd.to_datetime(["2026-11-04", "2026-11-05", "2026-11-06"])
        columns = pd.MultiIndex.from_tuples(
            [("APC.DE", "Close"), ("APC.DE", "Open"), ("IWDA.L", "Close"), ("IWDA.L", "Open")]
        )
        frame = pd.DataFrame(
            [
                [230.0, 229.0, 98.0, 97.0],
                [231.0, 230.0, 98.5, 98.0],
                [231.5, 231.0, float("nan"), 98.4],  # London ohne Schlusskurs am Freitag
            ],
            index=index,
            columns=columns,
        )
        quotes = quotes_from_download(frame, ["APC.DE", "IWDA.L", "XXX"])
        assert quotes == {
            "APC.DE": Quote("APC.DE", date(2026, 11, 6), 231.5),
            "IWDA.L": Quote("IWDA.L", date(2026, 11, 5), 98.5),
        }

    def test_one_symbol_without_multiindex(self):
        frame = pd.DataFrame(
            {"Close": [231.5], "Open": [231.0]}, index=pd.to_datetime(["2026-11-06"])
        )
        assert quotes_from_download(frame, ["APC.DE"]) == {
            "APC.DE": Quote("APC.DE", date(2026, 11, 6), 231.5)
        }

    def test_empty(self):
        assert quotes_from_download(pd.DataFrame(), ["APC.DE"]) == {}


@dataclass
class FakePriceStore:
    currencies: dict[str, str] = field(default_factory=dict)
    written: list[dict[str, Any]] = field(default_factory=list)

    def known_currencies(self, symbols):
        return {s: c for s, c in self.currencies.items() if s in symbols}

    def write_prices(self, *, source, started_at, finished_at, status, closes, fx):
        self.written.append(
            {"source": source, "status": status, "closes": list(closes), "fx": list(fx)}
        )
        return 7


@dataclass
class World:
    store: FakePriceStore = field(default_factory=FakePriceStore)
    quotes: dict[str, Quote] = field(default_factory=dict)
    yahoo_currencies: dict[str, str] = field(default_factory=dict)
    rates: dict[str, float] = field(default_factory=dict)
    quote_error: Exception | None = None
    asked: list[str] = field(default_factory=list)

    def collect(self, items):
        def quotes(symbols):
            if self.quote_error:
                raise self.quote_error
            return {s: q for s, q in self.quotes.items() if s in symbols}

        def currency(symbol):
            self.asked.append(symbol)
            return self.yahoo_currencies.get(symbol)

        return collect_prices(
            items,
            store=self.store,
            quotes=quotes,
            currency_of=currency,
            rate_to_eur=self.rates.get,
            clock=lambda: NOW,
            trade_date=FRIDAY,
        )


@pytest.fixture
def world() -> World:
    return World()


class TestCollect:
    def test_closes_and_fx_for_the_coverage(self, world):
        world.quotes = {
            "APC.DE": Quote("APC.DE", FRIDAY, 231.5),
            "IWDA.L": Quote("IWDA.L", FRIDAY, 98.5),
            "SHEL.L": Quote("SHEL.L", FRIDAY, 2650.0),
        }
        world.store.currencies = {"APC.DE": "EUR"}
        world.yahoo_currencies = {"IWDA.L": "USD", "SHEL.L": "GBp"}
        world.rates = {"USD": 0.92, "GBP": 1.18}
        result = world.collect([APPLE, WORLD, SHELL, BOND])
        assert result.price_run_id == 7
        assert sorted((c.isin, c.close, c.currency) for c in result.closes) == [
            ("GB00BP6MXD84", 26.5, "GBP"),
            ("IE00B4L5Y983", 98.5, "USD"),
            ("US0378331005", 231.5, "EUR"),
        ]
        assert sorted((f.currency, f.rate_to_eur) for f in result.fx) == [
            ("GBP", 1.18),
            ("USD", 0.92),
        ]
        assert result.missing == ["DE000A383J95"]  # Anleihe ohne Listing
        assert world.asked == ["IWDA.L", "SHEL.L"]  # bekannte Waehrung: kein Abruf
        [written] = world.store.written
        assert written["status"] == "ok"

    def test_a_title_without_price_is_missing(self, world):
        world.quotes = {"APC.DE": Quote("APC.DE", FRIDAY, 231.5)}
        world.store.currencies = {"APC.DE": "EUR"}
        result = world.collect([APPLE, WORLD])
        assert [c.symbol for c in result.closes] == ["APC.DE"]
        assert result.missing == ["IE00B4L5Y983"]

    def test_unknown_currency_is_missing_not_guessed(self, world):
        world.quotes = {"IWDA.L": Quote("IWDA.L", FRIDAY, 98.5)}
        result = world.collect([WORLD])
        assert result.closes == []
        assert result.missing == ["IE00B4L5Y983"]

    def test_download_failure_is_a_failed_run_not_an_error(self, world):
        world.quote_error = ConnectionError("Yahoo weg")
        result = world.collect([APPLE, WORLD])
        assert result.closes == []
        assert result.missing == ["IE00B4L5Y983", "US0378331005"]
        [written] = world.store.written
        assert written["status"] == "failed"

    def test_nothing_to_fetch(self, world):
        result = world.collect([BOND])
        assert (result.closes, result.missing) == ([], ["DE000A383J95"])

    def test_the_trade_date_is_the_newest_close(self, world):
        """Ein Feiertag: Yahoo liefert den letzten Handelstag."""
        world.quotes = {"APC.DE": Quote("APC.DE", date(2026, 11, 5), 231.0)}
        world.store.currencies = {"APC.DE": "EUR"}
        result = world.collect([APPLE])
        assert result.trade_date == date(2026, 11, 5)

    def test_fx_belongs_to_the_requested_day(self, world):
        """Der Waehrungskurs ist der von jetzt, auch wenn der letzte Schlusskurs vom Vortag ist."""
        world.quotes = {"IWDA.L": Quote("IWDA.L", date(2026, 11, 5), 98.5)}
        world.store.currencies = {"IWDA.L": "USD"}
        world.rates = {"USD": 0.92}
        [fx] = world.collect([WORLD]).fx
        assert fx.trade_date == FRIDAY

    def test_the_quote_unit_is_kept_for_the_next_day(self, world):
        world.quotes = {"SHEL.L": Quote("SHEL.L", FRIDAY, 2650.0)}
        world.yahoo_currencies = {"SHEL.L": "GBp"}
        [close] = world.collect([SHELL]).closes
        assert (close.close, close.currency, close.quote_currency) == (26.5, "GBP", "GBp")


def test_the_handler_answers_with_the_prices():
    bus = InProcessBus(max_deliver=1)
    seen: list[Envelope[Any]] = []
    bus.subscribe(PRICES_COMPLETED, "probe", seen.append)
    calls: list[date] = []

    def collect(trade_date: date):
        from va_market_data.application.prices import PricesResult

        calls.append(trade_date)
        return PricesResult(
            price_run_id=7,
            trade_date=trade_date,
            closes=[DailyClose("US0378331005", "APC.DE", trade_date, 231.5, "EUR")],
            fx=[FxDaily("USD", trade_date, 0.92)],
            missing=[],
        )

    PricesRequestedHandler(bus, collect=collect).subscribe()
    bus.publish(
        new_envelope(
            PRICES_REQUESTED,
            PricesRequestedV1(slot=NOW, trade_date=FRIDAY),
            source="va/web-api",
        )
    )
    [completed] = seen
    assert calls == [FRIDAY]
    assert completed.data.price_run_id == 7
    assert completed.data.closes[0].isin == "US0378331005"
    assert completed.data.fx[0].rate_to_eur == 0.92


class TestFxCache:
    """Nebenbefund in D2.3: ``_fx_rate`` war "pro Run" gecacht, im dauerhaft laufenden Dienst aber
    ueber alle Wochenlaeufe. Jeder neue Abruf (``YahooFundamentals``) leert den Cache."""

    def test_a_new_fetch_asks_again(self, monkeypatch):
        from va_market_data.adapters import yahoo

        calls: list[str] = []

        class FakeTicker:
            def __init__(self, symbol: str) -> None:
                calls.append(symbol)
                self.fast_info = {"lastPrice": 0.92}

        monkeypatch.setattr("yfinance.Ticker", FakeTicker)
        yahoo._fx_rate.cache_clear()
        yahoo._fx_rate("USD", "EUR")
        yahoo._fx_rate("USD", "EUR")
        assert calls == ["USDEUR=X"]
        yahoo.YahooFundamentals(yahoo.FetcherConfig(default_tax_rate=0.27))
        yahoo._fx_rate("USD", "EUR")
        assert calls == ["USDEUR=X", "USDEUR=X"]
