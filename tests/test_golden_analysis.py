"""Golden-Files der Depot-Analyse (D4.4, analyse.md, Tests und Abnahme).

Vier Beispieldepots als JSON-Fixtures unter ``tests/fixtures/analysis/``: nur Aktien, Aktien
plus Welt-ETF, mit Anleihen (darunter ein Floater), mit fehlenden Kursen. Das Ergebnis von
``analyze()`` steht je Depot in ``tests/golden/analysis/``. Eine gewollte Aenderung der Rechnung
schreibt sie mit ``--update-golden`` neu.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from va_portfolio.domain.analysis import AnalysisInput, BondData, EtfData, analyze
from va_portfolio.domain.bonds import BondTerms
from va_portfolio.domain.depots import CashLine, HoldingLine
from va_portfolio.domain.funds import Fund, FundHolding
from va_portfolio.domain.valuation import Market, Quote, Score, SecurityInfo, value_depot

FIXTURES = Path(__file__).parent / "fixtures" / "analysis"
DEPOTS = sorted(p.stem for p in FIXTURES.glob("*.json"))


def _day(text: str) -> date:
    return date.fromisoformat(text)


def _input(data: dict[str, Any]) -> AnalysisInput:
    market = Market(
        securities={
            s["isin"]: SecurityInfo(s["isin"], s["name"], s["asset_class"], s["currency"])
            for s in data["securities"]
        },
        quotes={
            q["isin"]: Quote(
                q["isin"],
                _day(q["trade_date"]),
                Decimal(q["close"]),
                q["currency"],
                percent_of_par=q["percent_of_par"],
            )
            for q in data["quotes"]
        },
        fx={currency: Decimal(rate) for currency, rate in data["fx"].items()},
        scores={s["isin"]: Score(**{**s, "as_of": _day(s["as_of"])}) for s in data["scores"]},
    )
    lines = [
        HoldingLine(line["isin"], Decimal(line["quantity"]), unit=line["unit"])
        for line in data["lines"]
    ]
    value = value_depot(data["kind"], lines, [CashLine(Decimal(data["cash"]))], market)
    etfs = {
        isin: EtfData(
            as_of=_day(e["as_of"]),
            ter=e["ter"],
            currency=e["currency"],
            sectors=e["sectors"],
            countries=e["countries"],
            holdings=Fund(
                holdings=tuple(FundHolding(i, w) for i, w, _ in e["holdings"]),
                complete=e["complete"],
            ),
        )
        for isin, e in data["etfs"].items()
    }
    bonds = {
        isin: BondData(
            BondTerms(
                coupon=b["coupon"],
                maturity=_day(b["maturity"]),
                floating=b.get("floating", False),
            ),
            b["cfi"],
        )
        for isin, b in data["bonds"].items()
    }
    return AnalysisInput(
        value=value,
        etfs=etfs,
        bonds=bonds,
        composites=data["composites"],
        names=data["names"],
    )


def _plain(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_plain(v) for v in value]
    if isinstance(value, float):
        return None if math.isnan(value) else round(value, 6)
    if isinstance(value, (Decimal, date)):
        return str(value)
    return value


@pytest.mark.parametrize("name", DEPOTS)
def test_analysis_matches_the_golden_file(golden, name):
    data = json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
    result = _plain(asdict(analyze(_input(data))))
    golden(
        f"analysis/{name}.json",
        (json.dumps(result, indent=2, ensure_ascii=False) + "\n").encode("utf-8"),
    )


def test_the_four_example_depots_exist():
    assert DEPOTS == ["aktien_und_welt_etf", "fehlende_kurse", "mit_anleihen", "nur_aktien"]
