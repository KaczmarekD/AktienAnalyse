"""Tests fuer Pydantic-Settings-Config."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.config import Settings


@pytest.fixture
def minimal_env(monkeypatch):
    """Setzt die Mindest-Pflichtfelder fuer eine valide Settings-Instanz."""
    monkeypatch.setenv("SMTP_USER", "test@gmail.com")
    monkeypatch.setenv("SMTP_PASSWORD", "test-app-password")
    monkeypatch.setenv("MAIL_TO", "recipient@example.com")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://va_app:x@localhost/value_analyzer")
    # .env-File aus dem Repo nicht laden (Tests sollen isoliert sein)
    monkeypatch.chdir("/tmp")


class TestSettings:
    def test_loads_with_minimal_env(self, minimal_env):
        s = Settings()  # type: ignore[call-arg]
        assert s.smtp_user == "test@gmail.com"
        assert s.smtp_password.get_secret_value() == "test-app-password"
        assert str(s.mail_to) == "recipient@example.com"

    def test_missing_required_raises(self, monkeypatch):
        monkeypatch.delenv("SMTP_USER", raising=False)
        monkeypatch.delenv("SMTP_PASSWORD", raising=False)
        monkeypatch.delenv("MAIL_TO", raising=False)
        monkeypatch.chdir("/tmp")
        with pytest.raises(ValidationError):
            Settings()  # type: ignore[call-arg]

    def test_invalid_email_rejected(self, monkeypatch):
        monkeypatch.setenv("SMTP_USER", "test@gmail.com")
        monkeypatch.setenv("SMTP_PASSWORD", "x")
        monkeypatch.setenv("MAIL_TO", "not-an-email")
        monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://va_app:x@localhost/value_analyzer")
        monkeypatch.chdir("/tmp")
        with pytest.raises(ValidationError):
            Settings()  # type: ignore[call-arg]

    def test_effective_mail_from_falls_back_to_smtp_user(self, minimal_env):
        s = Settings()  # type: ignore[call-arg]
        assert s.effective_mail_from == "test@gmail.com"

    def test_weights_renormalised(self, monkeypatch, minimal_env):
        monkeypatch.setenv("VALUE_WEIGHT", "1.0")
        monkeypatch.setenv("QUALITY_WEIGHT", "1.0")  # Summe 2.0
        s = Settings()  # type: ignore[call-arg]
        assert abs(s.value_weight - 0.5) < 1e-6
        assert abs(s.quality_weight - 0.5) < 1e-6

    def test_top_n_validation(self, monkeypatch, minimal_env):
        monkeypatch.setenv("TOP_N", "0")
        with pytest.raises(ValidationError):
            Settings()  # type: ignore[call-arg]

    def test_invalid_universe_literal(self, monkeypatch, minimal_env):
        monkeypatch.setenv("UNIVERSE", "S&P500")
        with pytest.raises(ValidationError):
            Settings()  # type: ignore[call-arg]

    def test_database_url_is_required(self, minimal_env, monkeypatch):
        monkeypatch.delenv("DATABASE_URL")
        with pytest.raises(ValidationError, match="database_url"):
            Settings()  # type: ignore[call-arg]

    def test_database_urls_are_secret(self, minimal_env, monkeypatch):
        monkeypatch.setenv("DATABASE_OWNER_URL", "postgresql+psycopg://va_owner:geheim@db/x")
        s = Settings()  # type: ignore[call-arg]
        assert "geheim" not in repr(s)
        assert s.database_url.get_secret_value().startswith("postgresql+psycopg://va_app")
        assert s.database_owner_url is not None
        assert "geheim" in s.database_owner_url.get_secret_value()

    def test_owner_url_defaults_to_none(self, minimal_env):
        assert Settings().database_owner_url is None  # type: ignore[call-arg]

    def test_retention_days_is_gone(self, minimal_env):
        # Daten werden nie mehr geloescht - die alte Einstellung existiert nicht mehr
        assert not hasattr(Settings(), "retention_days")  # type: ignore[call-arg]

    def test_smtp_plain_is_off_by_default(self, minimal_env):
        # U1: ohne TLS und ohne Login nur fuer den lokalen Mail-Catcher, nie aus Versehen
        assert Settings().smtp_plain is False  # type: ignore[call-arg]

    def test_smtp_plain_reaches_the_sender(self, minimal_env, monkeypatch):
        from src.composition import smtp_config

        monkeypatch.setenv("SMTP_PLAIN", "true")
        assert smtp_config(Settings()).plain is True  # type: ignore[call-arg]


class TestReplaySource:
    """U5.1: Replay-Daten nur mit einem lokalen Mail-Catcher und ohne Healthcheck."""

    @pytest.fixture
    def fixture_file(self, tmp_path):
        path = tmp_path / "woche.json"
        path.write_text("{}", encoding="utf-8")
        return path

    @pytest.fixture
    def local_env(self, minimal_env, monkeypatch):
        monkeypatch.setenv("SMTP_PLAIN", "true")
        monkeypatch.delenv("HEALTHCHECK_URL", raising=False)

    def test_is_off_by_default(self, minimal_env):
        assert Settings().replay_source is None  # type: ignore[call-arg]

    def test_local_setup_accepts_an_existing_file(self, local_env, monkeypatch, fixture_file):
        monkeypatch.setenv("REPLAY_SOURCE", str(fixture_file))
        assert Settings().replay_source == fixture_file  # type: ignore[call-arg]

    def test_missing_file_is_rejected(self, local_env, monkeypatch, tmp_path):
        monkeypatch.setenv("REPLAY_SOURCE", str(tmp_path / "fehlt.json"))
        with pytest.raises(ValidationError):
            Settings()  # type: ignore[call-arg]

    def test_rejected_with_a_real_mail_server(self, minimal_env, monkeypatch, fixture_file):
        monkeypatch.setenv("REPLAY_SOURCE", str(fixture_file))
        with pytest.raises(ValidationError, match="SMTP_PLAIN"):
            Settings()  # type: ignore[call-arg]

    def test_rejected_with_a_healthcheck(self, local_env, monkeypatch, fixture_file):
        monkeypatch.setenv("REPLAY_SOURCE", str(fixture_file))
        monkeypatch.setenv("HEALTHCHECK_URL", "https://hc-ping.com/abc")
        with pytest.raises(ValidationError, match="HEALTHCHECK_URL"):
            Settings()  # type: ignore[call-arg]


class TestEventBus:
    """P4.3: Der Batch laeuft im Prozess, ueber NATS nur auf ausdruecklichen Wunsch."""

    def test_in_process_is_the_default(self, minimal_env):
        settings = Settings()  # type: ignore[call-arg]
        assert settings.event_bus == "in_process"
        assert settings.nats_url is None
        assert settings.run_timeout_minutes == 120

    def test_nats_needs_a_url(self, monkeypatch, minimal_env):
        monkeypatch.setenv("EVENT_BUS", "nats")
        with pytest.raises(ValidationError, match="NATS_URL"):
            Settings()  # type: ignore[call-arg]

    def test_nats_with_url(self, monkeypatch, minimal_env):
        monkeypatch.setenv("EVENT_BUS", "nats")
        monkeypatch.setenv("NATS_URL", "nats://nats:4222")
        assert Settings().nats_url == "nats://nats:4222"  # type: ignore[call-arg]

    def test_unknown_bus_is_rejected(self, monkeypatch, minimal_env):
        monkeypatch.setenv("EVENT_BUS", "kafka")
        with pytest.raises(ValidationError):
            Settings()  # type: ignore[call-arg]
