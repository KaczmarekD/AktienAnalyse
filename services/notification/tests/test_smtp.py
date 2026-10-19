"""SMTP-Adapter (P1.6) gegen ein Fake-SMTP: Port ``ReportSender`` ohne globale Settings."""

from __future__ import annotations

from email.message import EmailMessage
from typing import Any, ClassVar
from unittest.mock import patch

import pytest

from va_notification.adapters.smtp import SmtpConfig, SmtpSender

CONFIG = SmtpConfig(
    host="smtp.example.com",
    port=587,
    user="sender@example.com",
    password="geheim",
    use_tls=True,
    mail_from="sender@example.com",
    mail_to="empfaenger@example.com",
    subject_prefix="[Value-Screening]",
)


class FakeSmtp:
    """Merkt sich Verbindung, Anmeldung und Nachrichten."""

    instances: ClassVar[list[FakeSmtp]] = []

    def __init__(self, host: str, port: int, **kwargs: Any) -> None:
        self.host, self.port, self.kwargs = host, port, kwargs
        self.calls: list[str] = []
        self.login_args: tuple[str, str] | None = None
        self.messages: list[EmailMessage] = []
        FakeSmtp.instances.append(self)

    def __enter__(self) -> FakeSmtp:
        return self

    def __exit__(self, *exc: object) -> None:
        self.calls.append("quit")

    def ehlo(self) -> None:
        self.calls.append("ehlo")

    def starttls(self, context: Any = None) -> None:
        self.calls.append("starttls")

    def login(self, user: str, password: str) -> None:
        self.calls.append("login")
        self.login_args = (user, password)

    def send_message(self, msg: EmailMessage) -> None:
        self.calls.append("send")
        self.messages.append(msg)


@pytest.fixture
def fake_smtp():
    FakeSmtp.instances = []
    with (
        patch("va_notification.adapters.smtp.smtplib.SMTP", FakeSmtp),
        patch("va_notification.adapters.smtp.smtplib.SMTP_SSL", FakeSmtp),
    ):
        yield FakeSmtp.instances


class TestSmtpSender:
    def test_tls_login_and_send(self, fake_smtp):
        SmtpSender(CONFIG).send("[ok 90/90] Test", "<p>hi</p>")
        (server,) = fake_smtp
        assert (server.host, server.port) == ("smtp.example.com", 587)
        assert server.calls == ["ehlo", "starttls", "ehlo", "login", "send", "quit"]
        assert server.login_args == ("sender@example.com", "geheim")

    def test_ssl_without_starttls(self, fake_smtp):
        from dataclasses import replace

        SmtpSender(replace(CONFIG, use_tls=False, port=465)).send("Test", "<p>hi</p>")
        (server,) = fake_smtp
        assert "starttls" not in server.calls
        assert server.calls[-2:] == ["send", "quit"]

    def test_headers_and_html(self, fake_smtp):
        SmtpSender(CONFIG).send("[ok 90/90] Test", "<h1>Report</h1>")
        msg = fake_smtp[0].messages[0]
        assert msg["Subject"] == "[Value-Screening] [ok 90/90] Test"
        assert (msg["From"], msg["To"]) == ("sender@example.com", "empfaenger@example.com")
        html = msg.get_body(preferencelist=("html",))
        assert html is not None
        assert "<h1>Report</h1>" in html.get_content()

    def test_csv_attachment(self, fake_smtp):
        data = "symbol;score\nSAP.DE;0,85\n".encode("utf-8-sig")
        SmtpSender(CONFIG).send("Test", "<p>x</p>", attachment=("ranking.csv", data))
        parts = list(fake_smtp[0].messages[0].iter_attachments())
        assert [p.get_filename() for p in parts] == ["ranking.csv"]
        assert parts[0].get_payload(decode=True) == data

    def test_without_prefix_the_subject_stays(self, fake_smtp):
        from dataclasses import replace

        SmtpSender(replace(CONFIG, subject_prefix="")).send("Nur der Betreff", "<p>x</p>")
        assert fake_smtp[0].messages[0]["Subject"] == "Nur der Betreff"
