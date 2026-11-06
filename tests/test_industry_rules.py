"""Branchenregel aus ADR-0011 auf der echten Woche vom 30.10.2026 (F2.4).

Sichert die Einstufung ab, die die Vorprüfung ergeben hat
(docs/research/adr-0011-vorpruefung/bericht.md): Banken, Versicherer, flatexDEGIRO („Capital
Markets“) und die vier Immobilienwerte, deren EBIT Bewertungsergebnisse nach IAS 40 enthält.
Deutsche Börse und DWS bleiben im Ranking.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from va_scoring.domain.scoring import ScoringConfig, score

FIXTURE = Path(__file__).parent / "fixtures" / "replay" / "2026-10-30_scoring-run-1.json"
EXPECTED = {
    # Banken und Versicherer (ADR-0011, Punkt 3)
    "ALV.DE", "CBK.DE", "DBK.DE", "HNR1.DE", "MUV2.DE", "TLX.DE",
    # Ergänzungen bei der Annahme: „Capital Markets“ und Immobilien
    "FTK.DE", "AT1.DE", "LEG.DE", "TEG.DE", "VNA.DE",
}  # fmt: skip


def _snapshots() -> pd.DataFrame:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return pd.DataFrame(data["snapshots"]["rows"], columns=data["snapshots"]["columns"])


def test_rule_covers_exactly_the_titles_from_the_pre_check():
    out = score(_snapshots(), ScoringConfig(industry_rules=True))
    assert set(out.loc[out["industry_rule"], "symbol"]) == EXPECTED


def test_titles_under_the_rule_get_no_composite():
    out = score(_snapshots(), ScoringConfig(industry_rules=True)).set_index("symbol")
    assert out.loc[sorted(EXPECTED), "composite_score"].isna().all()
    assert out.loc[["DB1.DE", "DWS.DE"], "industry_rule"].eq(False).all()


def test_off_the_ranking_stays_as_stored():
    """Mit abgeschalteter Regel (Profil v1) bleibt alles wie gespeichert."""
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    stored = pd.DataFrame(data["scores"]["rows"], columns=data["scores"]["columns"])
    out = score(_snapshots(), ScoringConfig())
    merged = out.merge(stored, on="symbol", suffixes=("", "_stored"))
    assert not out["industry_rule"].any()
    diff = (
        merged["composite_score"].fillna(-1) - merged["composite_score_stored"].fillna(-1)
    ).abs()
    assert diff.max() < 1e-12
