"""Sicherungstest fuer P1.3: Kennzahlen echter Titel bleiben beim Umbau gleich.

Rohdaten (info, Jahresabschluesse, FX-Kurs) sind aufgezeichnet (tests/fixtures/metrics),
die Erwartungswerte entstanden einmalig mit dem Code vor dem Umbau
(tests/golden/metrics). yfinance wird nicht gemockt: fetch_one bekommt die aufgezeichneten
Rohdaten statt des Abrufs.
"""

from __future__ import annotations

import json
from dataclasses import asdict, fields
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pandas as pd
import pytest

from va_market_data.adapters.yahoo import FetcherConfig, fetch_one
from va_market_data.domain.fundamentals import Fundamentals, Growth, QualityMetrics, ValueMetrics
from va_market_data.domain.metrics import Metrics
from va_market_data.domain.universe import Ticker

FIXTURES = Path(__file__).parent / "fixtures" / "metrics"
SYMBOLS = sorted(p.stem for p in FIXTURES.glob("*.json"))


def _frame(part: dict[str, Any] | None) -> pd.DataFrame:
    if part is None:
        return pd.DataFrame()
    columns = [pd.Timestamp(c) for c in part["columns"]]
    return pd.DataFrame(part["data"], index=part["index"], columns=columns, dtype=float)


def _fetch(symbol: str, *, fx_available: bool = True) -> Fundamentals:
    doc = json.loads((FIXTURES / f"{symbol}.json").read_text(encoding="utf-8"))
    statements = doc["statements"]
    raw = (
        doc["info"],
        _frame(statements["income"]),
        _frame(statements["balance"]),
        _frame(statements["cashflow"]),
    )

    def fx_rate(from_ccy: str, to_ccy: str) -> float:
        if not fx_available:
            msg = "kein Kurs"
            raise ValueError(msg)
        return doc["fx"][f"{from_ccy}->{to_ccy}"]

    with (
        patch("va_market_data.adapters.yahoo._ticker_data", return_value=raw),
        patch("va_market_data.adapters.yahoo._fx_rate", side_effect=fx_rate),
        patch("va_market_data.adapters.yahoo.fetch_consensus", return_value={}),
        patch("va_market_data.adapters.yahoo.fetch_quarterly", return_value={}),
        patch("va_market_data.adapters.yahoo.fetch_share_counts", return_value=None),
        patch("va_market_data.adapters.yahoo.fetch_prices", return_value=None),
    ):
        return fetch_one(Ticker(symbol, symbol, "DAX"), FetcherConfig(default_tax_rate=0.27))


def _snapshot(f: Fundamentals) -> bytes:
    """Alles, was fetch_one aus den Rohdaten rechnet - ohne den Zeitpunkt des Abrufs."""
    data = {
        "identity": asdict(f.identity),
        "market": asdict(f.market),
        "value": asdict(f.value),
        "quality": asdict(f.quality),
        "growth": asdict(f.growth),
        "fiscal_period_end": str(f.provenance.fiscal_period_end),
        "statement_fx": f.provenance.statement_fx,
        "errors": f.errors,
    }
    return (json.dumps(data, indent=1, sort_keys=True, ensure_ascii=False) + "\n").encode()


def test_fixtures_cover_the_interesting_cases():
    """Bank, Versicherer, Immobilien und eine abweichende Berichtswaehrung (Qiagen, USD)."""
    assert {"SAP.DE", "ALV.DE", "DBK.DE", "QIA.DE", "VNA.DE"} <= set(SYMBOLS)


@pytest.mark.parametrize("symbol", SYMBOLS)
def test_metrics_stay_the_same(golden, symbol):
    golden(f"metrics/{symbol}.json", _snapshot(_fetch(symbol)))


def test_without_exchange_rate(golden):
    """Qiagen berichtet in USD: Ohne Wechselkurs entfallen alle gemischten Multiples."""
    golden("metrics/QIA.DE-ohne-Kurs.json", _snapshot(_fetch("QIA.DE", fx_available=False)))


def test_metric_names_match_the_groups():
    """fetch_one uebernimmt die Kennzahlen ueber gleiche Feldnamen in die drei Gruppen."""
    groups = {f.name for cls in (ValueMetrics, QualityMetrics, Growth) for f in fields(cls)}
    assert {f.name for f in fields(Metrics)} == groups | {"enterprise_value"}


def test_no_stale_metric_files():
    expected = {f"{s}.json" for s in SYMBOLS} | {"QIA.DE-ohne-Kurs.json"}
    actual = {p.name for p in (Path(__file__).parent / "golden" / "metrics").iterdir()}
    assert actual == expected


def test_sap_bilanzqualitaet_by_hand():
    """F2.1 mit der aufgezeichneten SAP (Geschäftsjahre 2025, 2024, 2023), von Hand gerechnet.

    In Mio. EUR: Jahresüberschuss 7.161 und 3.124, operativer Cashflow 9.156, Bilanzsumme
    70.362, 74.237 und 68.331, langfristige Schulden 4.194 und 5.300, Umlaufvermögen 20.256 und
    21.401, kurzfristige Verbindlichkeiten 17.416 und 19.082, Aktien 1.167,6 und 1.166,6,
    Bruttoergebnis 26.814 und 24.932, Umsatz 36.800 und 34.176.

    - ROA 7.161 / 74.237 = 0,096 > 0, Vorjahr 3.124 / 68.331 = 0,046: gestiegen
    - CFO 9.156 / 74.237 = 0,123 > 0 und über dem ROA
    - Verschuldung 4.194 / 72.299,5 = 0,058 gegen 5.300 / 71.284 = 0,074: gesunken
    - Liquidität 1,163 gegen 1,122: gestiegen
    - Aktien 1.167,6 gegen 1.166,6: mehr geworden (0)
    - Bruttomarge 0,7286 gegen 0,7295: gesunken (0)
    - Kapitalumschlag 36.800 / 74.237 = 0,496 gegen 34.176 / 68.331 = 0,500: gesunken (0)

    F-Score 6. Accruals (7.161 - 9.156) / 72.299,5, CFO/Bilanzsumme 9.156 / 72.299,5.
    """
    quality = _fetch("SAP.DE").quality
    assert quality.f_score == 6
    assert quality.operating_accruals == pytest.approx(-1995.0 / 72299.5)
    assert quality.cfo_assets == pytest.approx(9156.0 / 72299.5)
