"""Tests fuer das Universum-Modul."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from src.universe import Ticker, _dedupe, load_fallback, load_universe


@pytest.fixture
def temp_fallback_csv(tmp_path: Path) -> Path:
    path = tmp_path / "fallback.csv"
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["symbol", "name", "index"])
        w.writerow(["AAA.DE", "Alpha", "DAX"])
        w.writerow(["BBB.DE", "Beta", "DAX"])
        w.writerow(["CCC.DE", "Gamma", "MDAX"])
    return path


class TestLoadFallback:
    def test_loads_csv(self, temp_fallback_csv):
        tickers = load_fallback(temp_fallback_csv)
        assert len(tickers) == 3
        assert tickers[0].symbol == "AAA.DE"
        assert tickers[0].name == "Alpha"
        assert tickers[0].index == "DAX"

    def test_missing_file(self, tmp_path):
        result = load_fallback(tmp_path / "doesnt-exist.csv")
        assert result == []

    def test_real_repo_fallback_has_no_dupes(self):
        # Realer Fallback in data/ - wenn er existiert, muss er dedupliziert sein
        repo_csv = Path(__file__).resolve().parent.parent / "data" / "dax_mdax_fallback.csv"
        if not repo_csv.exists():
            pytest.skip("Realer Fallback nicht vorhanden")
        tickers = load_fallback(repo_csv)
        symbols = [t.symbol for t in tickers]
        assert len(symbols) == len(set(symbols)), "Duplikate im Repo-Fallback"


class TestDedupe:
    def test_keeps_first_occurrence(self):
        ts = [
            Ticker("A.DE", "Alpha-1", "DAX"),
            Ticker("A.DE", "Alpha-2", "MDAX"),
            Ticker("B.DE", "Beta", "DAX"),
        ]
        result = _dedupe(ts)
        assert len(result) == 2
        assert result[0].name == "Alpha-1"

    def test_empty(self):
        assert _dedupe([]) == []


class TestLoadUniverseForceFallback:
    def test_force_fallback_works_without_network(self, temp_fallback_csv):
        tickers = load_universe(force_fallback=True, fallback_csv=temp_fallback_csv)
        assert len(tickers) == 3
        assert all(isinstance(t, Ticker) for t in tickers)
