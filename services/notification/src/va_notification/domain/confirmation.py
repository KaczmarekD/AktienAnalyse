"""Die Bestaetigungsmail fuer eine neue Mail-Adresse (D1.6, NUT-10): Betreff, HTML und Klartext.

Der Link kommt vom web-api und enthaelt das Token. Im HTML ist er escaped, im Klartext steht er
unveraendert, damit ihn jeder Mail-Client anklickbar macht.
"""

from __future__ import annotations

import html
from dataclasses import dataclass
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

if TYPE_CHECKING:
    from datetime import datetime

CONFIRMATION_SUBJECT = "Mail-Adresse bestätigen"
LOCAL_TIME = ZoneInfo("Europe/Berlin")


@dataclass(frozen=True)
class ConfirmationMail:
    subject: str
    html: str
    text: str


def confirmation_mail(link: str, expires_at: datetime) -> ConfirmationMail:
    until = expires_at.astimezone(LOCAL_TIME).strftime("%d.%m.%Y, %H:%M Uhr")
    safe = html.escape(link, quote=True)
    body = (
        "<p>Für dein Konto im Value-Analyzer wurde diese Mail-Adresse eingetragen.</p>"
        f'<p><a href="{safe}">Mail-Adresse bestätigen</a></p>'
        f"<p>Der Link gilt bis {until} und nur einmal. Falls der Knopf nicht geht, die Adresse "
        f"in den Browser kopieren:<br>{safe}</p>"
        "<p>Warst du das nicht? Dann diese Mail einfach löschen, es ändert sich nichts.</p>"
    )
    text = (
        "Für dein Konto im Value-Analyzer wurde diese Mail-Adresse eingetragen.\n\n"
        f"Bestätigen: {link}\n\n"
        f"Der Link gilt bis {until} und nur einmal.\n"
        "Warst du das nicht? Dann diese Mail einfach löschen, es ändert sich nichts.\n"
    )
    return ConfirmationMail(CONFIRMATION_SUBJECT, body, text)
