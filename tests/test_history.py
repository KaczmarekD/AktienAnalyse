"""Parser fuer Zeitreihen (ADR-0010): Aktienanzahl (F1.3)."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pandas as pd
from src.history import HistoryState, daily_share_counts

FIXTURES = Path(__file__).parent / "fixtures" / "shares"


def _recorded_shares(symbol: str) -> pd.Series:
    """Echte Antwort von ``get_shares_full(start='2000-01-01')`` (yfinance 1.7)."""
    doc = json.loads((FIXTURES / f"{symbol}.json").read_text(encoding="utf-8"))
    stamps, values = zip(*doc["series"], strict=True)
    return pd.Series(values, index=pd.DatetimeIndex([pd.Timestamp(s) for s in stamps]))


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

    def test_invalid_value_does_not_hide_a_valid_one_of_the_same_day(self):
        series = _series(("2026-01-08 09:00", 1_000), ("2026-01-08 17:00", float("nan")))
        assert daily_share_counts(series) == {date(2026, 1, 8): 1_000}

    def test_nothing_to_parse(self):
        assert daily_share_counts(None) == {}
        assert daily_share_counts(pd.Series(dtype="int64")) == {}


class TestHistoryState:
    def test_default_means_nothing_stored_yet(self):
        assert HistoryState().last_share_date is None
