"""Der Report-Renderer (P1.6) liest sein Template als Paketdatei.

Inhaltlich sichern ihn die Golden-Files unter tests/golden (tests/test_golden_report.py).
"""

from __future__ import annotations

from importlib import resources

from va_notification.domain.report import HTML_TEMPLATE, TEMPLATE_NAME, render_html


def test_template_ships_with_the_package():
    template = resources.files("va_notification").joinpath("templates", TEMPLATE_NAME)
    assert template.is_file()
    assert "<!DOCTYPE html>" in template.read_text(encoding="utf-8")


def test_template_escapes_html():
    """Namen kommen von Yahoo und iShares - im Mail-HTML nie ungefiltert."""
    assert HTML_TEMPLATE.environment.autoescape is True
    assert render_html.__module__ == "va_notification.domain.report"
