"""Die Abrufschleife (P1.4) gegen einen Fake-Provider: kein yfinance, kein Netz."""

from __future__ import annotations

from datetime import date
from unittest.mock import patch

import pandas as pd
import pytest

from va_market_data.application.fetch import fetch_all, success_share
from va_market_data.domain.fundamentals import Fundamentals, Identity, MarketData
from va_market_data.domain.history import HistoryState
from va_market_data.domain.universe import Ticker

TICKERS = [Ticker(f"T{i}.DE", f"T{i}", "DAX") for i in range(4)]


class FakeProvider:
    """Liefert je Titel Fundamentaldaten; fuer ``failing`` ohne Marktkapitalisierung."""

    def __init__(self, failing: frozenset[str] = frozenset()) -> None:
        self.calls: list[tuple[str, HistoryState | None]] = []
        self._failing = failing

    def fetch(self, ticker: Ticker, history: HistoryState | None = None) -> Fundamentals:
        self.calls.append((ticker.symbol, history))
        fund = Fundamentals(identity=Identity(ticker.symbol, ticker.name, ticker.index))
        if ticker.symbol in self._failing:
            fund.errors.append("fetch failed: down")
        else:
            fund.market = MarketData(market_cap=1e9)
        return fund


def _fetch_all(provider, **kwargs):
    with patch("va_market_data.application.fetch.time.sleep") as sleep:
        df = fetch_all(TICKERS, provider, sleep_between=0.4, **kwargs)
    return df, sleep


class TestFetchAll:
    def test_flat_frame_in_ticker_order(self):
        df, _ = _fetch_all(FakeProvider(frozenset({"T0.DE"})))
        assert list(df["symbol"]) == [t.symbol for t in TICKERS]
        assert "fetched_at" in df.columns
        assert df.loc[0, "errors"] == "fetch failed: down"

    def test_callback_receives_every_result_before_the_next_fetch(self):
        provider = FakeProvider()
        seen: list[tuple[str, int]] = []
        _fetch_all(provider, on_result=lambda f: seen.append((f.symbol, len(provider.calls))))
        assert seen == [(t.symbol, i) for i, t in enumerate(TICKERS, 1)]

    def test_callback_error_aborts(self):
        def boom(_):
            raise RuntimeError("db down")

        with pytest.raises(RuntimeError, match="db down"):
            _fetch_all(FakeProvider(), on_result=boom)

    def test_history_is_passed_per_symbol(self):
        provider = FakeProvider()
        state = HistoryState(last_share_date=date(2026, 7, 29))
        _fetch_all(provider, history={"T1.DE": state})
        assert [h for _, h in provider.calls] == [None, state, None, None]

    def test_pause_between_titles(self):
        _, sleep = _fetch_all(FakeProvider())
        assert [c.args for c in sleep.call_args_list] == [(0.4,)] * len(TICKERS)


class TestSuccessShare:
    def test_share_of_titles_with_market_cap(self):
        df, _ = _fetch_all(FakeProvider(frozenset({"T0.DE", "T1.DE", "T2.DE"})))
        assert success_share(df) == pytest.approx(0.25)

    def test_empty(self):
        assert success_share(pd.DataFrame()) == 0.0
