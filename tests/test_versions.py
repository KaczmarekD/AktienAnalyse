"""Eine Version fuer alle Pakete (P5.2): Projekt, Workspace-Mitglieder und ``src.__version__``.

Seit P5.1 laeuft jeder Service in seinem eigenen Image und kennt nur seine Paketversion. Sie
steht in der Fusszeile der Mail und in ``scoring_run.app_version``. Damit dort dieselbe Version
steht wie beim Batch, haben alle Pakete die Version des Projekts.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from src import __version__

ROOT = Path(__file__).resolve().parents[1]


def _version(path: Path) -> str:
    return tomllib.loads(path.read_text(encoding="utf-8"))["project"]["version"]


def test_every_package_has_the_project_version():
    project = _version(ROOT / "pyproject.toml")
    members = sorted(
        [*ROOT.glob("packages/*/pyproject.toml"), *ROOT.glob("services/*/pyproject.toml")]
    )
    assert members
    assert {str(m.relative_to(ROOT)): _version(m) for m in members} == {
        str(m.relative_to(ROOT)): project for m in members
    }


def test_the_batch_reports_the_same_version():
    assert __version__ == _version(ROOT / "pyproject.toml")
