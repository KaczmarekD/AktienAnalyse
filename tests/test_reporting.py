"""Tests fuer Report-Generierung."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.reporting import _build_subject, _fmt_num, _fmt_pct, build_report
from src.scoring import ScoringConfig, score


class TestFormatters:
    @pytest.mark.parametrize(
        ("v", "expected"),
        [
            (None, "-"),
            (1234.567, "1.234.57"),
            (0.0, "0.00"),
        ],
    )
    def test_fmt_num(self, v, expected):
        assert _fmt_num(v) == expected

    @pytest.mark.parametrize(
        ("v", "expected"),
        [
            (None, "-"),
            (0.05, "5.0 %"),
            (0.123, "12.3 %"),
        ],
    )
    def test_fmt_pct(self, v, expected):
        assert _fmt_pct(v) == expected


class TestSubject:
    def test_ok_tag(self):
        from datetime import datetime

        ts = datetime(2026, 5, 16, 7, 30)
        s = _build_subject(scored=110, universe_size=110, top_name="SAP", timestamp=ts)
        assert s.startswith("[ok 110/110]")
        assert "SAP" in s
        assert "2026-05-16" in s

    def test_partial_tag(self):
        from datetime import datetime

        ts = datetime(2026, 5, 16, 7, 30)
        s = _build_subject(scored=80, universe_size=110, top_name="BMW", timestamp=ts)
        assert s.startswith("[partial 80/110]")


class TestBuildReportIntegration:
    def test_html_and_csv_produced(self, mock_universe_df, tmp_path: Path):
        scored = score(mock_universe_df, ScoringConfig())
        report = build_report(scored, output_dir=tmp_path, top_n=3, bottom_n=2, universe_size=8)
        assert report.html.startswith("<!DOCTYPE")
        assert "<table>" in report.html
        assert "Top 3 Value-Kandidaten" in report.html
        assert report.csv_path.exists()
        assert report.top_count == 3
        assert report.bottom_count == 2
        assert report.scored > 0
        assert "Keine Anlageempfehlung" in report.html

    def test_subject_contains_stats(self, mock_universe_df, tmp_path: Path):
        scored = score(mock_universe_df, ScoringConfig())
        report = build_report(scored, output_dir=tmp_path, universe_size=8)
        assert "/8]" in report.subject  # z.B. [ok 7/8]
        assert "DAX/MDAX Value-Screening" in report.subject

    def test_csv_is_german_locale(self, mock_universe_df, tmp_path: Path):
        scored = score(mock_universe_df, ScoringConfig())
        report = build_report(scored, output_dir=tmp_path, universe_size=8)
        content = report.csv_path.read_text(encoding="utf-8-sig")
        # Deutsche CSV: Semikolon-Trenner, Komma-Dezimalzeichen
        assert ";" in content
        assert "," in content  # Dezimal
