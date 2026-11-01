"""Parameter eines Scoring-Profils (P2b.1, P2b.2, ADR-0009).

P2b.1: die Parameter aus der heutigen ``ScoringConfig``. P2b.2: ``ScoringProfileParams`` prueft
sie und bildet sie auf ``score()`` ab.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, get_args

import pytest
from pydantic import ValidationError

from va_scoring.domain.profile import (
    DEFAULT_PROFILE_NAME,
    QualityFactorKey,
    ScoringProfileParams,
    ValueFactorKey,
    profile_params,
)
from va_scoring.domain.scoring import (
    DEFAULT_QUALITY_FACTORS,
    DEFAULT_VALUE_FACTORS,
    ScoringConfig,
    score,
)

if TYPE_CHECKING:
    import pandas as pd


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


# --- P2b.2 ScoringProfileParams --------------------------------------------------------------

ALL_VALUE = set(DEFAULT_VALUE_FACTORS)
ALL_QUALITY = set(DEFAULT_QUALITY_FACTORS)


def _params(**values: Any) -> ScoringProfileParams:
    """Wie gespeicherte oder vom UI geschickte params: Faktoren als einfache Strings."""
    return ScoringProfileParams.model_validate(values)


class TestCatalog:
    def test_factor_keys_are_the_catalog_in_the_code(self):
        # Neue Faktoren bleiben Code-Aenderungen (ADR-0009): Katalog und Literal gehen zusammen
        assert set(get_args(ValueFactorKey)) == ALL_VALUE
        assert set(get_args(QualityFactorKey)) == ALL_QUALITY


class TestDefaults:
    def test_are_todays_scoring_config(self):
        cfg = ScoringProfileParams().to_config()
        assert cfg == ScoringConfig()
        # Gleiche Reihenfolge der Faktoren wie im Katalog: Golden-Files bleiben gleich
        assert list(cfg.value_factors) == list(DEFAULT_VALUE_FACTORS)
        assert list(cfg.quality_factors) == list(DEFAULT_QUALITY_FACTORS)

    def test_quality_weight_is_the_rest(self):
        cfg = ScoringProfileParams(value_weight=0.7).to_config()
        assert cfg.value_weight == 0.7
        assert cfg.quality_weight == pytest.approx(0.3)

    def test_stored_standard_from_p2b1_stays_valid(self):
        params = ScoringProfileParams.model_validate(profile_params(ScoringConfig()))
        assert params == ScoringProfileParams()

    def test_profile_params_go_through_the_model(self):
        cfg = ScoringConfig(value_weight=0.5, quality_weight=0.5, min_market_cap=1e9)
        params = profile_params(cfg)
        assert ScoringProfileParams.model_validate(params).to_config() == cfg


class TestJson:
    def test_factors_are_sorted_lists(self):
        params = _params(
            value_factors={"shareholder_yield", "ev_ebit"}, quality_factors={"roic", "fcf_margin"}
        )
        dumped = params.model_dump(mode="json")
        assert dumped["value_factors"] == ["ev_ebit", "shareholder_yield"]
        assert dumped["quality_factors"] == ["fcf_margin", "roic"]

    def test_round_trip_through_json(self):
        params = _params(value_weight=0.55, value_factors={"pb", "p_fcf"})
        text = json.dumps(params.model_dump(mode="json"))
        assert ScoringProfileParams.model_validate(json.loads(text)) == params


class TestRules:
    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("value_weight", -0.1),
            ("value_weight", 1.1),
            ("min_market_cap", -1),
            ("min_value_factor_share", 1.5),
            ("min_quality_factor_share", -0.5),
            ("value_trap_value_threshold", 2),
            ("value_trap_quality_threshold", -1),
            ("min_factor_count", 0),
        ],
    )
    def test_bounds(self, field: str, value: Any):
        with pytest.raises(ValidationError, match=field):
            ScoringProfileParams.model_validate({field: value})

    def test_unknown_factor_is_rejected(self):
        with pytest.raises(ValidationError, match="value_factors"):
            ScoringProfileParams.model_validate({"value_factors": ["ev_ebit", "pe_ratio"]})

    def test_unknown_field_is_rejected(self):
        # Ein Tippfehler in gespeicherten params darf nicht still wegfallen
        with pytest.raises(ValidationError, match="value_wieght"):
            ScoringProfileParams.model_validate({"value_wieght": 0.5})

    @pytest.mark.parametrize("group", ["value_factors", "quality_factors"])
    def test_at_least_two_factors_per_group(self, group: str):
        keys = sorted(ALL_VALUE if group == "value_factors" else ALL_QUALITY)
        with pytest.raises(ValidationError, match="mindestens 2"):
            ScoringProfileParams.model_validate({group: keys[:1]})

    def test_not_fewer_factors_than_min_factor_count(self):
        # Sonst entstuende nie ein Score
        with pytest.raises(ValidationError, match="min_factor_count"):
            _params(min_factor_count=3, value_factors={"ev_ebit", "pb"})

    def test_is_immutable(self):
        params = ScoringProfileParams()
        with pytest.raises(ValidationError):
            params.value_weight = 0.5  # type: ignore[misc]


class TestDisabledFactor:
    """Ein abgeschalteter Faktor faellt aus Ranking und Mittelwert, die uebrigen bleiben."""

    def test_disabled_factor_has_no_rank(self, mock_universe_df: pd.DataFrame):
        cfg = _params(value_factors=ALL_VALUE - {"pb"}).to_config()
        out = score(mock_universe_df, cfg)
        assert "rank_pb" not in out.columns
        assert {"rank_ev_ebit", "rank_p_fcf", "rank_shareholder_yield"} <= set(out.columns)

    def test_value_score_is_the_mean_of_the_remaining_factors(self, mock_universe_df: pd.DataFrame):
        cfg = _params(value_factors={"ev_ebit", "p_fcf"}).to_config()
        out = score(mock_universe_df, cfg)
        both = out[out["rank_ev_ebit"].notna() & out["rank_p_fcf"].notna()]
        assert not both.empty
        expected = (both["rank_ev_ebit"] + both["rank_p_fcf"]) / 2
        assert both["value_score"].tolist() == pytest.approx(expected.tolist())

    def test_changes_the_ranking(self, mock_universe_df: pd.DataFrame):
        default = score(mock_universe_df, ScoringProfileParams().to_config())
        without_pb = score(mock_universe_df, _params(value_factors=ALL_VALUE - {"pb"}).to_config())
        before = default.set_index("symbol")["value_score"]
        after = without_pb.set_index("symbol")["value_score"].reindex(before.index)
        assert not before.equals(after)


# --- P3.3: Katalog fuer das UI, Modell als Contract ------------------------------------------


def test_every_factor_has_label_and_hint():
    from va_scoring.domain.profile import FACTOR_INFO

    assert set(FACTOR_INFO) == ALL_VALUE | ALL_QUALITY
    assert all(label and hint for label, hint in FACTOR_INFO.values())


def test_params_are_the_shared_contract():
    # Das web-api kennt nur den Contract; scoring ergaenzt die Abbildung auf score()
    from va_contracts.profile import ProfileParamsV1

    assert issubclass(ScoringProfileParams, ProfileParamsV1)
    stored = ProfileParamsV1().model_dump(mode="json")
    assert ScoringProfileParams.model_validate(stored).to_config() == ScoringConfig()
