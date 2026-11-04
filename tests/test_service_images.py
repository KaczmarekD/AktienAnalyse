"""Ein Image je Service (P5.1, ADR-0004): Stufen im Dockerfile und Schritte der CI.

Jedes Service-Image installiert mit ``uv sync --package`` nur sein Paket (dazu ``va-platform`` und
``va-contracts``). Ob es startet und nichts anderes enthaelt, prueft die CI am fertigen Image;
hier steht, dass Dockerfile und Workflow es so vorsehen. Gelesen wird als Text, ohne Docker.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = (ROOT / "Dockerfile").read_text(encoding="utf-8")
WORKFLOW = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

SERVICES = {
    "market-data": ("va-market-data", '["python", "-m", "va_market_data"]'),
    "scoring": ("va-scoring", '["python", "-m", "va_scoring"]'),
    "notification": ("va-notification", '["python", "-m", "va_notification"]'),
    "web-api": (
        "va-web-api",
        '["python", "-m", "uvicorn", "--factory", "va_web_api.main:create_app", '
        '"--host", "0.0.0.0", "--port", "8000"]',
    ),
}


def _stage(name: str) -> str:
    """Der Text einer Stufe, von ``FROM … AS name`` bis zur naechsten ``FROM``-Zeile."""
    match = re.search(
        rf"^FROM \S+ AS {re.escape(name)}\n(.*?)(?=^FROM |\Z)", DOCKERFILE, re.M | re.S
    )
    assert match, f"Stufe {name} fehlt im Dockerfile"
    return match.group(1)


class TestDockerfile:
    def test_services_share_a_slim_base_without_cron(self):
        base = _stage("service-base")
        assert "tzdata" in base
        assert "cron" not in base

    @pytest.mark.parametrize("stage", sorted(SERVICES))
    def test_each_service_installs_only_its_package(self, stage):
        package, entrypoint = SERVICES[stage]
        text = _stage(stage)
        assert re.search(rf"^FROM service-base AS {stage}$", DOCKERFILE, re.M)
        syncs = re.findall(r"uv sync [^\n]*(?:\\\n[^\n]*)*", text)
        assert syncs, f"{stage}: kein uv sync"
        assert all(f"--package {package}" in sync for sync in syncs)
        assert all("--locked" in sync and "--no-dev" in sync for sync in syncs)
        assert f"ENTRYPOINT {entrypoint}" in text
        # Kein Batch-Code: src/ gehoert nur ins App-Image
        assert "COPY src/" not in text

    def test_market_data_brings_the_fallback_csv(self):
        assert "COPY data/ ./data/" in _stage("market-data")

    def test_the_app_image_stays(self):
        assert re.search(r"^FROM base AS runtime$", DOCKERFILE, re.M)


class TestWorkflow:
    @pytest.mark.parametrize("stage", sorted(SERVICES))
    def test_ci_builds_every_service_image(self, stage):
        assert f"target: {stage}" in WORKFLOW or f"--target {stage}" in WORKFLOW

    def test_ci_checks_the_images(self):
        # Import, nichts Fremdes im Image, Start ohne Konfiguration endet mit Exit 2
        assert "docker/service_smoke.sh" in WORKFLOW

    @pytest.mark.parametrize("package", [p for p, _ in SERVICES.values()])
    def test_ci_pushes_every_service_image(self, package):
        push = WORKFLOW[WORKFLOW.index("Image nach GHCR schieben") :]
        assert package in push


class TestSmokeScript:
    def test_checks_import_isolation_and_exit_code(self):
        script = (ROOT / "docker" / "service_smoke.sh").read_text(encoding="utf-8")
        assert "import" in script
        assert "exit 2" in script or "!= 2" in script or "-ne 2" in script
        for module in ("va_market_data", "va_scoring", "va_notification", "va_web_api"):
            assert module in script
