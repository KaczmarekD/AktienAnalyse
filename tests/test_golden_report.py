"""Golden-Master fuer die Samstags-Mail (Arbeitspaket P0.1).

Eingefrorener Datensatz (``golden/input_fundamentals.json``) -> ``score()`` ->
``build_report()``. HTML je Indexquelle und die Metadaten muessen byte-gleich
mit ``tests/golden/`` sein, die CSV inhaltlich gleich (Gleitkommazahlen mit
Toleranz fuer die letzte Stelle) und im selben Format. Das ist das
Sicherungsnetz fuer alle spaeteren Umbauten: Aendert sich die Mail ungewollt,
wird dieser Test rot. Bewusste Aenderungen mit ``pytest --update-golden`` neu
schreiben und im Review begruenden.

Der Datensatz gehoert nur diesem Test. Die geteilte Fixture ``mock_universe_df``
darf sich fuer andere Tests aendern, ohne dass die Golden-Files wackeln.
"""

from __future__ import annotations

import io
import json
from datetime import date, datetime

import pandas as pd
import pytest

from src.reporting import ReportArtifacts, build_report
from src.scoring import ScoringConfig, score
from src.universe import FALLBACK_SOURCE
from tests.conftest import GOLDEN_DIR

GOLDEN_INPUT = GOLDEN_DIR / "input_fundamentals.json"
FIXED_NOW = datetime(2026, 10, 3, 7, 30)

# Jeder Zweig des Templates rund um die Indexquelle
CASES: dict[str, dict[str, object]] = {
    "ishares": {
        "universe_source": "iShares",
        "universe_as_of": date(2026, 10, 2),
        "universe_added": ["NEU.DE"],
        "universe_removed": ["ALT.DE"],
    },
    "ishares_nur_neu": {
        "universe_source": "iShares",
        "universe_as_of": date(2026, 10, 2),
        "universe_added": ["NEU.DE"],
    },
    "ishares_nur_raus": {
        "universe_source": "iShares",
        "universe_as_of": date(2026, 10, 2),
        "universe_removed": ["ALT.DE"],
    },
    "deka": {"universe_source": "Deka", "universe_as_of": None},
    "fallback": {"universe_source": FALLBACK_SOURCE, "universe_as_of": None},
    # z. B. Altdaten-Import: keine Indexquelle bekannt
    "ohne_quelle": {"universe_source": None, "universe_as_of": None},
}


@pytest.fixture(scope="module")
def scored() -> pd.DataFrame:
    records = json.loads(GOLDEN_INPUT.read_text(encoding="utf-8"))
    return score(pd.DataFrame(records), ScoringConfig())


def _report(scored: pd.DataFrame, case: str) -> ReportArtifacts:
    return build_report(
        scored.copy(),
        top_n=5,
        bottom_n=3,
        version="0.0.0-golden",
        universe_size=8,
        now=FIXED_NOW,
        **CASES[case],  # type: ignore[arg-type]
    )


def _csv_frame(raw: bytes) -> pd.DataFrame:
    return pd.read_csv(io.BytesIO(raw), sep=";", decimal=",", encoding="utf-8-sig")


def _compare_csv(expected: bytes, actual: bytes, name: str) -> None:
    # Inhalt statt Bytes: Nach Upgrades darf sich die letzte Stelle einer Gleitkommazahl
    # aendern, Werte, Spalten und Reihenfolge nicht.
    try:
        pd.testing.assert_frame_equal(
            _csv_frame(actual), _csv_frame(expected), check_exact=False, rtol=1e-12, atol=0.0
        )
    except AssertionError as exc:
        raise AssertionError(f"CSV weicht inhaltlich von golden/{name} ab: {exc}") from exc


@pytest.mark.parametrize("case", sorted(CASES))
def test_mail_html_matches_golden(scored, golden, case):
    golden(f"mail_{case}.html", _report(scored, case).html.encode("utf-8"))


def test_ranking_csv_matches_golden(scored, golden):
    # Die CSV haengt nicht von der Indexquelle ab - ein Golden-File reicht
    golden("ranking.csv", _report(scored, "ishares").csv_bytes, compare=_compare_csv)


def test_csv_format(scored):
    raw = _report(scored, "ishares").csv_bytes
    assert raw.startswith(b"\xef\xbb\xbf"), "BOM fehlt - Excel erkennt sonst keine Umlaute"
    assert b"\r\n" not in raw, "CSV muss LF nutzen, wie auf der NAS (Linux)"
    header = raw[3:].split(b"\n", 1)[0].decode("utf-8")
    assert header.startswith("rank_overall;symbol;name;index;")


def test_mail_meta_matches_golden(scored, golden):
    # Betreff, Dateiname und Zaehler haengen nicht von der Indexquelle ab
    report = _report(scored, "ishares")
    meta = {
        "subject": report.subject,
        "csv_filename": report.csv_filename,
        "top_count": report.top_count,
        "bottom_count": report.bottom_count,
        "scored": report.scored,
        "failed": report.failed,
        "universe_size": report.universe_size,
    }
    golden("mail_meta.json", (json.dumps(meta, indent=2, ensure_ascii=False) + "\n").encode())


def test_no_stale_golden_files():
    expected = {"input_fundamentals.json", "ranking.csv", "mail_meta.json"} | {
        f"mail_{case}.html" for case in CASES
    }
    actual = {path.name for path in GOLDEN_DIR.iterdir()}
    assert actual == expected, f"Unerwartet: {actual - expected}, fehlt: {expected - actual}"
