"""Die Fehlermail: Betreff und HTML-Text mit dem Traceback (vorher in ``src/main.py``)."""

from __future__ import annotations

import html

ERROR_SUBJECT = "FEHLER beim Batch-Run"


def error_mail_html(trace: str) -> str:
    """Der Traceback wird escaped - er kann Text aus Fremddaten enthalten."""
    return f"<h2>Fehler im woechentlichen Batch-Run</h2><pre>{html.escape(trace)}</pre>"
