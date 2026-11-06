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
    "VA_IDENTITY_PASSWORD",
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
        # Eigener Einstiegspunkt: kein Migrationslauf mit der Owner-Rolle. Seit P5.4 wie auf der
        # NAS ohne src: Vorschau, Profile und Reports beantworten die Services ueber NATS
        assert api["entrypoint"][:3] == ["python", "-m", "uvicorn"]
        assert "va_web_api.main:create_app" in api["entrypoint"]

    def test_gets_only_its_own_roles(self, local):
        env = local["services"]["web-api"]["environment"]
        # keine Zugangsdaten des Batches: lesen (va_read) und Projektionen (va_web, P4.4), dazu
        # NATS. Seit P5.4 speichert scoring die Profile selbst, va_profiles braucht es nicht mehr.
        # D1.1: Konten und Sitzungen mit va_identity; lokal ohne HTTPS, also Cookie ohne Secure
        assert set(env) == {
            "TZ",
            "WEB_API_DATABASE_URL",
            "WEB_API_NATS_URL",
            "WEB_API_PROJECTIONS_DATABASE_URL",
            "WEB_API_IDENTITY_DATABASE_URL",
            "WEB_API_SCHEDULE",
            "WEB_API_OTEL_TRACES_EXPORTER",  # P5.5, Standard none
            "WEB_API_COOKIE_SECURE",
        }
        assert env["WEB_API_DATABASE_URL"].startswith("postgresql+psycopg://va_read:")
        assert env["WEB_API_PROJECTIONS_DATABASE_URL"].startswith("postgresql+psycopg://va_web:")
        assert env["WEB_API_IDENTITY_DATABASE_URL"].startswith("postgresql+psycopg://va_identity:")
        assert env["WEB_API_NATS_URL"] == "nats://nats:4222"
        assert env["WEB_API_SCHEDULE"] == ""  # lokal keine Wochenlaeufe von selbst
        assert env["WEB_API_COOKIE_SECURE"] == "false"

    def test_e2e_cookie_without_https(self, e2e):
        """D1.1: Der E2E-Stack spricht HTTP mit nginx, das Cookie darf dort nicht Secure sein."""
        env = e2e["services"]["web-api"]["environment"]
        assert env["WEB_API_COOKIE_SECURE"] == "false"
        assert env["WEB_API_IDENTITY_DATABASE_URL"].startswith("postgresql+psycopg://va_identity:")

    def test_e2e_web_api_runs_the_full_stack(self, e2e):
        """P5.2: Der E2E-Stack prueft die Zielarchitektur: NATS, Projektionen, Services."""
        api = e2e["services"]["web-api"]
        env = api["environment"]
        assert env["WEB_API_NATS_URL"] == "nats://nats:4222"
        assert env["WEB_API_PROJECTIONS_DATABASE_URL"].startswith("postgresql+psycopg://va_web:")
        # Ohne src: laeuft mit dem App-Image wie mit dem Image des web-api (P5.1)
        assert "va_web_api.main:create_app" in api["entrypoint"]

    def test_nas_web_api_runs_with_nats_and_plans_the_week(self, nas):
        """P5.4: Auf der NAS ist NATS Standard; das web-api plant den Wochenlauf statt Cron."""
        env = nas["services"]["web-api"]["environment"]
        assert env["WEB_API_NATS_URL"] == "nats://nats:4222"
        assert env["WEB_API_PROJECTIONS_DATABASE_URL"].startswith("postgresql+psycopg://va_web:")
        assert env["WEB_API_SCHEDULE"] == "30 7 * * 6"  # CRON_SCHEDULE aus der .env


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
        # P5.4: kein Cron mehr, der Batch laeuft nur auf Wunsch (make docker-run, Regression)
        assert batch["profiles"] == ["run"]

    def test_services_on_the_nas(self, tmp_path):
        # P5.4: die Zielarchitektur ohne Profil: Migration, NATS, drei Services, web-api, UI
        nas = _config(tmp_path, NAS, profiles=())
        assert set(nas["services"]) == {
            "db",
            "migrate",
            "nats",
            "market-data",
            "scoring",
            "notification",
            "web-api",
            "frontend",
        }

    def test_migration_runs_once_before_everything(self, nas):
        migrate = nas["services"]["migrate"]
        assert migrate["image"] == nas["services"]["value-analyzer"]["image"]
        assert migrate["entrypoint"] == ["python", "-m", "src.db.migrate"]
        assert migrate["restart"] == "no"
        env = migrate["environment"]
        assert env["DATABASE_OWNER_URL"].startswith("postgresql+psycopg://va_owner:")
        for variable in (
            "VA_PROFILES_PASSWORD",
            "VA_WEB_PASSWORD",
            "VA_MARKET_DATA_PASSWORD",
            "VA_SCORING_PASSWORD",
            "VA_NOTIFICATION_PASSWORD",
            "VA_IDENTITY_PASSWORD",  # D1.1
        ):
            assert variable in env
        for name in ("market-data", "scoring", "notification", "web-api"):
            assert nas["services"][name]["depends_on"]["migrate"]["condition"] == (
                "service_completed_successfully"
            )

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

    def test_web_api_has_no_port_and_only_its_roles(self, nas):
        api = nas["services"]["web-api"]
        assert "ports" not in api  # nur hinter nginx erreichbar
        # P5.4: das eigene Image (P5.1), der Einstieg steht darin
        assert api["image"] == "ghcr.io/kaczmarekd/va-web-api:latest"
        assert api.get("entrypoint") is None
        env = api["environment"]
        assert set(env) == {
            "TZ",
            "WEB_API_DATABASE_URL",
            "WEB_API_NATS_URL",
            "WEB_API_PROJECTIONS_DATABASE_URL",
            "WEB_API_IDENTITY_DATABASE_URL",  # D1.1: Konten und Sitzungen
            "WEB_API_SCHEDULE",
            "WEB_API_OTEL_TRACES_EXPORTER",  # P5.5, Standard none
        }
        assert env["WEB_API_DATABASE_URL"].startswith("postgresql+psycopg://va_read:")
        assert env["WEB_API_PROJECTIONS_DATABASE_URL"].startswith("postgresql+psycopg://va_web:")
        assert env["WEB_API_IDENTITY_DATABASE_URL"].startswith("postgresql+psycopg://va_identity:")
        assert env["WEB_API_OTEL_TRACES_EXPORTER"] == "none"
        # Auf der NAS mit HTTPS (D1.5): Das Cookie ist Secure, das ist der Standard
        assert "WEB_API_COOKIE_SECURE" not in env

    def test_tracing_is_one_switch_for_all_services(self, nas):
        """P5.5: OTEL_TRACES_EXPORTER aus der .env gilt fuer jeden Dienst, der einen Run sieht."""
        for name in ("market-data", "scoring", "notification"):
            assert nas["services"][name]["environment"]["OTEL_TRACES_EXPORTER"] == ""

    def test_db_creates_the_profiles_role_on_first_start(self, nas):
        env = nas["services"]["db"]["environment"]
        assert "VA_PROFILES_PASSWORD" in env

    def test_db_creates_the_identity_role_on_first_start(self, nas):
        """D1.1: In einer bestehenden Datenbank legt migrate die Rolle an, sonst db/init."""
        assert "VA_IDENTITY_PASSWORD" in nas["services"]["db"]["environment"]

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
        # pgweb braucht der Test nicht; seit P5.2 der ganze Stack mit den drei Services
        assert set(e2e["services"]) == {
            "db",
            "value-analyzer",
            "web-api",
            "frontend",
            "mailpit",
            "nats",
            "market-data",
            "scoring",
            "notification",
            "migrate",
        }

    def test_market_data_replays_the_fixture(self, e2e):
        service = e2e["services"]["market-data"]
        fixture = service["environment"]["REPLAY_SOURCE"]
        assert fixture.startswith("/app/e2e/")
        assert (ROOT / "tests/fixtures/replay" / fixture.removeprefix("/app/e2e/")).is_file()
        assert _mounts(service)["/app/e2e"].endswith("/tests/fixtures/replay")
        assert "profiles" not in service

    def test_notification_mails_only_to_mailpit(self, e2e):
        service = e2e["services"]["notification"]
        env = service["environment"]
        assert (env["SMTP_HOST"], env["SMTP_PORT"], env["SMTP_PLAIN"]) == (
            "mailpit",
            "1025",
            "true",
        )
        assert env["HEALTHCHECK_URL"] == ""
        assert {"SMTP_USER", "SMTP_PASSWORD", "MAIL_TO"} <= set(env)
        assert "profiles" not in service

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
        images = {
            "E2E_APP_IMAGE": "value-analyzer:ci",
            "E2E_FRONTEND_IMAGE": "va-frontend:ci",
            "E2E_WEB_API_IMAGE": "va-web-api:ci",
            "E2E_MARKET_DATA_IMAGE": "va-market-data:ci",
            "E2E_SCORING_IMAGE": "va-scoring:ci",
            "E2E_NOTIFICATION_IMAGE": "va-notification:ci",
        }
        ci = _config(tmp_path, NAS, LOCAL, E2E, env_file=E2E_ENV, extra_env=images)
        services = ci["services"]
        assert services["value-analyzer"]["image"] == "value-analyzer:ci"
        assert services["web-api"]["image"] == "va-web-api:ci"
        assert services["frontend"]["image"] == "va-frontend:ci"
        for name in ("market-data", "scoring", "notification"):
            assert services[name]["image"] == f"va-{name}:ci"

    def test_locally_everything_runs_from_the_app_image(self, e2e):
        for name in ("web-api", "market-data", "scoring", "notification"):
            assert e2e["services"][name]["image"] == "value-analyzer:local"


