"""Parameter eines Bewertungslaufs aus seiner gespeicherten Konfiguration (Track G, G3).

``scoring.scoring_run.config`` ist ``asdict(ScoringConfig)``, JSON-sicher gespeichert. Das web-api
(Tabellen-Pfad) und der Backfill lesen daraus die Parameter, die das UI in Tooltips nennt.
"""

from __future__ import annotations

import json
from dataclasses import asdict, replace

from va_contracts.profile import ProfileParamsV1, params_from_config
from va_scoring.domain.profile import ScoringProfileParams
from va_scoring.domain.scoring import ScoringConfig


def _stored(cfg: ScoringConfig) -> dict:
    # Wie das Repository speichert: Tupel werden Listen
    return json.loads(json.dumps(asdict(cfg), default=list))


def test_parameters_of_a_stored_config_match_the_profile() -> None:
    cfg = replace(ScoringConfig(), value_weight=0.7, quality_weight=0.3, min_market_cap=5e8)
    params = params_from_config(_stored(cfg))
    expected = ScoringProfileParams.from_config(cfg)
    assert params is not None
    assert type(params) is ProfileParamsV1
    assert params.model_dump() == ProfileParamsV1.model_validate(expected.model_dump()).model_dump()


def test_without_usable_config_there_are_no_parameters() -> None:
    assert params_from_config(None) is None
    assert params_from_config({}) is None  # importierte Altdaten
    assert params_from_config({"value_weight": 2.0}) is None  # verletzt die Regeln
    broken = _stored(ScoringConfig())
    broken["value_factors"] = {"gibts_nicht": ["x", "low"]}
    assert params_from_config(broken) is None
