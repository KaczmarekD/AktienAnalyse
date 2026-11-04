"""Settings von notification (P5.1a): Mail, Healthcheck, Umfang des Reports. Der Batch erbt sie."""

from __future__ import annotations

from pathlib import Path

from pydantic import EmailStr, Field, SecretStr

from va_platform.service import ServiceSettings


class NotificationSettings(ServiceSettings):
    # --- SMTP ---
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = Field(default=587, gt=0, lt=65536)
    smtp_user: str = Field(min_length=1)
    smtp_password: SecretStr = Field(min_length=1)
    smtp_use_tls: bool = True
    # Ohne TLS und ohne Login, nur fuer den lokalen Mail-Catcher (U1, umgebungen.md)
    smtp_plain: bool = False

    # --- Mail ---
    mail_from: EmailStr | None = None  # default: smtp_user
    mail_to: EmailStr
    mail_subject_prefix: str = "[Value-Screening DAX/MDAX]"

    # --- Report ---
    top_n: int = Field(default=20, ge=1, le=200)
    bottom_n: int = Field(default=10, ge=0, le=100)
    data_dir: Path = Path("/app/data")  # Vorschau eines Dry-Runs (HTML und CSV)
    healthcheck_url: str | None = None  # https://hc-ping.com/<uuid>

    @property
    def effective_mail_from(self) -> str:
        return str(self.mail_from) if self.mail_from else self.smtp_user
