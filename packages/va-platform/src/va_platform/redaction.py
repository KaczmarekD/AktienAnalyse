"""Keine Geheimnisse und Mail-Adressen in Logs (D1.2, Sicherheitsregel 7 in
docs/architecture/depot/nutzer.md).

``RedactingFilter`` schwaerzt in jeder Log-Zeile Mail-Adressen und die Werte hinter
``password``, ``passwort``, ``pin``, ``tan``, ``token``, ``secret`` und ``session``. Er haengt an
den Handlern (``install_redaction``), nicht an Loggern: Ein Filter am Logger saehe die Zeilen
seiner Kind-Logger nicht. Tracebacks (``exc_info``) werden ebenso geschwaerzt.
"""

from __future__ import annotations

import logging
import re

EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
SECRET_VALUE = re.compile(
    r"(?i)\b(password|passwort|pin|tan|token|secret|session(?:_id)?)\b"
    r"(\s*[=:]\s*)"
    r"(\"[^\"]*\"|'[^']*'|\S+)"
)
URL_PASSWORD = re.compile(r"(://[^:/@\s]+:)([^@\s]+)(@)")
MASK = "***"


def redact(text: str) -> str:
    text = URL_PASSWORD.sub(lambda m: f"{m.group(1)}{MASK}{m.group(3)}", text)
    text = SECRET_VALUE.sub(lambda m: f"{m.group(1)}{m.group(2)}{MASK}", text)
    return EMAIL.sub("<mail>", text)


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        clean = redact(message)
        if clean != message:
            record.msg, record.args = clean, None
        if record.exc_info and not record.exc_text:
            # Der Formatter nimmt exc_text, wenn gesetzt: so wird auch der Traceback geschwaerzt
            record.exc_text = redact(_FORMATTER.formatException(record.exc_info))
        return True


_FORMATTER = logging.Formatter()


def install_redaction(*loggers: str) -> None:
    """Haengt den Filter an alle Handler des Root-Loggers und der genannten Logger (idempotent)."""
    for name in ("", *loggers):
        for handler in logging.getLogger(name).handlers:
            if not any(isinstance(f, RedactingFilter) for f in handler.filters):
                handler.addFilter(RedactingFilter())
