"""Vergleich eines nachgespielten Bewertungslaufs mit dem gespeicherten (P2b.0)."""

from __future__ import annotations

import math
from collections.abc import Mapping

import pandas as pd

from src.regression.compare import (
    Difference,
    compare_csv,
    compare_factor_scores,
    compare_scores,
)


def _scores(**changes: Mapping[str, object]) -> pd.DataFrame:
    rows: dict[str, dict[str, object]] = {
        "AAA.DE": {
            "passed_filter": True,
            "value_score": 0.8,
            "quality_score": 0.6,
            "composite_score": 0.72,
            "value_trap_flag": False,
            "rank_overall": 1,
        },
        "BBB.DE": {
            "passed_filter": True,
            "value_score": 0.4,
            "quality_score": None,
            "composite_score": None,
            "value_trap_flag": False,
            "rank_overall": 2,
        },
        "TINY.DE": {
            "passed_filter": False,
            "value_score": None,
            "quality_score": None,
            "composite_score": None,
            "value_trap_flag": None,
            "rank_overall": None,
        },
    }
    for symbol, change in changes.items():
        rows[symbol] = {**rows[symbol], **change}
    return pd.DataFrame([{"symbol": s, **v} for s, v in rows.items()])


def _factors(**changes: Mapping[str, object]) -> pd.DataFrame:
    rows: dict[tuple[str, str], dict[str, object]] = {
        ("AAA.DE", "ev_ebit"): {"raw_value": 8.0, "percentile_rank": 1.0},
        ("AAA.DE", "roic"): {"raw_value": 0.12, "percentile_rank": 0.5},
        ("BBB.DE", "ev_ebit"): {"raw_value": 12.0, "percentile_rank": 0.5},
    }
    for key, change in changes.items():
        symbol, factor = key.split(":")
        rows[(symbol, factor)] = {**rows[(symbol, factor)], **change}
    return pd.DataFrame(
        [
            {
                "symbol": symbol,
                "factor_key": factor,
                "category": "value" if factor == "ev_ebit" else "quality",
                "source_column": factor,
                "direction": "low" if factor == "ev_ebit" else "high",
                **values,
            }
            for (symbol, factor), values in rows.items()
        ]
    )


class TestCompareScores:
    def test_equal_results_have_no_differences(self):
        assert compare_scores(_scores(), _scores()) == []

    def test_changed_score_is_reported_with_old_and_new_value(self):
        actual = _scores(**{"AAA.DE": {"composite_score": 0.70}})
        assert compare_scores(_scores(), actual) == [
            Difference("scores", "AAA.DE", "composite_score", 0.72, 0.70)
        ]

    def test_changed_rank_flag_and_filter_are_reported(self):
        actual = _scores(
            **{
                "AAA.DE": {"rank_overall": 2, "value_trap_flag": True},
                "TINY.DE": {"passed_filter": True},
            }
        )
        found = {(d.symbol, d.field) for d in compare_scores(_scores(), actual)}
        assert found == {
            ("AAA.DE", "rank_overall"),
            ("AAA.DE", "value_trap_flag"),
            ("TINY.DE", "passed_filter"),
        }

    def test_score_that_disappears_is_a_difference(self):
        # z. B. M1: Ohne Quality-Score gibt es keinen Composite mehr
        expected = _scores(**{"BBB.DE": {"composite_score": 0.4}})
        assert compare_scores(expected, _scores()) == [
            Difference("scores", "BBB.DE", "composite_score", 0.4, None)
        ]

    def test_missing_and_extra_titles_are_reported(self):
        expected = _scores()
        actual = pd.concat(
            [
                expected[expected["symbol"] != "BBB.DE"],
                pd.DataFrame([{"symbol": "NEW.DE", "passed_filter": False}]),
            ],
            ignore_index=True,
        )
        assert compare_scores(expected, actual) == [
            Difference("scores", "BBB.DE", "titel", "vorhanden", "fehlt"),
            Difference("scores", "NEW.DE", "titel", "fehlt", "vorhanden"),
        ]

    def test_last_digit_and_empty_versus_nan_are_equal(self):
        actual = _scores(
            **{
                "AAA.DE": {"composite_score": math.nextafter(0.72, 1.0)},
                "BBB.DE": {"quality_score": float("nan")},
            }
        )
        assert compare_scores(_scores(), actual) == []

    def test_row_order_does_not_matter(self):
        actual = _scores().iloc[::-1].reset_index(drop=True)
        assert compare_scores(_scores(), actual) == []


class TestCompareFactorScores:
    def test_equal_results_have_no_differences(self):
        assert compare_factor_scores(_factors(), _factors()) == []

    def test_changed_rank_is_reported_per_factor(self):
        actual = _factors(**{"AAA.DE:roic": {"percentile_rank": 0.75}})
        assert compare_factor_scores(_factors(), actual) == [
            Difference("factors", "AAA.DE", "roic.percentile_rank", 0.5, 0.75)
        ]

    def test_missing_factor_is_reported(self):
        actual = _factors().iloc[:2]
        assert compare_factor_scores(_factors(), actual) == [
            Difference("factors", "BBB.DE", "ev_ebit", "vorhanden", "fehlt")
        ]


def _csv(rows: list[dict[str, object]]) -> bytes:
    return (
        pd.DataFrame(rows)
        .to_csv(index=False, sep=";", decimal=",", lineterminator="\n")
        .encode("utf-8-sig")
    )


CSV_ROWS: list[dict[str, object]] = [
    {"rank_overall": 1, "symbol": "AAA.DE", "name": "Alpha", "composite_score": 0.72},
    {"rank_overall": 2, "symbol": "BBB.DE", "name": "Beta", "composite_score": None},
]


class TestCompareCsv:
    def test_equal_content_has_no_differences(self):
        assert compare_csv(_csv(CSV_ROWS), _csv(CSV_ROWS)) == []

    def test_last_digit_is_tolerated(self):
        rows = [{**CSV_ROWS[0], "composite_score": math.nextafter(0.72, 1.0)}, CSV_ROWS[1]]
        assert compare_csv(_csv(CSV_ROWS), _csv(rows)) == []

    def test_changed_cell_is_reported_with_title_and_column(self):
        rows = [CSV_ROWS[0], {**CSV_ROWS[1], "name": "Beta AG"}]
        assert compare_csv(_csv(CSV_ROWS), _csv(rows)) == [
            Difference("csv", "BBB.DE", "name", "Beta", "Beta AG")
        ]

    def test_changed_order_is_reported(self):
        swapped = [
            {**CSV_ROWS[1], "rank_overall": 1},
            {**CSV_ROWS[0], "rank_overall": 2},
        ]
        differences = compare_csv(_csv(CSV_ROWS), _csv(swapped))
        assert Difference("csv", "AAA.DE", "symbol", "AAA.DE", "BBB.DE") in differences

    def test_changed_columns_are_one_difference(self):
        rows = [{k: v for k, v in r.items() if k != "name"} for r in CSV_ROWS]
        assert compare_csv(_csv(CSV_ROWS), _csv(rows)) == [
            Difference(
                "csv",
                "",
                "spalten",
                "rank_overall, symbol, name, composite_score",
                "rank_overall, symbol, composite_score",
            )
        ]

    def test_extra_row_is_reported(self):
        rows = [*CSV_ROWS, {"rank_overall": 3, "symbol": "CCC.DE", "name": "Gamma"}]
        assert compare_csv(_csv(CSV_ROWS), _csv(rows)) == [
            Difference("csv", "CCC.DE", "zeile", "fehlt", "vorhanden")
        ]
