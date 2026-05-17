"""Konfiguration via Pydantic Settings.

Liest aus Umgebungsvariablen und (zur lokalen Entwicklung) aus einer .env-Datei.
Validiert beim Laden: fehlende Pflichtfelder, falsche Typen und ungueltige
E-Mail-Adressen produzieren sprechende Fehlermeldungen statt eines stillen
Defaults oder eines spaeten Stacktraces im Mailversand.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import EmailStr, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Anwendungs-Settings - alle Felder sind ENV-Variablen."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- SMTP ---
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = Field(default=587, gt=0, lt=65536)
    smtp_user: str = Field(min_length=1)
    smtp_password: SecretStr = Field(min_length=1)
    smtp_use_tls: bool = True

    # --- Mail ---
    mail_from: EmailStr | None = None  # default: smtp_user
    mail_to: EmailStr
    mail_subject_prefix: str = "[Value-Screening DAX/MDAX]"

    # --- Universum & Reporting ---
    universe: Literal["DAX_MDAX", "DAX_ONLY"] = "DAX_MDAX"
    top_n: int = Field(default=20, ge=1, le=200)
    bottom_n: int = Field(default=10, ge=0, le=100)
    min_market_cap: float = Field(default=300_000_000.0, ge=0)

    # --- Scoring (optional override) ---
    value_weight: float = Field(default=0.6, ge=0, le=1)
    quality_weight: float = Field(default=0.4, ge=0, le=1)
    default_tax_rate: float = Field(default=0.27, ge=0, le=0.6)

    # --- Operatives ---
    data_dir: Path = Path("/app/data")
    logs_dir: Path = Path("/app/logs")
    healthcheck_url: str | None = None  # https://hc-ping.com/<uuid>
    cron_schedule: str = "30 7 * * 6"  # Sa 07:30 Europe/Berlin
    tz: str = "Europe/Berlin"

    @field_validator("value_weight", "quality_weight")
    @classmethod
    def _weights_sane(cls, v: float) -> float:
        # Validierung der Summe erfolgt in model_validator unten - hier nur die einzelne Range.
        return v

    @property
    def effective_mail_from(self) -> str:
        return str(self.mail_from) if self.mail_from else self.smtp_user

    def model_post_init(self, __context: object) -> None:
        # Summe von value + quality muss ~1 sein - sonst stillschweigend skalieren
        total = self.value_weight + self.quality_weight
        if total <= 0:
            msg = "value_weight + quality_weight muss > 0 sein"
            raise ValueError(msg)
        if abs(total - 1.0) > 0.01:
            # Re-normalisieren ohne Exception (UX-freundlich).
            # __dict__ ist bei Pydantic v2 ein MappingProxy - object.__setattr__ umgeht das.
            object.__setattr__(self, "value_weight", self.value_weight / total)
            object.__setattr__(self, "quality_weight", self.quality_weight / total)


def load_settings() -> Settings:
    """Convenience-Wrapper."""
    return Settings()  # type: ignore[call-arg]
