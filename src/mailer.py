"""SMTP-Mailversand fuer Reports und Fehler-Notifications."""

from __future__ import annotations

import logging
import smtplib
import ssl
from email.message import EmailMessage
from pathlib import Path

from .config import Settings

log = logging.getLogger(__name__)


def send_report(
    settings: Settings,
    subject: str,
    html_body: str,
    attachment: Path | None = None,
) -> None:
    msg = EmailMessage()
    full_subject = f"{settings.mail_subject_prefix} {subject}".strip()
    msg["Subject"] = full_subject
    msg["From"] = settings.effective_mail_from
    msg["To"] = str(settings.mail_to)

    msg.set_content(
        "Dieser Report enthaelt HTML. Bitte in einem Mail-Client mit HTML-Anzeige oeffnen. "
        "Das vollstaendige Ranking liegt als CSV-Anhang bei.",
    )
    msg.add_alternative(html_body, subtype="html")

    if attachment and attachment.exists():
        data = attachment.read_bytes()
        msg.add_attachment(
            data,
            maintype="text",
            subtype="csv",
            filename=attachment.name,
        )
        log.info("CSV-Anhang angehaengt: %s (%.1f KB)", attachment.name, len(data) / 1024)

    log.info(
        "Verbinde zu SMTP %s:%d (TLS=%s)",
        settings.smtp_host,
        settings.smtp_port,
        settings.smtp_use_tls,
    )
    context = ssl.create_default_context()
    password = settings.smtp_password.get_secret_value()

    if settings.smtp_use_tls:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as s:
            s.ehlo()
            s.starttls(context=context)
            s.ehlo()
            s.login(settings.smtp_user, password)
            s.send_message(msg)
    else:
        with smtplib.SMTP_SSL(
            settings.smtp_host, settings.smtp_port, context=context, timeout=30
        ) as s:
            s.login(settings.smtp_user, password)
            s.send_message(msg)
    log.info("Mail an %s versendet: %s", settings.mail_to, full_subject)
