"""Parser fuer Zeitreihen (ADR-0010): Aktienanzahl (F1.3) und Kurshistorie (F1.4)."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd

from va_market_data.adapters.yahoo import normalize_prices
from va_market_data.domain.history import (
    HistoryState,
    PriceBar,
    daily_price_bars,
    daily_share_counts,
    split_days,
)

FIXTURES = Path(__file__).parent / "fixtures" / "shares"
PRICE_FIXTURES = Path(__file__).parent / "fixtures" / "prices"


def _recorded_shares(symbol: str) -> pd.Series:
    """Echte Antwort von ``get_shares_full(start='2000-01-01')`` (yfinance 1.7)."""
    doc = json.loads((FIXTURES / f"{symbol}.json").read_text(encoding="utf-8"))
    stamps, values = zip(*doc["series"], strict=True)
    # Sommer- und Winterzeit wechseln, yfinance liefert den Index in der Zeitzone der Boerse
    index = pd.to_datetime(list(stamps), utc=True).tz_convert(doc["tz"])
    return pd.Series(values, index=index)


def _series(*points: tuple[str, float]) -> pd.Series:
    return pd.Series(
        [v for _, v in points],
        index=pd.DatetimeIndex([pd.Timestamp(s) for s, _ in points]),
    )


class TestDailyShareCounts:
    def test_recorded_series_gives_one_value_per_day(self):
        series = _recorded_shares("SAP.DE")
        days = {ts.date() for ts in series.index}
        counts = daily_share_counts(series)
        assert set(counts) == days
        assert len(counts) < len(series)  # Yahoo liefert manche Tage mehrfach
        assert all(isinstance(d, date) for d in counts)
        assert all(isinstance(v, int) and v > 0 for v in counts.values())

    def test_last_value_of_a_day_wins(self):
        series = _recorded_shares("SAP.DE")
        same_day = series[[ts.date() == date(2017, 12, 1) for ts in series.index]]
        assert len(same_day) > 1
        assert daily_share_counts(series)[date(2017, 12, 1)] == int(same_day.iloc[-1])

    def test_day_is_taken_in_the_exchange_timezone(self):
        # Mitternacht in Frankfurt ist in UTC noch der Vortag
        counts = daily_share_counts(_series(("2018-08-08 00:00:00+02:00", 1_195_520_000)))
        assert counts == {date(2018, 8, 8): 1_195_520_000}

    def test_naive_timestamps_are_accepted(self):
        counts = daily_share_counts(_series(("2026-07-29 00:00:00", 1_154_204_232)))
        assert counts == {date(2026, 7, 29): 1_154_204_232}

    def test_missing_and_implausible_values_are_skipped(self):
        series = _series(
            ("2026-01-02", float("nan")),
            ("2026-01-05", 0),
            ("2026-01-06", -5),
            ("2026-01-07", float("inf")),
            ("2026-01-08", 1_000.0),
        )
        assert daily_share_counts(series) == {date(2026, 1, 8): 1_000}

    def test_values_outside_the_database_range_are_skipped(self):
        """Review: Ein Wert, der als 0 oder ueber BIGINT gespeichert wuerde, kostete sonst
        den ganzen Titel (CHECK bzw. Ueberlauf in der Transaktion)."""
        series = _series(("2026-01-07", 0.4), ("2026-01-08", 1e19), ("2026-01-09", 1_000.4))
        assert daily_share_counts(series) == {date(2026, 1, 9): 1_000}

    def test_invalid_value_does_not_hide_a_valid_one_of_the_same_day(self):
        series = _series(("2026-01-08 09:00", 1_000), ("2026-01-08 17:00", float("nan")))
        assert daily_share_counts(series) == {date(2026, 1, 8): 1_000}

    def test_nothing_to_parse(self):
        assert daily_share_counts(None) == {}
        assert daily_share_counts(pd.Series(dtype="int64")) == {}


def _recorded_prices(name: str) -> pd.DataFrame:
    """Echte Antwort von ``history(auto_adjust=False, actions=True)`` (yfinance 1.7).

    So, wie ``fetch_prices`` sie weitergibt: mit eigenen Spaltennamen (``PRICE_FIELDS``).
    """
    doc = json.loads((PRICE_FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
    index = pd.to_datetime(doc["index"], utc=True).tz_convert(doc["tz"])
    frame = normalize_prices(pd.DataFrame(doc["data"], index=index, columns=doc["columns"]))
    assert frame is not None
    return frame


# Abruf am Samstag nach dem Fenster: alle Tage im Fixture sind abgeschlossen
AFTER = datetime(2026, 10, 17, 5, 30, tzinfo=UTC)


class TestDailyPriceBars:
    def test_recorded_window_gives_one_bar_per_trading_day(self):
        frame = _recorded_prices("SAP.DE_dividende_2025")
        bars = daily_price_bars(frame, fetched_at=AFTER)
        assert len(bars) == len(frame)
        assert min(bars) == date(2025, 4, 28)
        assert all(isinstance(b, PriceBar) for b in bars.values())

    def test_columns_are_mapped(self):
        frame = _recorded_prices("SAP.DE_dividende_2025")
        row = frame.iloc[0]
        bar = daily_price_bars(frame, fetched_at=AFTER)[date(2025, 4, 28)]
        assert bar == PriceBar(
            close=row["close"], adj_close=row["adj_close"], dividend=0.0, split=0.0
        )

    def test_dividend_day(self):
        bars = daily_price_bars(_recorded_prices("SAP.DE_dividende_2025"), fetched_at=AFTER)
        assert bars[date(2025, 5, 14)].dividend == 2.35
        assert sum(b.dividend > 0 for b in bars.values()) == 1

    def test_split_day(self):
        frame = _recorded_prices("SAP.DE_split_2000")
        bars = daily_price_bars(frame, fetched_at=AFTER)
        assert bars[date(2000, 6, 26)].split == 3.0
        assert split_days(frame) == {date(2000, 6, 26)}

    def test_day_of_the_fetch_is_not_complete_and_skipped(self):
        frame = _recorded_prices("SAP.DE_dividende_2025")
        # Abruf am 14.05.2025 um 10:00 Uhr in Frankfurt: Der Tag laeuft noch
        during = datetime(2025, 5, 14, 8, 0, tzinfo=UTC)
        bars = daily_price_bars(frame, fetched_at=during)
        assert max(bars) == date(2025, 5, 13)

    def test_day_is_taken_in_the_exchange_timezone(self):
        # 23:30 UTC ist in Frankfurt schon der naechste Tag - der 14.05. ist dann abgeschlossen
        frame = _recorded_prices("SAP.DE_dividende_2025")
        late = datetime(2025, 5, 14, 22, 30, tzinfo=UTC)
        assert max(daily_price_bars(frame, fetched_at=late)) == date(2025, 5, 14)

    def test_missing_close_is_skipped_missing_adj_close_is_kept_empty(self):
        index = pd.DatetimeIndex(["2026-01-05", "2026-01-06"]).tz_localize("Europe/Berlin")
        frame = pd.DataFrame(
            {
                "close": [float("nan"), 101.0],
                "adj_close": [100.0, float("nan")],
                "dividend": [0.0, 0.0],
                "split": [0.0, 0.0],
            },
            index=index,
        )
        bars = daily_price_bars(frame, fetched_at=AFTER)
        assert bars == {date(2026, 1, 6): PriceBar(101.0, None, 0.0, 0.0)}

    def test_nothing_to_parse(self):
        assert daily_price_bars(None, fetched_at=AFTER) == {}
        assert daily_price_bars(pd.DataFrame(), fetched_at=AFTER) == {}
        assert split_days(None) == set()


CLOSE, ADJ = 181.6999969482422, 179.1234567


class TestPriceBarComparison:
    BAR = PriceBar(close=CLOSE, adj_close=ADJ, dividend=0.0, split=0.0)

    def test_float_noise_of_yahoo_is_no_change(self):
        # Gemessen: Adj Close weicht zwischen zwei Abrufen um bis zu 6e-7 relativ ab
        noisy = PriceBar(CLOSE, ADJ * (1 + 6e-7), 0.0, 0.0)
        assert noisy.same_as(self.BAR)

    def test_adjustment_by_a_dividend_is_a_change(self):
        adjusted = PriceBar(CLOSE, ADJ * 0.99, 0.0, 0.0)
        assert not adjusted.same_as(self.BAR)

    def test_split_adjusted_close_is_a_change(self):
        assert not PriceBar(CLOSE / 3, None, 0.0, 0.0).same_as(PriceBar(CLOSE, None, 0.0, 0.0))

    def test_new_dividend_or_split_is_a_change(self):
        assert not PriceBar(CLOSE, None, 2.35, 0.0).same_as(PriceBar(CLOSE, None, 0.0, 0.0))
        assert not PriceBar(CLOSE, None, 0.0, 3.0).same_as(PriceBar(CLOSE, None, 0.0, 0.0))

    def test_adj_close_appearing_is_a_change(self):
        assert not PriceBar(1.0, 1.0, 0.0, 0.0).same_as(PriceBar(1.0, None, 0.0, 0.0))


class TestHistoryState:
    def test_default_means_nothing_stored_yet(self):
        state = HistoryState()
        assert state.last_share_date is None
        assert state.last_price_date is None
        assert state.price_split_days == frozenset()
