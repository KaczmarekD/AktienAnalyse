"""Hilfsfunktionen des Market-Data-Repositories, die keine Datenbank brauchen."""

from __future__ import annotations

import pandas as pd
import pytest

from src.db.repositories.market_data import _join_errors


@pytest.mark.parametrize(
    ("errors", "expected"),
    [
        (["fx USD->EUR failed", "fetch failed"], "fx USD->EUR failed; fetch failed"),
        ([], ""),
        (None, ""),
        # Fehlende Werte kommen je nach pandas-Version als NA oder NaN an
        (pd.NA, ""),
        (float("nan"), ""),
    ],
)
def test_join_errors(errors, expected):
    assert _join_errors(errors) == expected
