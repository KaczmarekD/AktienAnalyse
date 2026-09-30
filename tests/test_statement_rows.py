"""Umwandlung der yfinance-Statements in Zeilen fuer statement_value (ohne Datenbank)."""

from __future__ import annotations

from datetime import date

import pandas as pd

from src.db.repositories.market_data import _statement_rows


def test_columns_without_valid_period_are_skipped():
    # yfinance liefert gelegentlich Spalten ohne Datum; die duerfen nicht als NaT in die DB
    income = pd.DataFrame(
        {pd.Timestamp("2025-12-31"): [1000.0], None: [2000.0], "NaT": [3000.0]},
        index=["Total Revenue"],
    )
    rows = _statement_rows({"income": income})
    assert rows == {("income", "Total Revenue", date(2025, 12, 31)): 1000.0}


def test_numeric_column_labels_are_no_periods():
    # pd.Timestamp(0) waere 1970-01-01 - ein RangeIndex darf keine Scheinperiode erzeugen
    income = pd.DataFrame(
        {0: [1000.0], 1: [900.0], pd.Timestamp("2025-12-31"): [800.0]},
        index=["Total Revenue"],
    )
    rows = _statement_rows({"income": income})
    assert rows == {("income", "Total Revenue", date(2025, 12, 31)): 800.0}
