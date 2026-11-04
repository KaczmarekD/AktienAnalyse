"""Compose: der lokale Stack und der E2E-Stack ueber der NAS-Definition (U1, U5).

Hintergrund: docs/architecture/umgebungen.md.

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
E2E = "docker-compose.e2e.yml"
E2E_ENV = "docker/e2e.env"
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
    "VA_PROFILES_PASSWORD",
    "DB_LAN_BIND",
    "REG",
    "VERSION",
    "LOCAL_DB_PORT",
    "UI_LAN_BIND",
    "UI_SERVER_NAMES",
    "E2E_APP_IMAGE",
    "E2E_FRONTEND_IMAGE",
    "E2E_FIXTURE",
)


def _config(
    directory: Path,
    *files: str,
    env: str | None = None,
    env_file: str | None = None,
    extra_env: dict[str, str] | None = None,
    profiles: tuple[str, ...] = ("run", "ui"),
) -> dict[str, Any]:
    """``env``: Inhalt der .env; ohne Angabe .env.example mit echt wirkenden Werten.

    ``env_file``: statt einer .env diese Datei aus dem Repo mit ``--env-file`` (E2E-Stack, der
    ohne .env auskommen muss, etwa in der CI).
    """
    if shutil.which("docker") is None:
        if os.environ.get("CI"):
            pytest.fail("docker CLI fehlt in der CI")
        pytest.skip("docker CLI nicht installiert")
    for name in files:
        shutil.copy(ROOT / name, directory / name)
    args = ["docker", "compose", "--project-directory", str(directory)]
    if env_file is None:
        if env is None:
            env = (ROOT / ".env.example").read_text(encoding="utf-8") + REAL_LOOKING_ENV
        (directory / ".env").write_text(env, encoding="utf-8")
    else:
        target = directory / env_file
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / env_file, target)
        args += ["--env-file", str(target)]
    for name in files:
        args += ["-f", str(directory / name)]
    environ = {k: v for k, v in os.environ.items() if k not in _COMPOSE_INPUTS}
    environ |= extra_env or {}
    result = subprocess.run(  # feste Argumente, keine Shell
        [*args, *(f"--profile={name}" for name in profiles), "config", "--format", "json"],
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
def e2e(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """Der E2E-Stack (U5.2): ohne .env, nur mit docker/e2e.env, wie in der CI."""
    return _config(tmp_path_factory.mktemp("e2e"), NAS, LOCAL, E2E, env_file=E2E_ENV)


@pytest.fixture(scope="module")
def nas(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    return _config(tmp_path_factory.mktemp("nas"), NAS)


@pytest.fixture(scope="module")
def nas_nats(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """Die NAS mit dem Profil ``nats`` (P4.7): Erst dann laeuft der Worker."""
    return _config(tmp_path_factory.mktemp("nas-nats"), NAS, profiles=("nats",))


@pytest.fixture(scope="module")
def local_nats(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """Wie ``make local-up``: lokal mit dem Profil ``nats``."""
    return _config(
        tmp_path_factory.mktemp("local-nats"), NAS, LOCAL, profiles=("run", "ui", "nats")
    )


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
            ("nats", "4222", "127.0.0.1"),  # P4.1: fuer make run/api aus der .venv
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
        assert _mounts(local["services"]["nats"])["/data"].endswith("/.local/natsdata")
        batch = _mounts(local["services"]["value-analyzer"])
        assert batch["/app/logs"].endswith("/.local/logs")
        assert batch["/app/data"].endswith("/data")


class TestLocalWebApi:
    """P3.1/U4: das web-api lokal unter localhost:8000, bis P3.6 es hinter nginx stellt."""

    def test_runs_from_the_local_image_with_uvicorn(self, local):
        api = local["services"]["web-api"]
        assert api["image"] == "value-analyzer:local"
        # Eigener Einstiegspunkt: kein Migrationslauf mit der Owner-Rolle. P3.3: die Composition
        # Root src.web, die Vorschau und Profil-Befehle aus scoring im selben Prozess verdrahtet
        assert api["entrypoint"][:3] == ["python", "-m", "uvicorn"]
        assert "src.web:create_app" in api["entrypoint"]

    def test_gets_only_its_own_roles(self, local):
        env = local["services"]["web-api"]["environment"]
        # keine Zugangsdaten des Batches: lesen (va_read), Profile (va_profiles, P3.3) und
        # Projektionen (va_web, P4.4), dazu NATS fuer den Event-Consumer
        assert set(env) == {
            "TZ",
            "WEB_API_DATABASE_URL",
            "WEB_API_PROFILES_DATABASE_URL",
            "WEB_API_NATS_URL",
            "WEB_API_PROJECTIONS_DATABASE_URL",
        }
        assert env["WEB_API_DATABASE_URL"].startswith("postgresql+psycopg://va_read:")
        assert env["WEB_API_PROFILES_DATABASE_URL"].startswith("postgresql+psycopg://va_profiles:")
        assert "@db:5432/value_analyzer" in env["WEB_API_PROFILES_DATABASE_URL"]
        assert env["WEB_API_PROJECTIONS_DATABASE_URL"].startswith("postgresql+psycopg://va_web:")
        assert env["WEB_API_NATS_URL"] == "nats://nats:4222"

    def test_e2e_web_api_stays_without_projections(self, e2e):
        """Der E2E-Stack bildet die NAS nach; NATS startet dort nicht (P4.4)."""
        env = e2e["services"]["web-api"]["environment"]
        assert env["WEB_API_NATS_URL"] == ""
        assert env["WEB_API_PROJECTIONS_DATABASE_URL"] == ""

    def test_nas_web_api_stays_without_projections(self, nas):
        """Auf der NAS laeuft die Kette im Prozess: Es gaebe nichts zu projizieren (P4.4)."""
        env = nas["services"]["web-api"]["environment"]
        assert "WEB_API_NATS_URL" not in env
        assert "WEB_API_PROJECTIONS_DATABASE_URL" not in env


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
        # Batch, Datenbank, seit P3.6 das UI (frontend vor dem web-api), seit P4.1 NATS
        assert set(nas["services"]) == {"db", "value-analyzer", "web-api", "frontend", "nats"}

    def test_nats_with_jetstream_and_its_own_data(self, nas):
        # P4.1: fester Stand, Daten unter ./natsdata, nur im Docker-Netz erreichbar
        nats = nas["services"]["nats"]
        assert nats["image"] == "nats:2.15.1-alpine"
        assert "-js" in nats["command"]
        assert _mounts(nats)["/data"].endswith("/natsdata")
        assert "ports" not in nats
        assert "healthcheck" in nats

    def test_mail_healthcheck_and_lan_come_from_the_env(self, nas):
        env = nas["services"]["value-analyzer"]["environment"]
        assert env["SMTP_HOST"] == "smtp.gmail.com"
        assert env["HEALTHCHECK_URL"].startswith("https://hc-ping.com/")
        assert "SMTP_PLAIN" not in env
        [port] = nas["services"]["db"]["ports"]
        assert port["host_ip"] == "192.168.1.10"

    def test_web_api_has_no_port_and_only_its_two_roles(self, nas):
        api = nas["services"]["web-api"]
        assert "ports" not in api  # nur hinter nginx erreichbar
        assert api["image"] == nas["services"]["value-analyzer"]["image"]
        assert api["entrypoint"][:3] == ["python", "-m", "uvicorn"]
        assert "src.web:create_app" in api["entrypoint"]
        env = api["environment"]
        assert set(env) == {"TZ", "WEB_API_DATABASE_URL", "WEB_API_PROFILES_DATABASE_URL"}
        assert env["WEB_API_DATABASE_URL"].startswith("postgresql+psycopg://va_read:")
        assert env["WEB_API_PROFILES_DATABASE_URL"].startswith("postgresql+psycopg://va_profiles:")

    def test_db_creates_the_profiles_role_on_first_start(self, nas):
        env = nas["services"]["db"]["environment"]
        assert "VA_PROFILES_PASSWORD" in env

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


class TestE2eStack:
    """U5.2: Wegwerf-Stack fuer make local-e2e und die CI, mit Replay-Daten statt Yahoo."""

    def test_own_project_and_names(self, e2e, local, nas):
        # Laeuft neben dem lokalen Stack und kollidiert mit keinem anderen
        assert e2e["name"] == "value-analyzer-e2e"
        names = {s.get("container_name") for s in e2e["services"].values()}
        assert None not in names
        assert all(n.startswith("value-analyzer-e2e") for n in names)
        others = {
            s.get("container_name")
            for s in [*local["services"].values(), *nas["services"].values()]
        }
        assert not names & others

    def test_services(self, e2e):
        # pgweb braucht der Test nicht
        assert set(e2e["services"]) == {
            "db",
            "value-analyzer",
            "web-api",
            "frontend",
            "mailpit",
            "nats",
        }

    def test_nats_is_thrown_away_too(self, e2e):
        nats = e2e["services"]["nats"]
        assert "/data" not in _mounts(nats)
        assert any(str(t).startswith("/data") for t in nats["tmpfs"])
        assert "ports" not in nats

    def test_database_is_thrown_away(self, e2e):
        db = e2e["services"]["db"]
        assert "/var/lib/postgresql" not in _mounts(db)  # nie .local/pgdata oder pgdata
        assert any(str(t).startswith("/var/lib/postgresql") for t in db["tmpfs"])
        assert _mounts(db)["/docker-entrypoint-initdb.d"].endswith("/db/init")  # Rollen wie sonst
        assert "ports" not in db

    def test_batch_replays_the_fixture(self, e2e):
        batch = e2e["services"]["value-analyzer"]
        fixture = batch["environment"]["REPLAY_SOURCE"]
        assert fixture.startswith("/app/e2e/")
        assert (ROOT / "tests/fixtures/replay" / fixture.removeprefix("/app/e2e/")).is_file()
        [mount] = batch["volumes"]
        assert (mount["target"], mount.get("read_only")) == ("/app/e2e", True)
        assert str(mount["source"]).replace("\\", "/").endswith("/tests/fixtures/replay")

    def test_mail_and_healthcheck_stay_local(self, e2e):
        env = e2e["services"]["value-analyzer"]["environment"]
        assert (env["SMTP_HOST"], env["SMTP_PORT"], env["SMTP_PLAIN"]) == (
            "mailpit",
            "1025",
            "true",
        )
        assert env["HEALTHCHECK_URL"] == ""

    def test_needs_no_env_file(self, e2e):
        # Kein .env des Rechners im Container: Der Stack laeuft gleich, lokal und in der CI
        batch = e2e["services"]["value-analyzer"]
        assert "env_file" not in batch
        assert {"SMTP_USER", "SMTP_PASSWORD", "MAIL_TO"} <= set(batch["environment"])

    def test_ports_bind_to_localhost_only(self, e2e):
        published = {
            (name, port["published"], port.get("host_ip"))
            for name, service in e2e["services"].items()
            for port in service.get("ports", [])
        }
        # Das web-api nur hinter nginx, wie auf der NAS
        assert published == {("mailpit", "18025", "127.0.0.1"), ("frontend", "18080", "127.0.0.1")}

    def test_frontend_serves_the_angular_build_of_the_working_tree(self, e2e):
        frontend = e2e["services"]["frontend"]
        assert frontend["image"] == "va-frontend:e2e"
        assert frontend["build"]["target"] == "prebuilt"  # ohne Node im Docker (Platz auf C:)
        dist = str(frontend["build"]["additional_contexts"]["dist"]).replace("\\", "/")
        assert dist.endswith("/frontend/dist/va-frontend/browser")
        assert "profiles" not in frontend
        assert frontend["environment"]["VA_SERVER_NAMES"] == "localhost 127.0.0.1"

    def test_batch_and_web_api_share_the_local_image(self, e2e):
        services = e2e["services"]
        assert services["value-analyzer"]["image"] == services["web-api"]["image"]
        assert services["web-api"]["image"] == "value-analyzer:local"

    def test_ci_uses_the_images_under_test(self, tmp_path):
        images = {"E2E_APP_IMAGE": "value-analyzer:ci", "E2E_FRONTEND_IMAGE": "va-frontend:ci"}
        ci = _config(tmp_path, NAS, LOCAL, E2E, env_file=E2E_ENV, extra_env=images)
        services = ci["services"]
        assert services["value-analyzer"]["image"] == "value-analyzer:ci"
        assert services["web-api"]["image"] == "value-analyzer:ci"
        assert services["frontend"]["image"] == "va-frontend:ci"


class TestWorker:
    """P4.7: Der Dienste-Prozess fuehrt die Runs des web-api ueber NATS aus."""

    def test_the_nas_starts_it_only_with_the_nats_profile(self, nas, nas_nats):
        assert "worker" not in nas["services"]
        assert "worker" in nas_nats["services"]

    def test_runs_the_app_image_without_migration(self, nas_nats):
        worker = nas_nats["services"]["worker"]
        assert worker["image"] == nas_nats["services"]["value-analyzer"]["image"]
        # Eigener Einstieg: Die Migration macht der Batch-Container, nicht zwei zugleich
        assert worker["entrypoint"] == ["python", "-m", "src.worker"]
        assert "ports" not in worker
        assert set(worker["depends_on"]) == {"db", "nats"}

    def test_uses_the_app_role_and_nats(self, nas_nats):
        env = nas_nats["services"]["worker"]["environment"]
        assert env["DATABASE_URL"].startswith("postgresql+psycopg://va_app:")
        assert "DATABASE_OWNER_URL" not in env
        assert env["NATS_URL"] == "nats://nats:4222"
        assert env["SMTP_HOST"] == "smtp.gmail.com"  # aus der .env, wie der Batch

    def test_local_worker_uses_the_working_tree_and_mailpit(self, local_nats):
        worker = local_nats["services"]["worker"]
        assert worker["image"] == "value-analyzer:local"
        assert worker["container_name"] == "value-analyzer-local-worker"
        env = worker["environment"]
        assert (env["SMTP_HOST"], env["SMTP_PORT"], env["SMTP_PLAIN"]) == (
            "mailpit",
            "1025",
            "true",
        )
        assert env["HEALTHCHECK_URL"] == ""
        assert env["DATA_DIR"] == "/app/data"

    def test_the_e2e_stack_has_no_worker(self, e2e):
        assert "worker" not in e2e["services"]
