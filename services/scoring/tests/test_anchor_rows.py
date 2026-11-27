"""F3.1: Die Anker aus der Ausgabe des Handlers kommen im Long-Format in den Speicher."""

from __future__ import annotations

import numpy as np
import pandas as pd

from va_scoring.adapters.postgres import AnchorRow
from va_scoring.adapters.postgres.store import anchor_rows


def test_only_values_that_exist():
    scored = pd.DataFrame(
        [
            {"symbol": "SAP.DE", "price_to_epv": 3.8, "implied_fcf_growth": 0.08},
            {"symbol": "DBK.DE", "price_to_epv": np.nan, "implied_fcf_growth": None},
        ]
    )
    assert anchor_rows(scored, {"SAP.DE": 1, "DBK.DE": 2}) == [
        AnchorRow(1, "price_to_epv", 3.8),
        AnchorRow(1, "implied_fcf_growth", 0.08),
    ]


def test_without_anchor_columns_nothing():
    scored = pd.DataFrame([{"symbol": "SAP.DE", "composite_score": 0.7}])
    assert anchor_rows(scored, {"SAP.DE": 1}) == []
