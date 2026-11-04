"""Settings je Service (P5.1a): jeder Service liest nur seine Felder, der Batch erbt alle.

Ein Image je Service (P5.1) bekommt nur seine Variablen. Damit kein Feld an zwei Stellen steht,
setzt sich ``src.config.Settings`` aus den Settings der drei Services zusammen.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from src.config import Settings
from va_market_data.entrypoints.settings import MarketDataSettings
from va_notification.entrypoints.settings import NotificationSettings
from va_platform.service import ServiceSettings
from va_scoring.entrypoints.settings import ScoringSettings

DB = "postgresql+psycopg://va_app:x@db:5432/value_analyzer"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch, tmp_path):
    """Keine .env und keine Variablen des Testlaufs: Jeder Test setzt, was er braucht."""
    monkeypatch.chdir(tmp_path)
    for name in ("DATABASE_URL", "NATS_URL", "SMTP_USER", "SMTP_PASSWORD", "MAIL_TO"):
        monkeypatch.delenv(name, raising=False)


class TestShared:
    def test_every_service_needs_a_database(self):
        for settings in (MarketDataSettings, ScoringSettings, NotificationSettings):
            assert issubclass(settings, ServiceSettings)
            with pytest.raises(ValidationError, match="database_url"):
                settings()  # type: ignore[call-arg]

    def test_defaults(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", DB)
        monkeypatch.setenv("NATS_URL", "nats://nats:4222")
        settings = ScoringSettings()  # type: ignore[call-arg]
        assert settings.nats_url == "nats://nats:4222"
        assert settings.run_timeout_minutes == 120
        assert settings.logs_dir == Path("/app/logs")


class TestMarketData:
    def test_only_its_own_fields(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", DB)
        settings = MarketDataSettings()  # type: ignore[call-arg]
        assert (settings.universe, settings.default_tax_rate) == ("DAX_MDAX", 0.27)
        assert settings.replay_source is None
        assert settings.fallback_csv == Path("data/dax_mdax_fallback.csv")
        assert not hasattr(settings, "smtp_user")


class TestScoring:
    def test_start_values_of_the_standard_profile(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", DB)
        settings = ScoringSettings()  # type: ignore[call-arg]
        assert (settings.min_market_cap, settings.value_weight, settings.quality_weight) == (
            300_000_000.0,
            0.6,
            0.4,
        )

    def test_weights_are_normalised(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", DB)
        settings = ScoringSettings(value_weight=0.9, quality_weight=0.3)  # type: ignore[call-arg]
        assert (settings.value_weight, settings.quality_weight) == pytest.approx((0.75, 0.25))


class TestNotification:
    def test_needs_mail_credentials(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", DB)
        with pytest.raises(ValidationError, match="smtp_user"):
            NotificationSettings()  # type: ignore[call-arg]

    def test_sender_defaults_to_the_smtp_user(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", DB)
        monkeypatch.setenv("SMTP_USER", "absender@gmail.com")
        monkeypatch.setenv("SMTP_PASSWORD", "pw")
        monkeypatch.setenv("MAIL_TO", "empfaenger@example.com")
        settings = NotificationSettings()  # type: ignore[call-arg]
        assert settings.effective_mail_from == "absender@gmail.com"
        assert (settings.top_n, settings.bottom_n) == (20, 10)
        assert not hasattr(settings, "universe")


class TestBatch:
    def test_the_batch_inherits_every_service(self):
        for settings in (MarketDataSettings, ScoringSettings, NotificationSettings):
            assert issubclass(Settings, settings)

    def test_each_field_has_one_home(self):
        services = (MarketDataSettings, ScoringSettings, NotificationSettings)
        shared = set(ServiceSettings.model_fields)
        seen: dict[str, str] = {}
        for settings in services:
            for name in set(settings.model_fields) - shared:
                assert name not in seen, f"{name} in {settings.__name__} und {seen[name]}"
                seen[name] = settings.__name__
