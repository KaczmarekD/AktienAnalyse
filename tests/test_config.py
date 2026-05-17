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
