"""Replay-Regression über echte, gespeicherte Wochen (P2b.0).

Jede Datei unter ``tests/fixtures/replay/`` ist ein Bewertungslauf, exportiert mit
``python -m src.regression --export``: die Snapshots des Abrufs und das gespeicherte
Ergebnis. Der aktuelle Code muss jede Woche gleich bewerten.

Eine gewollte Änderung der Methodik (Phase 2b, ADR-0011) schreibt die erwarteten Werte mit
``pytest tests/test_replay_fixtures.py --update-golden`` neu. Die Snapshots bleiben, der
Diff wird im Review begründet. In der CI ist das verboten.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from src.regression.case import ReplayCase
from src.regression.cli import format_outcome
from src.regression.replay import check, replay
from va_scoring.domain.profile import ScoringProfileParams
from va_scoring.domain.scoring import ScoringConfig

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "replay"
FIXTURES = sorted(FIXTURE_DIR.glob("*.json"))
# Kommen auf der NAS aus der .env (Settings); alles andere ist Methodik und kommt aus dem Code
DEPLOYMENT_KEYS = ("min_market_cap", "value_weight", "quality_weight")


def _config(case: ReplayCase) -> ScoringConfig:
    """Die Einstellungen des Deployments wie in der gespeicherten Woche, sonst die Standards."""
    stored = case.config or {}
    return ScoringConfig(**{k: stored[k] for k in DEPLOYMENT_KEYS if k in stored})


def test_there_is_at_least_one_real_week():
    assert FIXTURES, f"keine Fixture unter {FIXTURE_DIR} - mit --export anlegen"


@pytest.mark.parametrize("path", FIXTURES, ids=lambda p: p.stem)
def test_week_is_scored_unchanged(path: Path, request: pytest.FixtureRequest):
    case = ReplayCase.from_json(path.read_text(encoding="utf-8"))
    cfg = _config(case)
    outcome = check(case, cfg)
    if request.config.getoption("--update-golden"):
        if os.environ.get("CI"):
            pytest.fail("--update-golden ist in der CI verboten")
        if outcome.equal:
            return
        renewed = case.with_expected(replay(case, cfg))
        path.write_text(renewed.to_json(), encoding="utf-8", newline="\n")
        pytest.skip(f"Erwartete Werte neu geschrieben: {path.name} - Diff im Review begruenden")
    assert outcome.equal, format_outcome(outcome)


@pytest.mark.parametrize("path", FIXTURES, ids=lambda p: p.stem)
def test_week_is_scored_unchanged_with_the_standard_profile(path: Path):
    # P2b.2: Das Profil "Standard" mit den Werten des Deployments rechnet wie bisher (P2b.3
    # stellt das Scoring darauf um, ohne dass sich eine Woche aendert)
    case = ReplayCase.from_json(path.read_text(encoding="utf-8"))
    stored = case.config or {}
    params = ScoringProfileParams(
        **{k: stored[k] for k in ("min_market_cap", "value_weight") if k in stored}
    )
    outcome = check(case, params.to_config())
    assert outcome.equal, format_outcome(outcome)
