"""Settings des web-api: nur was das web-api braucht, mit eigenem Praefix ``WEB_API_``.

Die Zugangsdaten des Batches (``DATABASE_URL``, SMTP) sieht das web-api nie. Es liest mit der
Rolle ``va_read`` (U4, docs/architecture/umgebungen.md) und speichert Scoring-Profile mit der
Rolle ``va_profiles`` (P3.3), die nur in die Profil-Tabellen anfuegen darf. Die Projektionen
(P4.4) schreibt es mit der Rolle ``va_web`` ins Schema ``web``, gespeist aus NATS.
"""

from __future__ import annotations

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class WebApiSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="WEB_API_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # postgresql+psycopg://va_read:<pw>@db:5432/value_analyzer
    database_url: SecretStr = Field(min_length=1)
    # postgresql+psycopg://va_profiles:<pw>@db:5432/value_analyzer - ohne: Speichern ergibt 503
    profiles_database_url: SecretStr | None = None
    # P4.4: Event-Consumer fuer die Projektionen. Nur mit beidem, sonst laeuft die App ohne.
    # nats://nats:4222
    nats_url: str | None = None
    # postgresql+psycopg://va_web:<pw>@db:5432/value_analyzer
    projections_database_url: SecretStr | None = None
