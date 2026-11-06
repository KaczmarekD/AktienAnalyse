"""Tests fuer Report-Generierung."""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from va_market_data.domain.universe import FALLBACK_SOURCE
from va_notification.domain.report import _build_subject, _fmt_num, _fmt_pct, build_report
from va_scoring.domain.scoring import ScoringConfig, score


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


class TestUnscoredTitles:
    """M1: Ein Titel ohne Composite steht nur in der CSV, hinter den bewerteten Titeln."""

    def test_only_in_the_csv(self, mock_universe_df):
        row = mock_universe_df[mock_universe_df["symbol"] == "VAL.DE"].iloc[0].to_dict()
        # Billig wie VAL.DE, aber nur 2 von 5 Quality-Faktoren (wie eine Bank)
        row |= {
            "symbol": "BANK.DE",
            "name": "Bank ohne Quality",
            "roic": None,
            "operating_margin": None,
            "net_debt_ebitda": None,
        }
        df = pd.concat([mock_universe_df, pd.DataFrame([row])], ignore_index=True)
        report = build_report(score(df, ScoringConfig()), top_n=8, bottom_n=8, universe_size=9)
        assert "Bank ohne Quality" not in report.html
        lines = report.csv_bytes.decode("utf-8-sig").strip().splitlines()
        assert "BANK.DE" in lines[-1]
        assert report.scored == 7


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


def test_fallback_source_is_the_same_in_both_services():
    """notification kennt market-data nicht (import-linter) - der Name muss trotzdem passen."""
    from va_notification.domain.report import FALLBACK_SOURCE as REPORT_FALLBACK

    assert REPORT_FALLBACK == FALLBACK_SOURCE


class TestFinancialsSection:
    """F2.4 (ADR-0011, Punkt 3): Titel unter der Branchenregel stehen in einem eigenen Abschnitt
    mit KBV, KGV, ROE und dem gerechtfertigten KBV (ROE - g) / (r - g). Der ROE folgt aus KBV und
    KGV (Gewinn je Buchwert = KBV / KGV)."""

    def _scored(self, mock_universe_df, pe: float | None = 10.0) -> pd.DataFrame:
        df = mock_universe_df.copy()
        df["industry"] = "Specialty Chemicals"
        df.loc[df["symbol"] == "MID.DE", ["industry", "pb_ratio", "pe_ratio"]] = [
            "Insurance - Diversified",
            2.0,
            pe,
        ]
        return score(df, ScoringConfig(industry_rules=True))

    def _section(self, html: str) -> str:
        assert "Finanzwerte" in html
        return html.split("Finanzwerte", 1)[1]

    def test_lists_the_titles_with_their_figures(self, mock_universe_df):
        scored = self._scored(mock_universe_df)
        html = build_report(
            scored, universe_size=8, cost_of_capital=0.08, terminal_growth=0.02
        ).html
        section = self._section(html)
        assert "Mid Co" in section
        assert "20.0 %" in section  # ROE = 2,0 / 10
        assert "3.00" in section  # (0,20 - 0,02) / (0,08 - 0,02)
        # Nicht in Top und Flop: Der Titel hat keinen Composite
        assert "Mid Co" not in html.split("Finanzwerte", 1)[0]

    def test_without_earnings_no_roe(self, mock_universe_df):
        html = build_report(self._scored(mock_universe_df, pe=None), universe_size=8).html
        row = self._section(html).split("Mid Co", 1)[1].split("</tr>", 1)[0]
        assert "%" not in row  # kein ROE, kein gerechtfertigtes KBV

    def test_missing_without_affected_titles(self, mock_universe_df):
        html = build_report(score(mock_universe_df, ScoringConfig()), universe_size=8).html
        assert "Finanzwerte" not in html