SERVICES = {
    "market-data": "va_market_data",
    "scoring": "va_scoring",
    "notification": "va_notification",
}


class TestServices:
    """P5.1: Ein Container je Service aus seinem eigenen Image, nur mit dem Profil nats."""

    def test_the_nas_starts_them_without_a_profile(self, nas):
        # P5.4: NATS und die Services sind Standard, kein Profil nats mehr
        for name in SERVICES:
            assert name in nas["services"]
            assert "profiles" not in nas["services"][name]
        assert "worker" not in nas["services"]

    def test_each_runs_its_own_image(self, nas_nats):
        for name in SERVICES:
            service = nas_nats["services"][name]
            assert service["image"] == f"ghcr.io/kaczmarekd/va-{name}:latest"
            assert service.get("entrypoint") is None  # der Einstieg steht im Image
            assert "ports" not in service
            assert set(service["depends_on"]) == {"db", "nats", "migrate"}

    def test_each_gets_only_its_variables(self, nas_nats):
        for name in SERVICES:
            env = nas_nats["services"][name]["environment"]
            # P5.3: eine Rolle je Service, nur im eigenen Schema
            role = "va_" + name.replace("-", "_")
            assert env["DATABASE_URL"].startswith(f"postgresql+psycopg://{role}:")
            assert env["NATS_URL"] == "nats://nats:4222"
            assert "DATABASE_OWNER_URL" not in env
            assert "POSTGRES_PASSWORD" not in env
            has_smtp = any(key.startswith("SMTP_") for key in env)
            assert has_smtp == (name == "notification"), name

    def test_the_database_creates_the_service_roles(self, nas_nats):
        env = nas_nats["services"]["db"]["environment"]
        for variable in (
            "VA_MARKET_DATA_PASSWORD",
            "VA_SCORING_PASSWORD",
            "VA_NOTIFICATION_PASSWORD",
        ):
            assert variable in env

    def test_notification_mails_and_pings_like_the_batch(self, nas_nats):
        env = nas_nats["services"]["notification"]["environment"]
        assert env["SMTP_HOST"] == "smtp.gmail.com"
        assert env["HEALTHCHECK_URL"].startswith("https://hc-ping.com/")

    def test_local_services_run_from_the_app_image(self, local_nats):
        for name, module in SERVICES.items():
            service = local_nats["services"][name]
            assert service["image"] == "value-analyzer:local"
            assert service["entrypoint"] == ["python", "-m", module]
            assert service["container_name"] == f"value-analyzer-local-{name}"

    def test_local_mail_stays_on_the_machine(self, local_nats):
        env = local_nats["services"]["notification"]["environment"]
        assert (env["SMTP_HOST"], env["SMTP_PORT"], env["SMTP_PLAIN"]) == (
            "mailpit",
            "1025",
            "true",
        )
        assert env["HEALTHCHECK_URL"] == ""
        assert env["DATA_DIR"] == "/app/data"

    def test_the_e2e_stack_runs_them_without_a_worker(self, e2e):
        for name in SERVICES:
            assert name in e2e["services"]  # P5.2: der ganze Stack
        assert "worker" not in e2e["services"]
