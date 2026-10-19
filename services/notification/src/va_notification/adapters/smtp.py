"""SMTP-Versand fuer Reports und Fehlermails (Port ``ReportSender``)."""

from __future__ import annotations

import logging
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class SmtpConfig:
    """Alles, was der Versand braucht - unabhaengig von den Settings des Batches."""

    host: str
    port: int
    user: str
    password: str
    use_tls: bool  # STARTTLS; sonst direkt SSL
    mail_from: str
    mail_to: str
    subject_prefix: str = ""


class SmtpSender:
    """``ReportSender`` ueber SMTP (Gmail: App-Passwort)."""

    def __init__(self, config: SmtpConfig) -> None:
        self._config = config

    def send(
        self, subject: str, html_body: str, attachment: tuple[str, bytes] | None = None
    ) -> None:
        cfg = self._config
        msg = EmailMessage()
        full_subject = f"{cfg.subject_prefix} {subject}".strip()
        msg["Subject"] = full_subject
        msg["From"] = cfg.mail_from
        msg["To"] = cfg.mail_to

        msg.set_content(
            "Dieser Report enthaelt HTML. Bitte in einem Mail-Client mit HTML-Anzeige oeffnen. "
            "Das vollstaendige Ranking liegt als CSV-Anhang bei.",
        )
        msg.add_alternative(html_body, subtype="html")

        if attachment:
            filename, data = attachment
            msg.add_attachment(data, maintype="text", subtype="csv", filename=filename)
            log.info("CSV-Anhang angehaengt: %s (%.1f KB)", filename, len(data) / 1024)

        log.info("Verbinde zu SMTP %s:%d (TLS=%s)", cfg.host, cfg.port, cfg.use_tls)
        context = ssl.create_default_context()
        if cfg.use_tls:
            with smtplib.SMTP(cfg.host, cfg.port, timeout=30) as s:
                s.ehlo()
                s.starttls(context=context)
                s.ehlo()
                s.login(cfg.user, cfg.password)
                s.send_message(msg)
        else:
            with smtplib.SMTP_SSL(cfg.host, cfg.port, context=context, timeout=30) as s:
                s.login(cfg.user, cfg.password)
                s.send_message(msg)
        log.info("Mail an %s versendet: %s", cfg.mail_to, full_subject)
