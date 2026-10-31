"""Settings des web-api: nur was das web-api braucht, mit eigenem Praefix ``WEB_API_``.

Die Zugangsdaten des Batches (``DATABASE_URL``, SMTP) sieht das web-api nie. Es liest mit der
Rolle ``va_read`` (U4, docs/architecture/umgebungen.md).
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
