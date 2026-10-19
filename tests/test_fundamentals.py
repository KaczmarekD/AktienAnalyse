"""Tests fuer das Datenmodell."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pandas as pd
import pytest

from src.fundamentals import (
    Fundamentals,
    Growth,
    Identity,
    MarketData,
    Provenance,
    QualityMetrics,
    RawFetch,
    ValueMetrics,
    join_errors,
)


@pytest.mark.parametrize(
    ("errors", "expected"),
    [
        (["fx USD->EUR failed", "fetch failed"], "fx USD->EUR failed; fetch failed"),
        (("fetch failed",), "fetch failed"),  # ARRAY-Spalten koennen als Tupel kommen
        ([], ""),
        # Defensiv: kein Text daraus machen, wenn gar keine Liste ankommt
        (None, ""),
        (pd.NA, ""),
        (float("nan"), ""),
    ],
)
def test_join_errors(errors, expected):
    assert join_errors(errors) == expected


class TestFundamentals:
    def test_minimal_construction(self):
        f = Fundamentals(identity=Identity(symbol="X.DE", name="X", index="DAX"))
        assert f.symbol == "X.DE"
        assert f.value.ev_ebit is None

    def test_to_flat_dict_contains_all_fields(self):
        f = Fundamentals(
            identity=Identity(symbol="X.DE", name="X", index="DAX", sector="Tech"),
            market=MarketData(market_cap=1e9, price=42.0),
            value=ValueMetrics(ev_ebit=10.0, dividend_yield=0.03),
            quality=QualityMetrics(roic=0.15),
            growth=Growth(revenue_growth_5y=0.05),
        )
        flat = f.to_flat_dict()
        assert flat["symbol"] == "X.DE"
        assert flat["sector"] == "Tech"
        assert flat["market_cap"] == 1e9
        assert flat["ev_ebit"] == 10.0
        assert flat["roic"] == 0.15
        assert flat["revenue_growth_5y"] == 0.05
        assert flat["errors"] == ""

    def test_to_flat_dict_serialises_errors(self):
        f = Fundamentals(identity=Identity(symbol="X.DE", name="X", index="DAX"))
        f.errors.append("fetch failed")
        f.errors.append("parse failed")
        flat = f.to_flat_dict()
        assert "fetch failed" in flat["errors"]
        assert "parse failed" in flat["errors"]

    def test_to_flat_dict_contains_provenance(self):
        fetched = datetime(2026, 10, 3, 5, 30, tzinfo=UTC)
        f = Fundamentals(
            identity=Identity(symbol="X.DE", name="X", index="DAX"),
            provenance=Provenance(
                fetched_at=fetched, fiscal_period_end=date(2025, 12, 31), statement_fx=0.9
            ),
        )
        flat = f.to_flat_dict()
        assert flat["fetched_at"] == fetched
        assert flat["fiscal_period_end"] == date(2025, 12, 31)
        assert flat["statement_fx"] == 0.9

    def test_raw_data_is_not_flattened(self):
        f = Fundamentals(identity=Identity(symbol="X.DE", name="X", index="DAX"))
        f.raw = RawFetch(
            provider="yfinance",
            provider_version="0.2.66",
            info={"marketCap": 1.0},
            statements={"income": pd.DataFrame()},
        )
        flat = f.to_flat_dict()
        assert "raw" not in flat
        assert "info" not in flat
