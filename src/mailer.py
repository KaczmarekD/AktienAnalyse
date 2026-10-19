"""Uebergang bis P1.8: verdrahtet den SMTP-Adapter mit den Settings des Batches."""

from __future__ import annotations

from typing import TYPE_CHECKING

from va_notification.adapters.smtp import SmtpConfig, SmtpSender

if TYPE_CHECKING:
    from .config import Settings


def smtp_config(settings: Settings) -> SmtpConfig:
    return SmtpConfig(
        host=settings.smtp_host,
        port=settings.smtp_port,
        user=settings.smtp_user,
        password=settings.smtp_password.get_secret_value(),
        use_tls=settings.smtp_use_tls,
        mail_from=settings.effective_mail_from,
        mail_to=str(settings.mail_to),
        subject_prefix=settings.mail_subject_prefix,
    )


def send_report(
    settings: Settings,
    subject: str,
    html_body: str,
    attachment: tuple[str, bytes] | None = None,
) -> None:
    """Versendet den Report. ``attachment`` = (Dateiname, CSV-Bytes)."""
    SmtpSender(smtp_config(settings)).send(subject, html_body, attachment)
