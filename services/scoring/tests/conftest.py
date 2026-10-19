"""Fixtures fuer die Scoring-Tests (Kopie aus tests/conftest.py, die Root-Tests nutzen sie weiter)."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest


@pytest.fixture
def mock_universe_df() -> pd.DataFrame:
    """Repraesentatives 8-Werte-Universum mit allen Profilen."""
    # Eine Quelle fuer Root- und Scoring-Tests (vorher zwei identische Kopien)
    return pd.DataFrame(
        json.loads(
            (Path(__file__).parent / "fixtures" / "mock_universe.json").read_text(encoding="utf-8")
        )
    )
