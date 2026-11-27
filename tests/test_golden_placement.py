"""Golden-File der Einordnung (D4.1, analyse.md, Tests und Abnahme).

Ein eingefrorenes Universum, die Replay-Fixture vom 30.10.2026 mit 90 Titeln, und drei
Kandidaten: eine deutsche Aktie, eine US-Aktie und eine Bank ohne Quality-Kennzahlen. Das Ergebnis
von ``place()`` steht in ``tests/golden/placement/placements.json``. Eine gewollte Änderung der
Methodik schreibt es mit ``--update-golden`` neu.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pandas as pd

from src.regression.case import ReplayCase
from va_scoring.domain.placement import place
from va_scoring.domain.scoring import ScoringConfig, score

FIXTURE = Path(__file__).parent / "fixtures" / "replay" / "2026-10-30_scoring-run-1.json"

CANDIDATES = [
    {
        "symbol": "KAND.DE",
        "name": "Deutsche Kandidat AG",
        "index": "-",
        "market_cap": 1.2e9,
        "ev_ebit": 11.5,
        "pb_ratio": 1.8,
        "p_fcf": 14.0,
        "shareholder_yield": 0.035,
        "roic": 0.13,
        "fcf_margin": 0.08,
        "operating_margin": 0.11,
        "net_debt_ebitda": 1.4,
        "earnings_stability": 0.8,
    },
    {
        "symbol": "AAPL",
        "name": "Apple Inc.",
        "index": "-",
        "market_cap": 3.0e12,
        "ev_ebit": 27.0,
        "pb_ratio": 45.0,
        "p_fcf": 30.0,
        "shareholder_yield": 0.03,
        "roic": 0.55,
        "fcf_margin": 0.26,
        "operating_margin": 0.31,
        "net_debt_ebitda": 0.4,
        "earnings_stability": 0.92,
    },
    {
        "symbol": "BANK.DE",
        "name": "Kandidaten-Bank",
        "index": "-",
        "market_cap": 8.0e9,
        "ev_ebit": None,
        "pb_ratio": 0.65,
        "p_fcf": None,
        "shareholder_yield": 0.07,
        "roic": None,
        "fcf_margin": None,
        "operating_margin": None,
        "net_debt_ebitda": None,
        "earnings_stability": 0.7,
    },
]


def _plain(value: object) -> object:
    if isinstance(value, float):
        return None if math.isnan(value) else round(value, 6)
    return value


def test_placements_match_the_golden_file(golden):
    universe = ReplayCase.from_json(FIXTURE.read_text(encoding="utf-8")).snapshots
    cfg = ScoringConfig()
    reference = score(universe, cfg)
    candidates = pd.DataFrame(CANDIDATES).reindex(columns=universe.columns)
    candidates = candidates.astype({"symbol": str})
    placed = place(reference, candidates, cfg)
    rows = [
        {key: _plain(value) for key, value in sorted(row.items())}
        for row in placed.to_dict("records")
    ]
    golden(
        "placement/placements.json",
        (json.dumps(rows, indent=2, ensure_ascii=False) + "\n").encode("utf-8"),
    )


def test_the_ranking_stays_the_same_with_candidates():
    """Die Ränge der Referenz hängen nicht von den Kandidaten ab."""
    universe = ReplayCase.from_json(FIXTURE.read_text(encoding="utf-8")).snapshots
    reference = score(universe, ScoringConfig())
    before = reference.copy()
    place(reference, pd.DataFrame(CANDIDATES).reindex(columns=universe.columns), ScoringConfig())
    pd.testing.assert_frame_equal(reference, before)
