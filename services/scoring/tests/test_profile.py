"""Parameter eines Scoring-Profils (P2b.1, ADR-0009) aus der heutigen ``ScoringConfig``."""

from __future__ import annotations

import json

from va_scoring.domain.profile import DEFAULT_PROFILE_NAME, profile_params
from va_scoring.domain.scoring import ScoringConfig


def test_default_profile_is_called_standard():
    assert DEFAULT_PROFILE_NAME == "Standard"


def test_params_of_todays_defaults():
    assert profile_params(ScoringConfig()) == {
        "value_weight": 0.6,
        "min_market_cap": 300_000_000.0,
        "min_value_factor_share": 0.5,
        "min_quality_factor_share": 0.5,
        "min_factor_count": 2,
        "value_trap_value_threshold": 0.70,
        "value_trap_quality_threshold": 0.30,
        "drop_negative_value_metrics": True,
        "value_factors": ["ev_ebit", "p_fcf", "pb", "shareholder_yield"],
        "quality_factors": [
            "earnings_stability",
            "fcf_margin",
            "net_debt_ebitda",
            "operating_margin",
            "roic",
        ],
    }


def test_values_from_the_environment_are_taken_over():
    cfg = ScoringConfig(value_weight=0.5, quality_weight=0.5, min_market_cap=1e9)
    params = profile_params(cfg)
    assert (params["value_weight"], params["min_market_cap"]) == (0.5, 1e9)


def test_only_factor_keys_no_columns_or_directions():
    # Katalog und Richtung der Faktoren bleiben im Code (ADR-0009)
    params = profile_params(ScoringConfig())
    assert all(isinstance(key, str) for key in params["value_factors"])
    assert "quality_weight" not in params  # immer 1 - value_weight


def test_params_are_plain_json():
    params = profile_params(ScoringConfig())
    assert json.loads(json.dumps(params)) == params
