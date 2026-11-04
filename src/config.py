"""Konfiguration via Pydantic Settings.

Liest aus Umgebungsvariablen und (zur lokalen Entwicklung) aus einer .env-Datei.
Validiert beim Laden: fehlende Pflichtfelder, falsche Typen und ungueltige
E-Mail-Adressen produzieren sprechende Fehlermeldungen statt eines stillen
Defaults oder eines spaeten Stacktraces im Mailversand.
"""

from __future__ import annotations

from typing import Literal

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from va_market_data.entrypoints.settings import MarketDataSettings
from va_notification.entrypoints.settings import NotificationSettings
from va_scoring.entrypoints.settings import ScoringSettings

_MODEL_CONFIG = SettingsConfigDict(
    env_file=".env",
    env_file_encoding="utf-8",
    case_sensitive=False,
    extra="ignore",
)


class _OwnerUrl(BaseSettings):
    model_config = _MODEL_CONFIG

    # Owner-Rolle nur fuer Migrationen beim Container-Start; None = database_url
    database_owner_url: SecretStr | None = None


class DatabaseSettings(_OwnerUrl):
    """Nur die DB-Verbindung - reicht fuer Migration und Altdaten-Import."""

    database_url: SecretStr | None = None
    # P3.3: Passwort der Rolle va_profiles; gesetzt legt die Migration sie an und gleicht es an
    va_profiles_password: SecretStr | None = None
    # P4.4: Passwort der Rolle va_web (Projektionen des web-api im Schema web), ebenso
    va_web_password: SecretStr | None = None


class Settings(MarketDataSettings, ScoringSettings, NotificationSettings, _OwnerUrl):
    """Anwendungs-Settings - alle Felder sind ENV-Variablen.

    Seit P5.1a erbt der Batch die Felder der drei Services (``va_<service>.entrypoints.settings``,
    gemeinsame in ``va_platform.service.ServiceSettings``: Datenbank, NATS, Zeitlimit, Logs). Hier
    steht nur, was allein der Batch braucht.
    """

    # --- Operatives ---
    cron_schedule: str = "30 7 * * 6"  # Sa 07:30 Europe/Berlin
    tz: str = "Europe/Berlin"

    # --- Event-Bus (P4.3, docs/architecture/events.md) ---
    # in_process: die Kette laeuft im Batch-Prozess (Standard, auch auf der NAS).
    # nats: ueber NATS JetStream; seit P4.3b verarbeitet jeder Service ein Event nur einmal.
    event_bus: Literal["in_process", "nats"] = "in_process"

    @model_validator(mode="after")
    def _nats_needs_a_url(self) -> Settings:
        if self.event_bus == "nats" and not (self.nats_url or "").strip():
            msg = "EVENT_BUS=nats braucht NATS_URL (z. B. nats://nats:4222)"
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def _replay_only_locally(self) -> Settings:
        """Eine Mail mit Replay-Daten darf nie ueber einen echten Mailserver hinausgehen."""
        if self.replay_source is None:
            return self
        if not self.smtp_plain:
            msg = "REPLAY_SOURCE nur mit SMTP_PLAIN (lokaler Mail-Catcher wie Mailpit)"
            raise ValueError(msg)
        if self.healthcheck_url:
            msg = "REPLAY_SOURCE nur ohne HEALTHCHECK_URL (sonst verdeckt der Ping die NAS)"
            raise ValueError(msg)
        return self


def load_settings() -> Settings:
    """Convenience-Wrapper."""
    return Settings()  # type: ignore[call-arg]
