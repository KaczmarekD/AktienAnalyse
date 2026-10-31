"""Woher ein Bewertungslauf sein Profil nimmt (P2b.3, ADR-0009).

``StoredProfile``: die aktive Version aus der Datenbank, "Standard" bei Bedarf aus ENV angelegt.
``FixedProfile``: eine feste Konfiguration ohne Profil (Replay).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest
from pydantic import ValidationError

from va_scoring.application.profiles import FixedProfile, StoredProfile
from va_scoring.domain.profile import (
    ActiveProfile,
    ProfileVersionRef,
    ScoringProfileParams,
    profile_params,
)
from va_scoring.domain.scoring import ScoringConfig

DEFAULTS = profile_params(ScoringConfig())


class FakeProfiles:
    """``ProfileStore``: liefert eine feste aktive Version und merkt sich die Startwerte."""

    def __init__(self, ref: ProfileVersionRef) -> None:
        self.ref = ref
        self.calls: list[dict[str, Any]] = []

    def ensure_default_profile(self, params: Mapping[str, Any]) -> ProfileVersionRef:
        self.calls.append(dict(params))
        return self.ref


def test_stored_profile_scores_with_the_active_version():
    params = {**DEFAULTS, "value_weight": 0.5, "value_factors": ["ev_ebit", "pb"]}
    ref = ProfileVersionRef(1, "Standard", 3, params)
    active = StoredProfile(FakeProfiles(ref), DEFAULTS).active()
    assert active.ref == ref
    assert active.config == ScoringProfileParams.model_validate(params).to_config()
    assert (active.config.value_weight, list(active.config.value_factors)) == (
        0.5,
        ["ev_ebit", "pb"],
    )


def test_env_values_only_go_to_ensure_as_start_values():
    store = FakeProfiles(ProfileVersionRef(1, "Standard", 1, DEFAULTS))
    active = StoredProfile(store, {**DEFAULTS, "value_weight": 0.9}).active()
    assert store.calls == [{**DEFAULTS, "value_weight": 0.9}]
    assert active.config.value_weight == 0.6  # es gilt die gespeicherte Version


def test_each_call_reads_the_active_version_again():
    # Ein neu aktiviertes Profil gilt ab dem naechsten Bewertungslauf, ohne Neustart
    store = FakeProfiles(ProfileVersionRef(1, "Standard", 1, DEFAULTS))
    source = StoredProfile(store, DEFAULTS)
    source.active()
    store.ref = ProfileVersionRef(1, "Standard", 2, {**DEFAULTS, "value_weight": 0.5})
    assert source.active().config.value_weight == 0.5


def test_invalid_stored_params_fail_loudly():
    ref = ProfileVersionRef(1, "Standard", 1, {**DEFAULTS, "value_wieght": 0.5})
    with pytest.raises(ValidationError):
        StoredProfile(FakeProfiles(ref), DEFAULTS).active()


def test_fixed_profile_has_no_version():
    cfg = ScoringConfig(min_market_cap=1e9)
    active = FixedProfile(cfg).active()
    assert active == ActiveProfile(cfg)
    assert active.ref is None
    assert active.label is None


def test_label_names_profile_and_version():
    ref = ProfileVersionRef(1, "Standard", 1, DEFAULTS)
    assert ActiveProfile(ScoringConfig(), ref).label == "Standard v1"
