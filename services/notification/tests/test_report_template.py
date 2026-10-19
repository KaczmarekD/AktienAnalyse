"""Der Report-Renderer (P1.6) liest sein Template als Paketdatei.

Inhaltlich sichern ihn die Golden-Files unter tests/golden (tests/test_golden_report.py).
"""

from __future__ import annotations

from importlib import resources

from va_notification.domain.report import TEMPLATE_NAME, render_html


def test_template_ships_with_the_package():
    template = resources.files("va_notification").joinpath("templates", TEMPLATE_NAME)
    assert template.is_file()
    assert "<!DOCTYPE html>" in template.read_text(encoding="utf-8")


def test_template_escapes_html():
    html = render_html(
        generated_at="2026-10-19 07:30",
        top_n=1,
        bottom_n=1,
        top_rows=[{"name": "<b>Boese</b> AG", "symbol": "X.DE"}],
        bottom_rows=[],
        weights={"value": 0.6, "quality": 0.4},
        version="test",
        universe_source=None,
        universe_as_of=None,
        is_fallback=False,
        universe_added=[],
        universe_removed=[],
        fmt_num=str,
        fmt_pct=str,
        stats={"scored": 1, "universe": 1, "failed": 0},
    )
    assert "&lt;b&gt;Boese&lt;/b&gt; AG" in html
