"""Universum im Batch (P1.4): die Repo-CSV und die Verdrahtung in ``src.composition``.

Kette iShares -> Deka -> CSV mit den echten Adaptern, nur ihr Netzzugriff ist ersetzt.
"""

from __future__ import annotations

import csv
import io
from datetime import date
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pandas as pd
import pytest

from src.composition import DEFAULT_FALLBACK_CSV, load_universe
from va_market_data.adapters.csv_universe import load_fallback
from va_market_data.domain.universe import (
    FALLBACK_SOURCE,
    SourceError,
    Universe,
    UniverseConfig,
)

TODAY = date(2026, 9, 30)
# Kleine Indizes halten die Fixtures uebersichtlich
CFG = UniverseConfig(expected_counts={"DAX": 2, "MDAX": 1}, max_age_days=10)

DAX_ROWS = [
    # (ticker, isin, issueName, assetClass)
    ("SAP", "DE0007164600", "SAP", "Aktien"),
    ("SIE", "DE0007236101", "SIEMENS N AG", "Aktien"),
    ("EUR", None, "EUR CASH", "Geldmarkt"),
    ("GXZ6", "DE000F0GDWD2", "DAX INDEX DEC 26", "Futures"),
]
MDAX_ROWS = [
    ("SAX", "DE0007493991", "STROEER SE + CO KGAA", "Aktien"),
    ("MFLZ6", "DE000F3E21M2", "MDAX MINI DEC 26", "Futures"),
]


def _ishares_payload(rows: list[tuple[Any, ...]], as_of: int = 20260929) -> dict[str, Any]:
    """Baut die spaltenweise iShares-Struktur nach."""

    def dp(values: list[Any]) -> dict[str, Any]:
        return {"value": values, "formattedValue": values}

    points = {
        "ticker": dp([r[0] for r in rows]),
        "isin": dp([r[1] for r in rows]),
        "issueName": dp([r[2] for r in rows]),
        "assetClass": dp([r[3] for r in rows]),
        "asOfDate": {"value": as_of},
    }
    return {
        "componentsByNameMap": {
            "holdings": {"containersByNameMap": {"all": {"dataPointsByNameMap": points}}}
        }
    }


def _deka_xlsx(rows: list[tuple[str, str]], sheet: str = "Indexzusammensetzung") -> bytes:
    """XLSX mit den drei Deka-Blaettern; rows = (Holding Name, ISIN)."""
    buf = io.BytesIO()
    index_df = pd.DataFrame(
        {
            "Holding Name": [r[0] for r in rows],
            "WKN": ["000000"] * len(rows),
            "ISIN": [r[1] for r in rows],
            "Gewichtung": [0.1] * len(rows),
        }
    )
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        pd.DataFrame({"x": [1]}).to_excel(writer, sheet_name="Fondszusammensetzung", index=False)
        index_df.to_excel(writer, sheet_name=sheet, index=False)
        pd.DataFrame({"x": [1]}).to_excel(writer, sheet_name="Lizenzhinweise", index=False)
    return buf.getvalue()


@pytest.fixture
def fallback_csv(tmp_path: Path) -> Path:
    path = tmp_path / "fallback.csv"
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["symbol", "name", "index", "isin"])
        w.writerow(["SAP.DE", "SAP", "DAX", "DE0007164600"])
        w.writerow(["SIE.DE", "Siemens", "DAX", "DE0007236101"])
        w.writerow(["BOSS.DE", "Hugo Boss", "MDAX", "DE000A1PHFF7"])
    return path


def _ishares_ok(index: str, timeout: float = 30.0) -> dict[str, Any]:
    return _ishares_payload(DAX_ROWS if index == "DAX" else MDAX_ROWS)


def _deka_ok(index: str, timeout: float = 30.0) -> bytes:
    if index == "DAX":
        return _deka_xlsx([("SAP SE", "DE0007164600"), ("SIEMENS AG-REG", "DE0007236101")])
    return _deka_xlsx([("STROEER SE + CO KGAA", "DE0007493991")])


# ---------------------------------------------------------------------------
# Fallback-CSV
# ---------------------------------------------------------------------------


class TestRepoFallbackCsv:
    """Der echte Fallback in data/ ist das Sicherheitsnetz - er muss vollstaendig sein."""

    TICKERS = load_fallback(DEFAULT_FALLBACK_CSV)

    def test_no_duplicates(self):
        symbols = [t.symbol for t in self.TICKERS]
        assert len(symbols) == len(set(symbols))

    def test_expected_index_sizes(self):
        default = UniverseConfig()
        for index, expected in default.expected_counts.items():
            assert sum(t.index == index for t in self.TICKERS) == expected

    def test_every_row_has_valid_isin(self):
        for t in self.TICKERS:
            assert t.isin is not None, t.symbol
            assert len(t.isin) == 12, t.symbol
            assert t.isin[:2].isalpha(), t.symbol


