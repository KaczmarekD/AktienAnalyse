"""Tests fuer den SMTP-Mailversand (src/mailer.py).

smtplib.SMTP wird vollstaendig gemockt - kein echter Netz-Call.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.mailer import send_report

# ---------------------------------------------------------------------------
# Hilfs-Fixture: minimale Settings
# ---------------------------------------------------------------------------


@pytest.fixture
def settings(tmp_path, monkeypatch):
    monkeypatch.setenv("SMTP_USER", "sender@gmail.com")
    monkeypatch.setenv("SMTP_PASSWORD", "test-app-password")
    monkeypatch.setenv("MAIL_TO", "empfaenger@example.com")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://va_app:x@localhost/value_analyzer")
    monkeypatch.chdir(tmp_path)

    from src.config import Settings

    return Settings()  # type: ignore[call-arg]


@pytest.fixture
def csv_attachment() -> tuple[str, bytes]:
    return "ranking_20260517.csv", "symbol;score\nSAP.DE;0.85\n".encode("utf-8-sig")


# ---------------------------------------------------------------------------
# Betreff und Adressierung
# ---------------------------------------------------------------------------


class TestMailHeaders:
    def test_subject_contains_prefix(self, settings):
        with patch("smtplib.SMTP") as MockSMTP:
            MockSMTP.return_value.__enter__ = lambda s: s
            MockSMTP.return_value.__exit__ = MagicMock(return_value=False)
            smtp_instance = MockSMTP.return_value
            smtp_instance.send_message = MagicMock()

            send_report(settings, subject="[ok 110/110] Test", html_body="<p>hi</p>")

        msg = smtp_instance.send_message.call_args.args[0]
        assert "[Value-Screening DAX/MDAX]" in msg["Subject"]
        assert "[ok 110/110] Test" in msg["Subject"]

    def test_to_and_from_set_correctly(self, settings):
        with patch("smtplib.SMTP") as MockSMTP:
            MockSMTP.return_value.__enter__ = lambda s: s
            MockSMTP.return_value.__exit__ = MagicMock(return_value=False)
            smtp_instance = MockSMTP.return_value
            smtp_instance.send_message = MagicMock()

            send_report(settings, subject="Test", html_body="<p>hi</p>")

        msg = smtp_instance.send_message.call_args.args[0]
        assert msg["To"] == "empfaenger@example.com"
        assert msg["From"] == "sender@gmail.com"


# ---------------------------------------------------------------------------
# HTML-Inhalt
# ---------------------------------------------------------------------------


class TestMailBody:
    def test_html_alternative_present(self, settings):
        html = "<h1>Report</h1><p>Inhalt</p>"

        with patch("smtplib.SMTP") as MockSMTP:
            MockSMTP.return_value.__enter__ = lambda s: s
            MockSMTP.return_value.__exit__ = MagicMock(return_value=False)
            smtp_instance = MockSMTP.return_value
            smtp_instance.send_message = MagicMock()

            send_report(settings, subject="Test", html_body=html)

        msg = smtp_instance.send_message.call_args.args[0]
        # EmailMessage mit add_alternative erzeugt multipart/alternative
        payload = msg.get_payload()
        assert any(
            part.get_content_type() == "text/html"
            for part in (payload if isinstance(payload, list) else [msg])
        )


# ---------------------------------------------------------------------------
# CSV-Anhang
# ---------------------------------------------------------------------------


class TestCsvAttachment:
    def test_attachment_added(self, settings, csv_attachment):
        with patch("smtplib.SMTP") as MockSMTP:
            MockSMTP.return_value.__enter__ = lambda s: s
            MockSMTP.return_value.__exit__ = MagicMock(return_value=False)
            smtp_instance = MockSMTP.return_value
            smtp_instance.send_message = MagicMock()

            send_report(settings, subject="Test", html_body="<p>x</p>", attachment=csv_attachment)

        msg = smtp_instance.send_message.call_args.args[0]
        payload = msg.get_payload()
        filenames = [
            part.get_filename()
            for part in (payload if isinstance(payload, list) else [])
            if part.get_filename()
        ]
        assert csv_attachment[0] in filenames
        part = next(p for p in payload if p.get_filename())
        assert part.get_payload(decode=True) == csv_attachment[1]

    def test_no_attachment_when_path_is_none(self, settings):
        with patch("smtplib.SMTP") as MockSMTP:
            MockSMTP.return_value.__enter__ = lambda s: s
            MockSMTP.return_value.__exit__ = MagicMock(return_value=False)
            smtp_instance = MockSMTP.return_value
            smtp_instance.send_message = MagicMock()

            send_report(settings, subject="Test", html_body="<p>x</p>", attachment=None)

        msg = smtp_instance.send_message.call_args.args[0]
        payload = msg.get_payload()
        filenames = [
            part.get_filename()
            for part in (payload if isinstance(payload, list) else [])
            if part.get_filename()
        ]
        assert filenames == []


# ---------------------------------------------------------------------------
# SMTP-Verbindung (TLS vs. SSL)
# ---------------------------------------------------------------------------


class TestSmtpConnection:
    def test_starttls_used_when_tls_true(self, settings):
        with patch("smtplib.SMTP") as MockSMTP:
            MockSMTP.return_value.__enter__ = lambda s: s
            MockSMTP.return_value.__exit__ = MagicMock(return_value=False)
            smtp_instance = MockSMTP.return_value
            smtp_instance.send_message = MagicMock()

            send_report(settings, subject="Test", html_body="<p>x</p>")

        MockSMTP.assert_called_once()
        smtp_instance.starttls.assert_called_once()
        smtp_instance.login.assert_called_once_with("sender@gmail.com", "test-app-password")

    def test_smtp_ssl_used_when_tls_false(self, settings, monkeypatch):
        monkeypatch.setenv("SMTP_USE_TLS", "false")
        from src.config import Settings

        settings_no_tls = Settings()  # type: ignore[call-arg]

        with patch("smtplib.SMTP_SSL") as MockSMTPSSL:
            MockSMTPSSL.return_value.__enter__ = lambda s: s
            MockSMTPSSL.return_value.__exit__ = MagicMock(return_value=False)
            smtp_instance = MockSMTPSSL.return_value
            smtp_instance.send_message = MagicMock()

            send_report(settings_no_tls, subject="Test", html_body="<p>x</p>")

        MockSMTPSSL.assert_called_once()

    def test_correct_smtp_host_and_port_used(self, settings):
        with patch("smtplib.SMTP") as MockSMTP:
            MockSMTP.return_value.__enter__ = lambda s: s
            MockSMTP.return_value.__exit__ = MagicMock(return_value=False)
            MockSMTP.return_value.send_message = MagicMock()

            send_report(settings, subject="Test", html_body="<p>x</p>")

        call_args = MockSMTP.call_args
        assert call_args.args[0] == "smtp.gmail.com"
        assert call_args.args[1] == 587
