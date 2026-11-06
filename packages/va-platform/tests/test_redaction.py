"""Keine Geheimnisse und Mail-Adressen in Logs (D1.2, Sicherheitsregel 7 in nutzer.md).

Der Filter haengt an den Handlern und schwaerzt jede Zeile, egal welcher Logger sie schreibt.
"""

from __future__ import annotations

import io
import logging

import pytest

from va_platform.redaction import RedactingFilter, install_redaction, redact


@pytest.mark.parametrize(
    ("text", "secret"),
    [
        ("Mail an dennis@example.com versendet", "dennis@example.com"),
        ("password=Kiefer-Wolke-42 abgelehnt", "Kiefer-Wolke-42"),
        ("Passwort: 'geheim 123' falsch", "geheim 123"),
        ("pin=12345 fuer Abruf", "12345"),
        ("TAN = 998877", "998877"),
        ("token=abc.def.ghi", "abc.def.ghi"),
        ('secret: "s3cr3t"', "s3cr3t"),
        ("session_id=Zx9", "Zx9"),
        ("Verbinde postgresql+psycopg://va_web:Geheim42@db:5432/x", "Geheim42"),
    ],
)
def test_secrets_and_addresses_are_blacked_out(text, secret):
    assert secret not in redact(text)


@pytest.mark.parametrize(
    "text",
    [
        "Lauf 42 fertig: 90 Titel",
        "Token abgelaufen",  # ohne Wert
        "Spinner gestartet",  # pin nur als Teil eines Wortes
        "postgresql+psycopg://db:5432/value_analyzer",
    ],
)
def test_ordinary_lines_stay_unchanged(text):
    assert redact(text) == text


def test_the_filter_works_with_format_arguments():
    record = logging.LogRecord(
        "x", logging.INFO, __file__, 1, "Mail an %s: %s", ("a@b.de", "ok"), None
    )
    assert RedactingFilter().filter(record)
    assert "a@b.de" not in record.getMessage()
    assert "ok" in record.getMessage()


def test_tracebacks_are_blacked_out_too():
    try:
        raise RuntimeError("Login fuer anna@example.com mit token=abc123 gescheitert")
    except RuntimeError:
        import sys

        record = logging.LogRecord("x", logging.ERROR, __file__, 1, "Fehler", None, sys.exc_info())
    RedactingFilter().filter(record)
    text = logging.Formatter().format(record)
    assert "RuntimeError" in text
    assert "anna@example.com" not in text
    assert "abc123" not in text


def test_install_puts_the_filter_on_every_handler():
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    logger = logging.getLogger("va_test_redaction")
    logger.addHandler(handler)
    logger.propagate = False
    try:
        install_redaction("va_test_redaction")
        install_redaction("va_test_redaction")  # doppelt aufgerufen: ein Filter
        logger.warning("Anmeldung fuer anna@example.com, password=xyz")
        assert "anna@example.com" not in stream.getvalue()
        assert "xyz" not in stream.getvalue()
        assert sum(isinstance(f, RedactingFilter) for f in handler.filters) == 1
    finally:
        logger.removeHandler(handler)
