"""Tests fuer den Migrations-Einstieg (ohne Datenbank - upgrade wird gepatcht)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from src.db import migrate


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

    def test_without_any_url_fails_cleanly(self, no_db_env):
        with patch("src.db.migrate.upgrade") as upgrade:
            assert migrate.main() == 1
        upgrade.assert_not_called()

    def test_alembic_config_keeps_percent_in_password(self):
        cfg = migrate.alembic_config("postgresql://u:p%25w@db/va")
        assert cfg.attributes["url"] == "postgresql+psycopg://u:p%25w@db/va"
        assert cfg.get_main_option("script_location") == str(migrate.MIGRATIONS_DIR)