# ---------------------------------------------------------------------------
# iShares
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Deka + ISIN-Mapping
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# load_universe: Quellen-Kette + Abweichung zur CSV
# ---------------------------------------------------------------------------


def _fail(*_args, **_kwargs):
    msg = "Quelle nicht erreichbar"
    raise SourceError(msg)


class TestLoadUniverse:
    def _load(self, fallback_csv, ishares=_ishares_ok, deka=_deka_ok, figi=None):
        figi = figi or {"DE0007493991": "SAX.DE"}
        with (
            patch("va_market_data.adapters.ishares.fetch_ishares_json", side_effect=ishares),
            patch("va_market_data.adapters.deka.fetch_deka_xlsx", side_effect=deka),
            patch("src.composition.resolve_isins_openfigi", return_value=figi),
        ):
            return load_universe(cfg=CFG, fallback_csv=fallback_csv, today=TODAY)

    def test_ishares_is_primary(self, fallback_csv):
        uni = self._load(fallback_csv)
        assert isinstance(uni, Universe)
        assert uni.source == "iShares"
        assert uni.as_of == date(2026, 9, 29)
        assert [t.symbol for t in uni.tickers] == ["SAP.DE", "SIE.DE", "SAX.DE"]

    def test_deka_when_ishares_fails(self, fallback_csv):
        uni = self._load(fallback_csv, ishares=_fail)
        assert uni.source == "Deka"
        assert uni.as_of is None
        assert [t.symbol for t in uni.tickers] == ["SAP.DE", "SIE.DE", "SAX.DE"]
        assert uni.tickers[0].name == "SAP"  # Name aus CSV

    def test_csv_when_all_live_sources_fail(self, fallback_csv):
        uni = self._load(fallback_csv, ishares=_fail, deka=_fail)
        assert uni.source == FALLBACK_SOURCE
        assert [t.symbol for t in uni.tickers] == ["SAP.DE", "SIE.DE", "BOSS.DE"]
        assert uni.added == []
        assert uni.removed == []

    def test_one_failing_index_invalidates_whole_source(self, fallback_csv):
        def ishares_mdax_broken(index, timeout=None):
            return _ishares_ok(index) if index == "DAX" else _ishares_payload([])

        uni = self._load(fallback_csv, ishares=ishares_mdax_broken)
        assert uni.source == "Deka"

    def test_diff_against_csv(self, fallback_csv):
        uni = self._load(fallback_csv)
        assert [t.symbol for t in uni.added] == ["SAX.DE"]
        assert [t.symbol for t in uni.removed] == ["BOSS.DE"]

    def test_diff_detects_index_move(self, fallback_csv):
        # SIE.DE steigt laut Quelle in den MDAX ab - CSV fuehrt es noch im DAX
        def ishares_moved(index, timeout=None):
            rows = {"DAX": [DAX_ROWS[0], ("ADS", "DE000A1EWWW0", "ADIDAS", "Aktien")]}
            return _ishares_payload(rows.get(index, [DAX_ROWS[1]]))

        uni = self._load(fallback_csv, ishares=ishares_moved)
        assert ("SIE.DE", "MDAX") in [(t.symbol, t.index) for t in uni.added]
        assert ("SIE.DE", "DAX") in [(t.symbol, t.index) for t in uni.removed]

    def test_diff_detects_isin_change(self, fallback_csv):
        def ishares_new_isin(index, timeout=None):
            if index == "MDAX":
                return _ishares_ok(index)
            return _ishares_payload([DAX_ROWS[0], ("SIE", "DE000NEU00001", "SIEMENS", "Aktien")])

        uni = self._load(fallback_csv, ishares=ishares_new_isin)
        assert [t.isin for t in uni.added if t.symbol == "SIE.DE"] == ["DE000NEU00001"]
        assert [t.isin for t in uni.removed if t.symbol == "SIE.DE"] == ["DE0007236101"]

    def test_force_fallback_skips_network(self, fallback_csv):
        with (
            patch("va_market_data.adapters.ishares.fetch_ishares_json") as ishares,
            patch("va_market_data.adapters.deka.fetch_deka_xlsx") as deka,
        ):
            uni = load_universe(cfg=CFG, fallback_csv=fallback_csv, force_fallback=True)
        ishares.assert_not_called()
        deka.assert_not_called()
        assert uni.source == FALLBACK_SOURCE
