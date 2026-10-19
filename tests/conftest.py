"""Pytest-Fixtures fuer den Value-Analyzer."""

from __future__ import annotations

import difflib
import json
import os
from collections.abc import Callable
from itertools import islice
from pathlib import Path

import pandas as pd
import pytest

GOLDEN_DIR = Path(__file__).parent / "golden"

# Vergleicht Golden-Inhalt (erwartet) mit dem aktuellen Ergebnis; wirft AssertionError
GoldenCompare = Callable[[bytes, bytes, str], None]


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--update-golden",
        action="store_true",
        default=False,
        help="Golden-Files unter tests/golden/ neu schreiben statt vergleichen",
    )


def _text_diff(expected: bytes, actual: bytes, name: str, max_lines: int = 60) -> str:
    diff = difflib.unified_diff(
        expected.decode("utf-8", errors="replace").splitlines(),
        actual.decode("utf-8", errors="replace").splitlines(),
        fromfile=f"golden/{name}",
        tofile="aktuell",
        lineterm="",
    )
    return "\n".join(islice(diff, max_lines))


def compare_exact(expected: bytes, actual: bytes, name: str) -> None:
    if actual != expected:
        msg = (
            f"Abweichung zu golden/{name}. Bewusste Aenderung? Dann --update-golden "
            f"und den Diff im Review begruenden.\n{_text_diff(expected, actual, name)}"
        )
        raise AssertionError(msg)


@pytest.fixture
def golden(request: pytest.FixtureRequest) -> Callable[..., None]:
    """Vergleicht Ergebnisse mit ``tests/golden/<name>``.

    Golden-Files halten das heutige Verhalten fest (Sicherungsnetz fuer Umbauten).
    Eine Abweichung ist entweder ein Fehler oder eine bewusste Aenderung. Mit
    ``--update-golden`` werden geaenderte Dateien neu geschrieben und der Test als
    uebersprungen gemeldet, damit jede Aenderung sichtbar bleibt. In der CI ist
    das verboten.
    """
    update = request.config.getoption("--update-golden")
    if update and os.environ.get("CI"):
        pytest.fail("--update-golden ist in der CI verboten - Golden-Files nur lokal neu schreiben")

    def check(name: str, actual: bytes, compare: GoldenCompare = compare_exact) -> None:
        path = GOLDEN_DIR / name
        if update:
            if path.exists() and path.read_bytes() == actual:
                return
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(actual)
            pytest.skip(f"Golden-File neu geschrieben: {name} - Diff im Review begruenden")
        assert path.exists(), f"Golden-File fehlt: {name} - einmal mit --update-golden erzeugen"
        compare(path.read_bytes(), actual, name)

    return check


@pytest.fixture
def settings(tmp_path, monkeypatch):
    """Gueltige Settings ohne echte Dienste; Daten und Logs unter ``tmp_path``."""
    monkeypatch.setenv("SMTP_USER", "test@gmail.com")
    monkeypatch.setenv("SMTP_PASSWORD", "dummy-app-pw")
    monkeypatch.setenv("MAIL_TO", "recipient@example.com")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://va_app:x@localhost/value_analyzer")
    monkeypatch.chdir(tmp_path)

    from src.config import Settings

    s = Settings()  # type: ignore[call-arg]
    return s.model_copy(update={"data_dir": tmp_path / "data", "logs_dir": tmp_path / "logs"})


@pytest.fixture
def mock_universe_df() -> pd.DataFrame:
    """Repraesentatives 8-Werte-Universum mit allen Profilen."""
    # Eine Quelle fuer Root- und Scoring-Tests (vorher zwei identische Kopien)
    return pd.DataFrame(
        json.loads(
            (
                Path(__file__).parents[1]
                / "services"
                / "scoring"
                / "tests"
                / "fixtures"
                / "mock_universe.json"
            ).read_text(encoding="utf-8")
        )
    )
