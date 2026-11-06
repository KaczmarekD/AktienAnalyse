"""Tests fuer den Migrations-Einstieg (ohne Datenbank - upgrade wird gepatcht)."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import patch

import pytest

from src.db import migrate
from va_platform.db import ddl


@pytest.fixture
def no_db_env(monkeypatch, tmp_path):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_OWNER_URL", raising=False)
    monkeypatch.chdir(tmp_path)  # keine .env aus dem Repo


class TestMigrateMain:
    def test_owner_url_alone_is_enough(self, no_db_env, monkeypatch):
        monkeypatch.setenv("DATABASE_OWNER_URL", "postgresql://va_owner:pw@db/va")
        with patch("src.db.migrate.upgrade") as upgrade:
            assert migrate.main() == 0
        upgrade.assert_called_once_with("postgresql://va_owner:pw@db/va")

    def test_owner_url_wins_over_app_url(self, no_db_env, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "postgresql://va_app:pw@db/va")
        monkeypatch.setenv("DATABASE_OWNER_URL", "postgresql://va_owner:pw@db/va")
        with patch("src.db.migrate.upgrade") as upgrade:
            migrate.main()
        assert "va_owner" in upgrade.call_args.args[0]

    def test_falls_back_to_app_url(self, no_db_env, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "postgresql://va_app:pw@db/va")
        with patch("src.db.migrate.upgrade") as upgrade:
            assert migrate.main() == 0
        assert "va_app" in upgrade.call_args.args[0]

    def test_profiles_role_is_ensured_with_the_password_from_the_env(self, no_db_env, monkeypatch):
        # P3.3: In einer bestehenden Datenbank fehlt va_profiles, das Init-Skript lief dort nicht
        monkeypatch.setenv("DATABASE_OWNER_URL", "postgresql://va_owner:pw@db/va")
        monkeypatch.setenv("VA_PROFILES_PASSWORD", "geheim")
        with (
            patch("src.db.migrate.upgrade"),
            patch("src.db.migrate.ensure_profiles_role") as ensure,
        ):
            assert migrate.main() == 0
        ensure.assert_called_once_with("postgresql://va_owner:pw@db/va", "geheim")

    def test_without_password_no_role_is_touched(self, no_db_env, monkeypatch):
        monkeypatch.setenv("DATABASE_OWNER_URL", "postgresql://va_owner:pw@db/va")
        monkeypatch.delenv("VA_PROFILES_PASSWORD", raising=False)
        with (
            patch("src.db.migrate.upgrade"),
            patch("src.db.migrate.ensure_profiles_role") as ensure,
        ):
            assert migrate.main() == 0
        ensure.assert_not_called()

    def test_role_failure_does_not_stop_the_batch(self, no_db_env, monkeypatch):
        # Der Batch braucht die Rolle nicht; nur das Speichern im UI faellt dann aus
        monkeypatch.setenv("DATABASE_OWNER_URL", "postgresql://va_owner:pw@db/va")
        monkeypatch.setenv("VA_PROFILES_PASSWORD", "geheim")
        with (
            patch("src.db.migrate.upgrade"),
            patch("src.db.migrate.ensure_profiles_role", side_effect=RuntimeError("kein Recht")),
        ):
            assert migrate.main() == 0

    def test_web_role_is_ensured_with_the_password_from_the_env(self, no_db_env, monkeypatch):
        # P4.4: va_web schreibt die Projektionen des web-api im Schema web
        monkeypatch.setenv("DATABASE_OWNER_URL", "postgresql://va_owner:pw@db/va")
        monkeypatch.setenv("VA_WEB_PASSWORD", "projektionen")
        monkeypatch.delenv("VA_PROFILES_PASSWORD", raising=False)
        with (
            patch("src.db.migrate.upgrade"),
            patch("src.db.migrate.ensure_web_role") as ensure,
        ):
            assert migrate.main() == 0
        ensure.assert_called_once_with("postgresql://va_owner:pw@db/va", "projektionen")

    def test_service_roles_are_ensured_with_their_passwords(self, no_db_env, monkeypatch):
        # P5.3: je Service eine Rolle nur fuers eigene Schema
        monkeypatch.setenv("DATABASE_OWNER_URL", "postgresql://va_owner:pw@db/va")
        monkeypatch.delenv("VA_PROFILES_PASSWORD", raising=False)
        monkeypatch.delenv("VA_WEB_PASSWORD", raising=False)
        monkeypatch.setenv("VA_SCORING_PASSWORD", "bewerten")
        monkeypatch.delenv("VA_MARKET_DATA_PASSWORD", raising=False)
        monkeypatch.delenv("VA_NOTIFICATION_PASSWORD", raising=False)
        with (
            patch("src.db.migrate.upgrade"),
            patch("src.db.migrate.ensure_service_role") as ensure,
        ):
            assert migrate.main() == 0
        ensure.assert_called_once_with(
            "postgresql://va_owner:pw@db/va", "bewerten", role="va_scoring"
        )

    def test_identity_role_is_ensured_with_the_password_from_the_env(self, no_db_env, monkeypatch):
        # D1.1: va_identity besitzt Konten und Sitzungen des web-api (Schema identity)
        monkeypatch.setenv("DATABASE_OWNER_URL", "postgresql://va_owner:pw@db/va")
        monkeypatch.setenv("VA_IDENTITY_PASSWORD", "konten")
        monkeypatch.delenv("VA_PROFILES_PASSWORD", raising=False)
        monkeypatch.delenv("VA_WEB_PASSWORD", raising=False)
        with (
            patch("src.db.migrate.upgrade"),
            patch("src.db.migrate.ensure_identity_role") as ensure,
        ):
            assert migrate.main() == 0
        ensure.assert_called_once_with("postgresql://va_owner:pw@db/va", "konten")

    def test_web_role_failure_does_not_stop_the_batch(self, no_db_env, monkeypatch):
        monkeypatch.setenv("DATABASE_OWNER_URL", "postgresql://va_owner:pw@db/va")
        monkeypatch.setenv("VA_WEB_PASSWORD", "projektionen")
        with (
            patch("src.db.migrate.upgrade"),
            patch("src.db.migrate.ensure_web_role", side_effect=RuntimeError("kein Recht")),
        ):
            assert migrate.main() == 0

    def test_without_any_url_fails_cleanly(self, no_db_env):
        with patch("src.db.migrate.upgrade") as upgrade:
            assert migrate.main() == 1
        upgrade.assert_not_called()

    def test_alembic_config_keeps_percent_in_password(self):
        cfg = migrate.alembic_config("postgresql://u:p%25w@db/va")
        assert cfg.attributes["url"] == "postgresql+psycopg://u:p%25w@db/va"
        assert cfg.get_main_option("script_location") == str(migrate.MIGRATIONS_DIR)


def _function(sql: str, name: str) -> str:
    """Eine ``CREATE FUNCTION`` aus einem SQL-Text, Leerraum vereinheitlicht."""
    start = sql.index(f"CREATE OR REPLACE FUNCTION public.{name}()")
    end = sql.index("$$;", start) + len("$$;")
    return " ".join(sql[start:end].split())


class TestGuardFinished:
    """P1.10: Migration 0005 und ``va_platform.db.ddl`` haben dieselbe Fassung des Triggers.

    Eine frische Datenbank bekommt ihn ueber 0001 aus ``ddl.py``, eine bestehende ueber
    0005. Laufen beide auseinander, unterscheiden sich NAS und Testvorlage.
    """

    def test_migration_and_ddl_agree(self):
        path = Path(__file__).parents[1] / "migrations" / "versions" / "0005_guard_finished.py"
        spec = importlib.util.spec_from_file_location("migration_0005", path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        assert _function(module.GUARD_FINISHED, "va_guard_finished") == _function(
            ddl.CREATE_FUNCTIONS, "va_guard_finished"
        )
