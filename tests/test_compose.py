"""Compose: der lokale Stack ueber der NAS-Definition (U1, docs/architecture/umgebungen.md).

``docker compose config`` fuehrt die Dateien zusammen, wie ``up`` es taete, und braucht dafuer
nur die CLI, keinen Docker-Daemon. Es laeuft in einem temporaeren Ordner mit einer Dummy-.env,
die wie eine echte aussieht: Gmail, Healthcheck und Datenbank im LAN sind gesetzt. Lokal
muessen sie trotzdem aus sein.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
NAS = "docker-compose.yml"
LOCAL = "docker-compose.local.yml"
REAL_LOOKING_ENV = """
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
HEALTHCHECK_URL=https://hc-ping.com/00000000-0000-0000-0000-000000000000
DB_LAN_BIND=192.168.1.10
UI_LAN_BIND=192.168.1.10
UI_SERVER_NAMES=nas nas.fritz.box 192.168.1.10
"""
# Variablen, die Compose sonst aus der Umgebung des Testlaufs uebernaehme
_COMPOSE_INPUTS = (
    "COMPOSE_FILE",
    "COMPOSE_PROFILES",
    "COMPOSE_PROJECT_NAME",
    "POSTGRES_PASSWORD",
    "VA_APP_PASSWORD",
    "VA_READ_PASSWORD",
    "DB_LAN_BIND",
    "REG",
    "VERSION",
    "LOCAL_DB_PORT",
    "UI_LAN_BIND",
    "UI_SERVER_NAMES",
)


def _config(directory: Path, *files: str, env: str | None = None) -> dict[str, Any]:
    """``env``: Inhalt der .env; ohne Angabe .env.example mit echt wirkenden Werten."""
    if shutil.which("docker") is None:
        if os.environ.get("CI"):
            pytest.fail("docker CLI fehlt in der CI")
        pytest.skip("docker CLI nicht installiert")
    for name in files:
        shutil.copy(ROOT / name, directory / name)
    if env is None:
        env = (ROOT / ".env.example").read_text(encoding="utf-8") + REAL_LOOKING_ENV
    (directory / ".env").write_text(env, encoding="utf-8")
    args = ["docker", "compose", "--project-directory", str(directory)]
    for name in files:
        args += ["-f", str(directory / name)]
    environ = {k: v for k, v in os.environ.items() if k not in _COMPOSE_INPUTS}
    result = subprocess.run(  # feste Argumente, keine Shell
        [*args, "--profile", "run", "--profile", "ui", "config", "--format", "json"],
        capture_output=True,
        text=True,
        check=False,
        env=environ,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


@pytest.fixture(scope="module")
def local(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    return _config(tmp_path_factory.mktemp("local"), NAS, LOCAL)


@pytest.fixture(scope="module")
def local_dev_env(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """Mit der .env aus .env.local.example, wie auf dem Entwicklungsrechner."""
    env = (ROOT / ".env.local.example").read_text(encoding="utf-8")
    return _config(tmp_path_factory.mktemp("local-dev"), NAS, LOCAL, env=env)


@pytest.fixture(scope="module")
def nas(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    return _config(tmp_path_factory.mktemp("nas"), NAS)


def _mounts(service: dict[str, Any]) -> dict[str, str]:
    """Ziel im Container -> Quelle auf dem Host (mit /)."""
    return {v["target"]: str(v["source"]).replace("\\", "/") for v in service.get("volumes", [])}


class TestLocalStack:
    def test_batch_is_built_from_the_working_tree(self, local):
        batch = local["services"]["value-analyzer"]
        assert batch["image"] == "value-analyzer:local"
        assert batch["build"]["target"] == "runtime"

    def test_batch_runs_only_on_demand(self, local):
        batch = local["services"]["value-analyzer"]
        assert batch["profiles"] == ["run"]  # make local-up startet ihn nicht, also kein Cron
        assert batch["restart"] == "no"

    def test_mail_and_healthcheck_never_leave_the_machine(self, local):
        env = local["services"]["value-analyzer"]["environment"]
        assert (env["SMTP_HOST"], env["SMTP_PORT"], env["SMTP_PLAIN"]) == (
            "mailpit",
            "1025",
            "true",
        )
        assert env["HEALTHCHECK_URL"] == ""

    def test_ports_bind_to_localhost_only(self, local):
        published = {
            (name, port["published"], port.get("host_ip"))
            for name, service in local["services"].items()
            for port in service.get("ports", [])
        }
        assert published == {
            ("db", "5432", "127.0.0.1"),
            ("mailpit", "8025", "127.0.0.1"),
            ("mailpit", "1025", "127.0.0.1"),
            ("pgweb", "8081", "127.0.0.1"),
            ("web-api", "8000", "127.0.0.1"),
            ("frontend", "8080", "127.0.0.1"),
        }

    def test_names_do_not_collide_with_the_nas_definition(self, local, nas):
        # Ein alter Stack aus docker-compose.yml auf demselben Rechner blockiert sonst den Start
        assert local["name"] == "value-analyzer-local"
        names = {s.get("container_name") for s in local["services"].values()} - {None}
        assert not names & {s.get("container_name") for s in nas["services"].values()}

    def test_helpers_have_fixed_versions(self, local):
        images = {name: local["services"][name]["image"] for name in ("mailpit", "pgweb")}
        assert images["mailpit"].startswith("axllent/mailpit:v")
        assert images["pgweb"].startswith("sosedoff/pgweb:0.")
        assert not any(image.endswith(":latest") for image in images.values())

    def test_pgweb_only_reads(self, local):
        pgweb = local["services"]["pgweb"]
        assert "--readonly" in pgweb["command"]
        url = pgweb["environment"]["PGWEB_DATABASE_URL"]
        assert url.startswith("postgres://va_read:")
        assert "@db:5432/value_analyzer" in url

    def test_database_and_logs_are_separate_from_the_nas(self, local):
        db = _mounts(local["services"]["db"])
        assert db["/var/lib/postgresql"].endswith("/.local/pgdata")
        batch = _mounts(local["services"]["value-analyzer"])
        assert batch["/app/logs"].endswith("/.local/logs")
        assert batch["/app/data"].endswith("/data")


class TestLocalWebApi:
    """P3.1/U4: das web-api lokal unter localhost:8000, bis P3.6 es hinter nginx stellt."""

    def test_runs_from_the_local_image_with_uvicorn(self, local):
        api = local["services"]["web-api"]
        assert api["image"] == "value-analyzer:local"
        # Eigener Einstiegspunkt: kein Migrationslauf mit der Owner-Rolle
        assert api["entrypoint"][:3] == ["python", "-m", "uvicorn"]
        assert "va_web_api.main:create_app" in api["entrypoint"]

    def test_gets_only_the_read_role(self, local):
        env = local["services"]["web-api"]["environment"]
        assert set(env) == {"TZ", "WEB_API_DATABASE_URL"}  # keine Zugangsdaten des Batches
        assert env["WEB_API_DATABASE_URL"].startswith("postgresql+psycopg://va_read:")
        assert "@db:5432/value_analyzer" in env["WEB_API_DATABASE_URL"]


class TestLocalFrontend:
    """P3.6: nginx mit dem Build aus dem Arbeitsstand unter localhost:8080."""

    def test_is_built_from_the_working_tree(self, local):
        frontend = local["services"]["frontend"]
        assert frontend["image"] == "va-frontend:local"
        assert str(frontend["build"]["context"]).replace("\\", "/").endswith("/frontend")

    def test_starts_only_on_demand(self, local):
        # Der Node-Build braucht viel Platz; zum Entwickeln gibt es make ui (ng serve)
        assert local["services"]["frontend"]["profiles"] == ["ui"]

    def test_answers_only_for_local_names(self, local):
        # Die Namen der NAS aus der .env gelten lokal nicht
        env = local["services"]["frontend"]["environment"]
        assert env["VA_SERVER_NAMES"] == "localhost 127.0.0.1"


class TestLocalDevEnv:
    """Die .env fuer make run/dry aus der .venv darf den Container nicht verbiegen."""

    def test_container_uses_its_own_paths_and_database(self, local_dev_env):
        env = local_dev_env["services"]["value-analyzer"]["environment"]
        assert (env["DATA_DIR"], env["LOGS_DIR"]) == ("/app/data", "/app/logs")
        assert "@db:5432/value_analyzer" in env["DATABASE_URL"]
        assert "@db:5432/value_analyzer" in env["DATABASE_OWNER_URL"]
        assert (env["SMTP_HOST"], env["SMTP_PORT"]) == ("mailpit", "1025")

    def test_pgweb_gets_the_read_password(self, local_dev_env):
        url = local_dev_env["services"]["pgweb"]["environment"]["PGWEB_DATABASE_URL"]
        assert url.startswith("postgres://va_read:lokalread@db:5432/")


class TestNasDefinition:
    """Die NAS nutzt ``docker-compose.yml`` allein - U1 darf daran nichts aendern."""

    def test_image_comes_from_ghcr(self, nas):
        batch = nas["services"]["value-analyzer"]
        assert batch["image"] == "ghcr.io/kaczmarekd/value-analyzer:latest"
        assert "build" not in batch
        assert "profiles" not in batch

    def test_services_on_the_nas(self, nas):
        # Batch, Datenbank und seit P3.6 das UI: frontend (nginx) vor dem web-api
        assert set(nas["services"]) == {"db", "value-analyzer", "web-api", "frontend"}

    def test_mail_healthcheck_and_lan_come_from_the_env(self, nas):
        env = nas["services"]["value-analyzer"]["environment"]
        assert env["SMTP_HOST"] == "smtp.gmail.com"
        assert env["HEALTHCHECK_URL"].startswith("https://hc-ping.com/")
        assert "SMTP_PLAIN" not in env
        [port] = nas["services"]["db"]["ports"]
        assert port["host_ip"] == "192.168.1.10"

    def test_web_api_has_no_port_and_only_the_read_role(self, nas):
        api = nas["services"]["web-api"]
        assert "ports" not in api  # nur hinter nginx erreichbar
        assert api["image"] == nas["services"]["value-analyzer"]["image"]
        assert api["entrypoint"][:3] == ["python", "-m", "uvicorn"]
        env = api["environment"]
        assert set(env) == {"TZ", "WEB_API_DATABASE_URL"}
        assert env["WEB_API_DATABASE_URL"].startswith("postgresql+psycopg://va_read:")

    def test_frontend_from_ghcr_on_8080_in_the_lan(self, nas):
        frontend = nas["services"]["frontend"]
        assert frontend["image"] == "ghcr.io/kaczmarekd/va-frontend:latest"
        assert "build" not in frontend
        [port] = frontend["ports"]
        assert (port["published"], port["target"], port["host_ip"]) == (
            "8080",
            8080,
            "192.168.1.10",
        )
        assert frontend["environment"]["VA_SERVER_NAMES"] == "nas nas.fritz.box 192.168.1.10"
        assert "web-api" in frontend["depends_on"]

    def test_ui_stays_local_without_lan_bind(self, tmp_path):
        env = (ROOT / ".env.example").read_text(encoding="utf-8")
        nas = _config(tmp_path, NAS, env=env)
        [port] = nas["services"]["frontend"]["ports"]
        assert port["host_ip"] == "127.0.0.1"

    def test_data_stays_in_pgdata(self, nas):
        assert _mounts(nas["services"]["db"])["/var/lib/postgresql"].endswith("/pgdata")
