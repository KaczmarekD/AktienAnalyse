"""Tests fuer Report-Generierung."""

from __future__ import annotations

from datetime import date

import pytest

from src.reporting import _build_subject, _fmt_num, _fmt_pct, build_report
from src.scoring import ScoringConfig, score
from src.universe import FALLBACK_SOURCE


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
    def test_html_and_csv_produced(self, mock_universe_df):
        scored = score(mock_universe_df, ScoringConfig())
        report = build_report(scored, top_n=3, bottom_n=2, universe_size=8)
        assert report.html.startswith("<!DOCTYPE")
        assert "<table>" in report.html
        assert "Top 3 Value-Kandidaten" in report.html
        assert report.csv_filename.startswith("value_ranking_")
        assert report.csv_filename.endswith(".csv")
        assert report.csv_bytes.startswith(b"\xef\xbb\xbf")  # BOM fuer Excel
        assert report.top_count == 3
        assert report.bottom_count == 2
        assert report.scored > 0
        assert "Keine Anlageempfehlung" in report.html

    def test_weights_rendered_as_single_percent(self, mock_universe_df):
        scored = score(mock_universe_df, ScoringConfig())
        report = build_report(scored, universe_size=8)
        assert "60 % Value" in report.html
        assert "%%" not in report.html

    def test_subject_contains_stats(self, mock_universe_df):
        scored = score(mock_universe_df, ScoringConfig())
        report = build_report(scored, universe_size=8)
        assert "/8]" in report.subject  # z.B. [ok 7/8]
        assert "DAX/MDAX Value-Screening" in report.subject

    def test_csv_is_german_locale(self, mock_universe_df):
        scored = score(mock_universe_df, ScoringConfig())
        report = build_report(scored, universe_size=8)
        content = report.csv_bytes.decode("utf-8-sig")
        # Deutsche CSV: Semikolon-Trenner, Komma-Dezimalzeichen
        assert ";" in content
        assert "," in content  # Dezimal

    def test_build_report_writes_no_files(self, mock_universe_df, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        build_report(score(mock_universe_df, ScoringConfig()), universe_size=8)
        assert list(tmp_path.iterdir()) == []

    def test_missing_sector_shows_dash_not_nan(self, mock_universe_df):
        # pandas 3: fehlende Texte kommen als NaN (truthy) statt None - im Template "-"
        df = mock_universe_df.copy()
        df.loc[df["symbol"] == "VAL.DE", "sector"] = None
        report = build_report(score(df, ScoringConfig()), top_n=8, bottom_n=8, universe_size=8)
        assert ">nan<" not in report.html
        assert '<td class="text">-</td>' in report.html


class TestUniverseSourceNote:
    def _html(self, mock_universe_df, **kwargs):
        scored = score(mock_universe_df, ScoringConfig())
        return build_report(scored, universe_size=8, **kwargs).html

    def test_shows_source_and_as_of(self, mock_universe_df):
        html = self._html(
            mock_universe_df, universe_source="iShares", universe_as_of=date(2026, 9, 29)
        )
        assert "Indexquelle: iShares (Stand 2026-09-29)" in html
        assert "Fallback-CSV pflegen" not in html

    def test_warns_when_csv_is_outdated(self, mock_universe_df):
        html = self._html(
            mock_universe_df,
            universe_source="iShares",
            universe_added=["Ströer (SAX.DE, MDAX)"],
            universe_removed=["Hugo Boss (BOSS.DE, MDAX)"],
        )
        assert "Fallback-CSV pflegen" in html
        assert "Ströer (SAX.DE, MDAX)" in html
        assert "Hugo Boss (BOSS.DE, MDAX)" in html

    def test_warns_when_only_fallback_available(self, mock_universe_df):
        html = self._html(mock_universe_df, universe_source=FALLBACK_SOURCE)
        assert "Live-Indexquellen nicht erreichbar" in html

    def test_deka_marked_without_as_of(self, mock_universe_df):
        html = self._html(mock_universe_df, universe_source="Deka")
        assert "Indexquelle: Deka (ohne Stichtag)" in html
        assert "Live-Indexquellen nicht erreichbar" not in html

    def test_escapes_names(self, mock_universe_df):
        html = self._html(mock_universe_df, universe_source="iShares", universe_added=["<b>X</b>"])
        assert "<b>X</b>" not in html
