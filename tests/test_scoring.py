"""Tests fuer die Scoring-Engine."""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.scoring import (
    DEFAULT_QUALITY_FACTORS,
    DEFAULT_VALUE_FACTORS,
    ScoringConfig,
    _composite_mean,
    _percentile_rank,
    score,
)


class TestPercentileRank:
    def test_low_direction_inverts(self):
        s = pd.Series([10.0, 5.0, 1.0])
        r = _percentile_rank(s, direction="low", drop_non_positive=True)
        # Niedrigster Wert (1) sollte den hoechsten Rank haben
        assert r.iloc[2] > r.iloc[0]

    def test_high_direction_keeps(self):
        s = pd.Series([10.0, 5.0, 1.0])
        r = _percentile_rank(s, direction="high", drop_non_positive=False)
        assert r.iloc[0] > r.iloc[2]

    def test_nan_stays_nan(self):
        s = pd.Series([1.0, np.nan, 3.0])
        r = _percentile_rank(s, direction="high", drop_non_positive=False)
        assert pd.isna(r.iloc[1])

    def test_drop_non_positive_for_value_metrics(self):
        # Negative Werte (Verluste) sollen aus dem Ranking ausgeschlossen werden
        s = pd.Series([10.0, -5.0, 2.0])
        r = _percentile_rank(s, direction="low", drop_non_positive=True)
        assert pd.isna(r.iloc[1])
        assert not pd.isna(r.iloc[0])
        assert not pd.isna(r.iloc[2])

    def test_drop_non_positive_false_keeps_negatives(self):
        s = pd.Series([10.0, -5.0, 2.0])
        r = _percentile_rank(s, direction="high", drop_non_positive=False)
        assert not pd.isna(r.iloc[1])


class TestCompositeMean:
    def test_min_share_filters_sparse_rows(self):
        df = pd.DataFrame(
            {
                "f1": [1.0, np.nan, 1.0],
                "f2": [1.0, np.nan, 1.0],
                "f3": [1.0, 1.0, np.nan],
                "f4": [1.0, 1.0, np.nan],
            },
        )
        # Zeile 1 hat nur 2/4 = 50 %, mit min_share 0.6 -> NaN
        score_s = _composite_mean(df, min_share=0.6)
        assert pd.isna(score_s.iloc[1])
        assert not pd.isna(score_s.iloc[0])

    def test_empty_df(self):
        result = _composite_mean(pd.DataFrame(), min_share=0.5)
        assert result.empty


class TestScoreEndToEnd:
    def test_market_cap_filter(self, mock_universe_df):
        out = score(mock_universe_df, ScoringConfig(min_market_cap=300_000_000))
        symbols = set(out["symbol"])
        assert "SMALL.DE" not in symbols  # market_cap 100 Mio
        assert "VAL.DE" in symbols

    def test_value_co_ranks_top(self, mock_universe_df):
        out = score(mock_universe_df, ScoringConfig())
        # Value Co kombiniert guenstige Bewertung mit hoher Qualitaet
        assert out.iloc[0]["symbol"] == "VAL.DE"

    def test_value_trap_flag(self, mock_universe_df):
        out = score(mock_universe_df, ScoringConfig())
        trap_row = out[out["symbol"] == "TRAP.DE"].iloc[0]
        assert bool(trap_row["value_trap_flag"]) is True

    def test_loss_maker_no_score(self, mock_universe_df):
        out = score(mock_universe_df, ScoringConfig())
        loss_row = out[out["symbol"] == "LOSS.DE"].iloc[0]
        # Loss-Maker hat negative Value-Metriken -> Value-Score sehr niedrig
        # und sollte definitiv NICHT auf Platz 1 stehen
        assert loss_row["rank_overall"] > out["rank_overall"].median()

    def test_rank_overall_continuous(self, mock_universe_df):
        out = score(mock_universe_df, ScoringConfig())
        assert list(out["rank_overall"]) == list(range(1, len(out) + 1))

    def test_weights_normalised(self, mock_universe_df):
        out = score(mock_universe_df, ScoringConfig(value_weight=0.6, quality_weight=0.4))
        composites = out["composite_score"].dropna()
        # Alle Composites sollten im Bereich [0,1] liegen
        assert (composites >= 0).all() and (composites <= 1).all()

    def test_custom_factor_config(self, mock_universe_df):
        # Custom Faktoren-Set (Minimum 2 wegen min_factor_share)
        cfg = ScoringConfig(
            value_factors={
                "ev_ebit": ("ev_ebit", "low"),
                "pb": ("pb_ratio", "low"),
            }
        )
        out = score(mock_universe_df, cfg)
        assert out["value_score"].notna().sum() > 0


class TestDefaultFactors:
    def test_default_value_factors_complete(self):
        assert "ev_ebit" in DEFAULT_VALUE_FACTORS
        assert "shareholder_yield" in DEFAULT_VALUE_FACTORS
        # Direction muss "low" oder "high" sein
        for col, direction in DEFAULT_VALUE_FACTORS.values():
            assert direction in ("low", "high")
            assert isinstance(col, str)

    def test_default_quality_factors_complete(self):
        assert "roic" in DEFAULT_QUALITY_FACTORS
        for col, direction in DEFAULT_QUALITY_FACTORS.values():
            assert direction in ("low", "high")
