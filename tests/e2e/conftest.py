"""Ende-zu-Ende (U5.2): Zugaenge zu einem laufenden Stack, von aussen wie ein Browser.

- ``E2E_BASE_URL``: das UI (nginx), ueber das auch das web-api erreichbar ist
- ``E2E_MAILPIT_URL``: Mailpit
- ``E2E_FIXTURE``: Dateiname der Replay-Fixture unter ``tests/fixtures/replay/``, mit der der
  Batch lief (wie in ``docker/e2e.env``). Nur dann vergleichen die Tests auch mit ihren
  Erwartungswerten (``make local-e2e``); ohne sie nur die Zusammenhaenge (``make local-check``).

Ohne ``E2E_BASE_URL`` werden alle Tests hier uebersprungen, wie die DB-Tests ohne
``TEST_DATABASE_URL``.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx
import pytest

from src.regression.case import ReplayCase

if TYPE_CHECKING:
    from collections.abc import Iterator

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "replay"


def _env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        pytest.skip(f"{name} nicht gesetzt (make local-e2e oder make local-check)")
    return value.rstrip("/")


@pytest.fixture(scope="session")
def base_url() -> str:
    return _env("E2E_BASE_URL")


@pytest.fixture(scope="session")
def ui(base_url: str) -> Iterator[httpx.Client]:
    with httpx.Client(base_url=base_url, timeout=30) as client:
        yield client


@pytest.fixture(scope="session")
def mailpit() -> Iterator[httpx.Client]:
    with httpx.Client(base_url=_env("E2E_MAILPIT_URL"), timeout=30) as client:
        yield client


@pytest.fixture(scope="session")
def expected() -> ReplayCase:
    """Die Fixture, mit der der Batch lief. Ohne sie: nur Zusammenhaenge pruefen."""
    name = os.environ.get("E2E_FIXTURE", "").strip()
    if not name:
        pytest.skip("ohne E2E_FIXTURE: echte Daten, keine festen Erwartungswerte")
    return ReplayCase.from_json((FIXTURES / name).read_text(encoding="utf-8"))


def get_json(client: httpx.Client, path: str, **params: Any) -> Any:
    response = client.get(path, params=params)
    response.raise_for_status()
    return response.json()


@pytest.fixture(scope="session")
def run(ui: httpx.Client) -> dict[str, Any]:
    """Der juengste abgeschlossene Lauf mit Versand (kein Dry-Run)."""
    for summary in get_json(ui, "/api/v1/runs", limit=50):
        if summary["finished_at"] is not None and not summary["dry_run"]:
            return get_json(ui, f"/api/v1/runs/{summary['id']}")
    pytest.fail("kein abgeschlossener Lauf ohne Dry-Run")


@pytest.fixture(scope="session")
def report(ui: httpx.Client, run: dict[str, Any]) -> dict[str, Any]:
    assert run["report_id"] is not None, f"Lauf #{run['id']} ohne Report ({run['status']})"
    return get_json(ui, f"/api/v1/reports/{run['report_id']}")


@pytest.fixture(scope="session")
def mail(mailpit: httpx.Client, report: dict[str, Any]) -> dict[str, Any]:
    """Die Mail zum Report in Mailpit: Ihr Betreff endet mit dem des Reports."""
    for message in get_json(mailpit, "/api/v1/messages", limit=50)["messages"]:
        if message["Subject"].endswith(report["subject"]):
            return get_json(mailpit, f"/api/v1/message/{message['ID']}")
    pytest.fail(f"keine Mail mit dem Betreff {report['subject']!r} in Mailpit")
