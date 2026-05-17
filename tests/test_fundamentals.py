"""Tests fuer das Datenmodell."""

from __future__ import annotations

from src.fundamentals import (
    Fundamentals,
    Growth,
    Identity,
    MarketData,
    QualityMetrics,
    ValueMetrics,
)


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
