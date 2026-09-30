"""Golden-Master fuer die Samstags-Mail (Arbeitspaket P0.1).

Fester Datensatz -> ``score()`` -> ``build_report()``. HTML, CSV und Metadaten
muessen byte-gleich mit ``tests/golden/`` sein. Das ist das Sicherungsnetz fuer
alle spaeteren Umbauten: Aendert sich die Mail ungewollt, wird dieser Test rot.
Bewusste Aenderungen mit ``pytest --update-golden`` neu schreiben und im Review
begruenden.
"""

from __future__ import annotations

import json
from datetime import date, datetime

import pytest

from src.reporting import build_report
from src.scoring import ScoringConfig, score
from src.universe import FALLBACK_SOURCE

FIXED_NOW = datetime(2026, 10, 3, 7, 30)

# Deckt alle Template-Zweige der Indexquelle ab
CASES: dict[str, dict[str, object]] = {
    "ishares": {
        "universe_source": "iShares",
        "universe_as_of": date(2026, 10, 2),
        "universe_added": ["NEU.DE"],
        "universe_removed": ["ALT.DE"],
    },
    "deka": {"universe_source": "Deka", "universe_as_of": None},
    "fallback": {"universe_source": FALLBACK_SOURCE, "universe_as_of": None},
}


def _report(mock_universe_df, case: str):
    scored = score(mock_universe_df, ScoringConfig())
    return build_report(
        scored,
        top_n=5,
        bottom_n=3,
        version="0.0.0-golden",
        universe_size=len(mock_universe_df),
        now=FIXED_NOW,
        **CASES[case],  # type: ignore[arg-type]
    )


@pytest.mark.parametrize("case", sorted(CASES))
def test_mail_html_matches_golden(mock_universe_df, golden, case):
    report = _report(mock_universe_df, case)
    golden(f"mail_{case}.html", report.html.encode("utf-8"))


def test_ranking_csv_matches_golden(mock_universe_df, golden):
    # Die CSV haengt nicht von der Indexquelle ab - ein Golden-File reicht
    report = _report(mock_universe_df, "ishares")
    golden("ranking.csv", report.csv_bytes)


def test_mail_meta_matches_golden(mock_universe_df, golden):
    meta = {}
    for case in sorted(CASES):
        report = _report(mock_universe_df, case)
        meta[case] = {
            "subject": report.subject,
            "csv_filename": report.csv_filename,
            "top_count": report.top_count,
            "bottom_count": report.bottom_count,
            "scored": report.scored,
            "failed": report.failed,
            "universe_size": report.universe_size,
        }
    golden("mail_meta.json", (json.dumps(meta, indent=2, ensure_ascii=False) + "\n").encode())


def test_csv_uses_lf_line_endings(mock_universe_df):
    # Auf der NAS (Linux) entsteht LF; unter Windows darf die CSV nicht anders aussehen
    report = _report(mock_universe_df, "ishares")
    assert b"\r\n" not in report.csv_bytes
