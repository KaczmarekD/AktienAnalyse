"""Tests fuer das Universum-Modul (iShares -> Deka -> Fallback-CSV).

Kein Netz: Die Quell-Abrufe (_fetch_ishares_json, _fetch_deka_xlsx,
_openfigi_post) werden gepatcht, Payloads sind dem echten Format
nachgebaut (Stand 2026-09-29).
"""

from __future__ import annotations

import csv
import io
from datetime import date
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from src.universe import (
    FALLBACK_SOURCE,
    SourceError,
    Ticker,
    Universe,
    UniverseConfig,
    _dedupe,
    _fetch_ishares_json,
    _map_isins,
    load_fallback,
    load_universe,
    parse_deka,
    parse_ishares,
    resolve_isins_openfigi,
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


class TestLoadFallback:
    def test_loads_csv_with_isin(self, fallback_csv):
        tickers = load_fallback(fallback_csv)
        assert len(tickers) == 3
        assert tickers[0] == Ticker("SAP.DE", "SAP", "DAX", "DE0007164600")

    def test_isin_column_is_optional(self, tmp_path):
        path = tmp_path / "old.csv"
        path.write_text("symbol,name,index\nAAA.DE,Alpha,DAX\n", encoding="utf-8")
        assert load_fallback(path) == [Ticker("AAA.DE", "Alpha", "DAX")]

    def test_missing_file(self, tmp_path):
        assert load_fallback(tmp_path / "doesnt-exist.csv") == []


class TestRepoFallbackCsv:
    """Der echte Fallback in data/ ist das Sicherheitsnetz - er muss vollstaendig sein."""

    TICKERS = load_fallback()

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


class TestParseIshares:
    def test_extracts_equities_only(self):
        tickers, as_of = parse_ishares(_ishares_payload(DAX_ROWS), "DAX", {}, CFG, TODAY)
        assert [t.symbol for t in tickers] == ["SAP.DE", "SIE.DE"]
        assert all(t.index == "DAX" for t in tickers)
        assert tickers[0].isin == "DE0007164600"
        assert as_of == date(2026, 9, 29)

    def test_prefers_known_name_over_issue_name(self):
        tickers, _ = parse_ishares(
            _ishares_payload(DAX_ROWS), "DAX", {"DE0007236101": "Siemens"}, CFG, TODAY
        )
        assert tickers[1].name == "Siemens"
        assert tickers[0].name == "SAP"  # unbekannt -> issueName

    def test_wrong_count_raises(self):
        with pytest.raises(SourceError, match="1 statt 2"):
            parse_ishares(_ishares_payload(DAX_ROWS[:1]), "DAX", {}, CFG, TODAY)

    def test_stale_as_of_date_raises(self):
        with pytest.raises(SourceError, match="Stichtag"):
            parse_ishares(_ishares_payload(DAX_ROWS, as_of=20260901), "DAX", {}, CFG, TODAY)

    def test_future_as_of_date_raises(self):
        with pytest.raises(SourceError, match="Stichtag"):
            parse_ishares(_ishares_payload(DAX_ROWS, as_of=20270929), "DAX", {}, CFG, TODAY)

    def test_changed_structure_raises(self):
        with pytest.raises(SourceError, match="Struktur"):
            parse_ishares({"componentsByNameMap": {}}, "DAX", {}, CFG, TODAY)

    def test_html_with_status_200_raises(self):
        # September 2026: alte iShares-URLs lieferten HTML mit HTTP 200
        response = MagicMock()
        response.json.side_effect = ValueError("Expecting value")
        with (
            patch("src.universe._http_get", return_value=response),
            pytest.raises(SourceError, match="kein JSON"),
        ):
            _fetch_ishares_json("DAX", timeout=12.0)

    def test_timeout_is_passed_through(self):
        response = MagicMock()
        response.json.return_value = {}
        with patch("src.universe._http_get", return_value=response) as http_get:
            _fetch_ishares_json("MDAX", timeout=12.0)
        assert http_get.call_args.kwargs["timeout"] == 12.0


# ---------------------------------------------------------------------------
# Deka + ISIN-Mapping
# ---------------------------------------------------------------------------


class TestParseDeka:
    def test_reads_index_sheet(self):
        rows = parse_deka(_deka_ok("DAX"), "DAX", CFG)
        assert rows == [("SAP SE", "DE0007164600"), ("SIEMENS AG-REG", "DE0007236101")]

    def test_empty_name_falls_back_to_isin(self):
        content = _deka_xlsx([("", "DE0007164600"), ("SIEMENS AG-REG", "DE0007236101")])
        rows = parse_deka(content, "DAX", CFG)
        assert rows[0] == ("DE0007164600", "DE0007164600")

    def test_wrong_count_raises(self):
        with pytest.raises(SourceError, match="1 statt 2"):
            parse_deka(_deka_xlsx([("SAP SE", "DE0007164600")]), "DAX", CFG)

    def test_missing_sheet_raises(self):
        content = _deka_xlsx([("SAP SE", "DE0007164600")], sheet="Anderes Blatt")
        with pytest.raises(SourceError, match="Indexzusammensetzung"):
            parse_deka(content, "MDAX", CFG)

    def test_not_an_xlsx_raises(self):
        with pytest.raises(SourceError):
            parse_deka(b"<html>Wartungsarbeiten</html>", "DAX", CFG)


KNOWN_ISINS = {"DE0007164600": Ticker("SAP.DE", "SAP", "DAX", "DE0007164600")}


class TestMapIsins:
    def test_known_isin_uses_csv_symbol(self):
        resolver = MagicMock(return_value={})
        tickers = _map_isins([("SAP SE", "DE0007164600")], "DAX", KNOWN_ISINS, resolver)
        assert tickers == [Ticker("SAP.DE", "SAP", "DAX", "DE0007164600")]
        resolver.assert_not_called()

    def test_unknown_isin_resolved_via_resolver(self):
        resolver = MagicMock(return_value={"DE0007493991": "SAX.DE"})
        tickers = _map_isins([("STROEER SE", "DE0007493991")], "MDAX", KNOWN_ISINS, resolver)
        assert tickers == [Ticker("SAX.DE", "STROEER SE", "MDAX", "DE0007493991")]
        resolver.assert_called_once_with(["DE0007493991"])

    def test_unresolvable_isin_raises(self):
        resolver = MagicMock(return_value={})
        with pytest.raises(SourceError, match="DE0007493991"):
            _map_isins([("STROEER SE", "DE0007493991")], "MDAX", KNOWN_ISINS, resolver)


class TestOpenFigi:
    def test_maps_xetra_ticker_and_skips_errors(self):
        responses = [[{"data": [{"ticker": "SAX", "exchCode": "GY"}]}, {"error": "No match"}]]
        with patch("src.universe._openfigi_post", side_effect=responses):
            result = resolve_isins_openfigi(["DE0007493991", "XX0000000000"])
        assert result == {"DE0007493991": "SAX.DE"}

    def test_batches_of_ten(self):
        isins = [f"DE00000000{i:02d}" for i in range(11)]
        calls: list[list[dict[str, str]]] = []

        def fake_post(jobs, timeout=None):
            calls.append(jobs)
            return [{"data": [{"ticker": f"T{j['idValue'][-2:]}"}]} for j in jobs]

        with patch("src.universe._openfigi_post", side_effect=fake_post):
            result = resolve_isins_openfigi(isins)
        assert [len(c) for c in calls] == [10, 1]
        assert all(job["exchCode"] == "GY" for job in calls[0])
        assert result["DE0000000010"] == "T10.DE"

    @pytest.mark.parametrize(
        "answer",
        [{"error": "Too many requests"}, ["kein dict"], [{"data": "kein list"}]],
    )
    def test_malformed_answer_returns_empty(self, answer):
        with patch("src.universe._openfigi_post", return_value=answer):
            assert resolve_isins_openfigi(["DE0007493991"]) == {}

    def test_network_error_returns_partial_result(self):
        with patch("src.universe._openfigi_post", side_effect=OSError("down")):
            assert resolve_isins_openfigi(["DE0007493991"]) == {}


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
            patch("src.universe._fetch_ishares_json", side_effect=ishares),
            patch("src.universe._fetch_deka_xlsx", side_effect=deka),
            patch("src.universe.resolve_isins_openfigi", return_value=figi),
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
            patch("src.universe._fetch_ishares_json") as ishares,
            patch("src.universe._fetch_deka_xlsx") as deka,
        ):
            uni = load_universe(cfg=CFG, fallback_csv=fallback_csv, force_fallback=True)
        ishares.assert_not_called()
        deka.assert_not_called()
        assert uni.source == FALLBACK_SOURCE


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
