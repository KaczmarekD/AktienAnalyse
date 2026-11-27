"""Einordnung ins Referenzuniversum (D4.1, ANA-01 bis 03; docs/architecture/depot/analyse.md).

Eigenschaften aus der Spezifikation:
- Ein Kandidat mit denselben Kennzahlen wie ein Referenztitel landet neben ihm.
- Besser als alle: je Faktor der höchste Rang bei n+1 Werten (1,0 bei „hoch ist gut“,
  1 - 1/(n+1) bei „niedrig ist gut“); schlechter als alle entsprechend der niedrigste.
- Die Ränge der Referenztitel ändern sich nicht.
- Negative Multiples, Mindestanteil, Composite nur aus beiden Teilscores, Branchenregel und
  Value-Trap wie im Ranking; der Größenfilter gilt nicht.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd
import pytest

from va_scoring.domain.placement import composite_percentiles, place
from va_scoring.domain.scoring import ScoringConfig, score

CFG = ScoringConfig()
FACTORS = CFG.value_factors | CFG.quality_factors


@pytest.fixture
def reference(mock_universe_df: pd.DataFrame) -> pd.DataFrame:
    return score(mock_universe_df, CFG)


def _row(universe: pd.DataFrame, source: str, /, **values: Any) -> pd.DataFrame:
    """Die Zeile von ``source``, mit geänderten Werten (etwa einem neuen Symbol)."""
    row = universe[universe["symbol"] == source].copy()
    return row.assign(**values).reset_index(drop=True)


def _valid_count(reference: pd.DataFrame, col: str, *, positive: bool) -> int:
    values = reference[col].astype(float)
    valid = np.isfinite(values)
    if positive:
        valid &= values > 0
    return int(valid.sum())


class TestRanks:
    def test_a_twin_lands_next_to_its_original(self, mock_universe_df, reference):
        [twin] = place(reference, _row(mock_universe_df, "VAL.DE", symbol="TWIN"), CFG).to_dict(
            "records"
        )
        original = reference[reference["symbol"] == "VAL.DE"].iloc[0]
        n = len(reference)
        for name in FACTORS:
            if pd.notna(original[f"rank_{name}"]):
                assert twin[f"rank_{name}"] == pytest.approx(original[f"rank_{name}"], abs=1 / n)
        assert twin["composite_score"] == pytest.approx(original["composite_score"], abs=1 / n)

    def test_better_than_all_gets_the_top_rank_of_n_plus_one(self, mock_universe_df, reference):
        best = _row(
            mock_universe_df,
            "MID.DE",
            symbol="BEST",
            ev_ebit=0.01,
            pb_ratio=0.01,
            p_fcf=0.01,
            shareholder_yield=9.0,
            roic=9.0,
            fcf_margin=9.0,
            operating_margin=9.0,
            net_debt_ebitda=-99.0,
            earnings_stability=9.0,
        )
        [placed] = place(reference, best, CFG).to_dict("records")
        for name, (col, direction) in FACTORS.items():
            positive = direction == "low" and name in CFG.value_factors
            n = _valid_count(reference, col, positive=positive)
            expected = 1.0 if direction == "high" else 1 - 1 / (n + 1)
            assert placed[f"rank_{name}"] == pytest.approx(expected), name
        assert placed["composite_percentile"] == 1.0

    def test_worse_than_all_gets_the_bottom_rank_of_n_plus_one(self, mock_universe_df, reference):
        worst = _row(
            mock_universe_df,
            "MID.DE",
            symbol="WORST",
            ev_ebit=999.0,
            pb_ratio=999.0,
            p_fcf=999.0,
            shareholder_yield=-9.0,
            roic=-9.0,
            fcf_margin=-9.0,
            operating_margin=-9.0,
            net_debt_ebitda=999.0,
            earnings_stability=-9.0,
        )
        [placed] = place(reference, worst, CFG).to_dict("records")
        for name, (col, direction) in FACTORS.items():
            positive = direction == "low" and name in CFG.value_factors
            n = _valid_count(reference, col, positive=positive)
            expected = 1 / (n + 1) if direction == "high" else 0.0
            assert placed[f"rank_{name}"] == pytest.approx(expected), name

    def test_the_reference_does_not_change(self, mock_universe_df, reference):
        before = reference.copy()
        place(reference, _row(mock_universe_df, "VAL.DE", symbol="TWIN"), CFG)
        pd.testing.assert_frame_equal(reference, before)

    def test_each_candidate_alone(self, mock_universe_df, reference):
        """Zwei Kandidaten sehen einander nicht: jeder wird allein eingeordnet."""
        one = place(reference, _row(mock_universe_df, "VAL.DE", symbol="A"), CFG)
        two = place(
            reference,
            pd.concat(
                [
                    _row(mock_universe_df, "VAL.DE", symbol="A"),
                    _row(mock_universe_df, "VAL.DE", symbol="B"),
                ],
                ignore_index=True,
            ),
            CFG,
        )
        assert two.iloc[0]["composite_score"] == pytest.approx(one.iloc[0]["composite_score"])
        assert two.iloc[1]["composite_score"] == pytest.approx(one.iloc[0]["composite_score"])


class TestRules:
    def test_a_negative_multiple_does_not_count(self, mock_universe_df, reference):
        [placed] = place(
            reference, _row(mock_universe_df, "VAL.DE", symbol="LOSS", ev_ebit=-5.0), CFG
        ).to_dict("records")
        assert math.isnan(placed["rank_ev_ebit"])

    def test_no_composite_without_quality(self, mock_universe_df, reference):
        nothing = {col: np.nan for name, (col, _) in CFG.quality_factors.items()}
        [placed] = place(
            reference, _row(mock_universe_df, "VAL.DE", symbol="BANK", **nothing), CFG
        ).to_dict("records")
        assert not math.isnan(placed["value_score"])
        assert math.isnan(placed["quality_score"])
        assert math.isnan(placed["composite_score"])
        assert math.isnan(placed["composite_percentile"])
        assert placed["reason"] == "no_quality"

    def test_without_value_and_without_any(self, mock_universe_df, reference):
        no_value = {col: np.nan for _, (col, _) in CFG.value_factors.items()}
        no_quality = {col: np.nan for _, (col, _) in CFG.quality_factors.items()}
        value_missing, all_missing = place(
            reference,
            pd.concat(
                [
                    _row(mock_universe_df, "VAL.DE", symbol="X", **no_value),
                    _row(mock_universe_df, "VAL.DE", symbol="Y", **no_value, **no_quality),
                ],
                ignore_index=True,
            ),
            CFG,
        ).to_dict("records")
        assert (value_missing["reason"], all_missing["reason"]) == ("no_value", "no_data")

    def test_the_value_trap_like_in_the_ranking(self, mock_universe_df, reference):
        [placed] = place(reference, _row(mock_universe_df, "TRAP.DE", symbol="TRAP2"), CFG).to_dict(
            "records"
        )
        trap = reference[reference["symbol"] == "TRAP.DE"].iloc[0]
        assert bool(trap["value_trap_flag"]) is True
        assert placed["value_trap_flag"] is True
        assert placed["value_trap_reason"] == "quality"

    def test_the_size_filter_does_not_exclude(self, mock_universe_df, reference):
        [placed] = place(reference, _row(mock_universe_df, "SMALL.DE"), CFG).to_dict("records")
        assert placed["symbol"] == "SMALL.DE"
        assert not math.isnan(placed["value_score"])

    def test_the_industry_rule_like_in_the_ranking(self, mock_universe_df):
        cfg = ScoringConfig(industry_rules=True)
        reference = score(mock_universe_df, cfg)
        bank = _row(mock_universe_df, "VAL.DE", symbol="BANK", industry="Banks - Regional")
        [placed] = place(reference, bank, cfg).to_dict("records")
        assert placed["industry_rule"] is True
        assert math.isnan(placed["rank_ev_ebit"])
        assert not math.isnan(placed["rank_pb"])

    def test_nothing_to_place(self, mock_universe_df, reference):
        assert place(reference, mock_universe_df.iloc[0:0], CFG).empty
        assert place(reference.iloc[0:0], mock_universe_df, CFG).empty


def test_composite_percentiles():
    out = composite_percentiles(pd.Series([0.2, np.nan, 0.8, 0.5]))
    assert out.tolist()[0:1] + out.tolist()[2:] == pytest.approx([1 / 3, 1.0, 2 / 3])
    assert math.isnan(out.iloc[1])
