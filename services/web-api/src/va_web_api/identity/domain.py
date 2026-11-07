"""Fachregeln der Anmeldung (D1.1, docs/architecture/depot/nutzer.md): rein, ohne Ein-/Ausgabe.

- Benutzernamen: klein geschrieben, 3 bis 32 Zeichen aus a-z, 0-9, ``.``, ``_`` und ``-``.
- Passwoerter (NUT-05): mindestens 12 Zeichen, nicht in der Liste haeufiger Passwoerter, ohne den
  Benutzernamen. Gespeichert wird nur ein scrypt-Hash (Standardbibliothek, keine native
  Abhaengigkeit fuer den J4125). Die Parameter stehen im Hash, ein spaeterer Wechsel bleibt moeglich.
- Sitzungen (NUT-01): zufaellige ID mit 256 Bit im Cookie, in der Datenbank nur ihr SHA-256.
  Ablauf nach 12 h ohne Aktivitaet, spaetestens nach 30 Tagen.
- Sperre (NUT-06): ab 5 Fehlversuchen je Konto oder je IP-Adresse, 15 Minuten.
- Mail-Adresse (NUT-10, D1.6): eine neue gilt erst nach dem Link aus der Mail, der 24 h
  gilt; gespeichert ist nur der SHA-256 seines Tokens.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta

ROLES = ("admin", "user")
STATUSES = ("active", "disabled")
# Gruende in login_event; nur die ersten beiden zaehlen fuer die Sperre
FAILURE_REASONS = ("wrong_password", "unknown_user")
LOGIN_REASONS = ("ok", *FAILURE_REASONS, "locked", "disabled")
REVOKE_REASONS = ("logout", "admin", "password_changed", "disabled")

USERNAME_PATTERN = re.compile(r"[a-z0-9][a-z0-9._-]{2,31}")
# Bewusst schlicht: genau ein @, davor etwas, dahinter eine Domain mit Punkt, kein
# Leerzeichen und keine Steuerzeichen (die Adresse landet im Kopf einer Mail)
_EMAIL_PART = r"[^@\s\x00-\x1f\x7f]+"
EMAIL_PATTERN = re.compile(rf"{_EMAIL_PART}@{_EMAIL_PART}\.{_EMAIL_PART}")
EMAIL_MAX_LENGTH = 254
EMAIL_CONFIRMATION_VALIDITY = timedelta(hours=24)
# Gegen Mails in Serie an fremde Adressen ueber das SMTP-Konto der NAS (Gmail: ~500 am Tag)
EMAIL_CONFIRMATION_LIMIT = 5
EMAIL_CONFIRMATION_WINDOW = timedelta(hours=1)
MIN_PASSWORD_LENGTH = 12

# Bewusst klein: Kurze Passwoerter scheitern schon an der Laenge. Die Liste faengt die haeufigsten
# Muster ab 12 Zeichen ab; erweitern, wenn noetig.
COMMON_PASSWORDS = frozenset(
    {
        "123456789012",
        "1234567890123",
        "12345678901234",
        "123123123123",
        "111111111111",
        "000000000000",
        "qwertzuiop12",
        "qwertyuiop12",
        "qwertzuiopü1",
        "asdfghjkl123",
        "password1234",
        "password12345",
        "passwort1234",
        "passwort12345",
        "passwordpassword",
        "passwortpasswort",
        "iloveyou1234",
        "letmein12345",
        "welcome12345",
        "willkommen12",
        "willkommen123",
        "geheimgeheim",
        "hallohallo12",
        "sommer2026!!",
        "winter2026!!",
        "administrator",
        "administrator1",
        "changeme1234",
        "bitteaendern",
        "bitte-aendern",
        "dkbbanking12",
        "aktienanalyse",
    }
)


class InvalidUsername(ValueError):
    pass


def normalize_username(raw: str) -> str:
    """Klein geschrieben und ohne Rand; wirft ``InvalidUsername`` bei unzulaessigen Zeichen."""
    name = raw.strip().lower()
    if not USERNAME_PATTERN.fullmatch(name):
        msg = (
            "Benutzername: 3 bis 32 Zeichen aus a-z, 0-9, Punkt, Unterstrich und Bindestrich, "
            "beginnend mit Buchstabe oder Ziffer"
        )
        raise InvalidUsername(msg)
    return name


def valid_email(email: str) -> bool:
    return len(email) <= EMAIL_MAX_LENGTH and EMAIL_PATTERN.fullmatch(email) is not None


def password_problems(password: str, username: str | None = None) -> list[str]:
    """Was gegen ein Passwort spricht; leer, wenn es die Regeln erfuellt."""
    problems: list[str] = []
    if len(password) < MIN_PASSWORD_LENGTH:
        problems.append(f"mindestens {MIN_PASSWORD_LENGTH} Zeichen")
    if password.lower() in COMMON_PASSWORDS:
        problems.append("steht in der Liste haeufiger Passwoerter")
    if len(set(password)) == 1:
        problems.append("besteht aus einem einzigen Zeichen")
    if username and username.lower() in password.lower():
        problems.append("enthaelt den Benutzernamen")
    return problems


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


@dataclass(frozen=True)
class PasswordHasher:
    """scrypt nach OWASP (N = 2**17, r = 8, p = 1, also 128 MiB je Hash).

    Format: ``scrypt$<n>$<r>$<p>$<salt>$<hash>``, Salt und Hash base64url ohne Fuellzeichen.
    ``verify`` nimmt die Parameter aus dem Hash, nicht aus der Instanz.
    """

    n: int = 2**17
    r: int = 8
    p: int = 1
    dklen: int = 32
    salt_bytes: int = 16

    @staticmethod
    def _derive(password: str, salt: bytes, n: int, r: int, p: int, dklen: int) -> bytes:
        # OpenSSL begrenzt den Speicher sonst auf 32 MiB; 128 * r * n Byte plus Reserve
        maxmem = 128 * r * (n + p + 2) + 1024 * 1024
        return hashlib.scrypt(
            password.encode("utf-8"), salt=salt, n=n, r=r, p=p, maxmem=maxmem, dklen=dklen
        )

    def hash(self, password: str) -> str:
        salt = secrets.token_bytes(self.salt_bytes)
        digest = self._derive(password, salt, self.n, self.r, self.p, self.dklen)
        return f"scrypt${self.n}${self.r}${self.p}${_b64(salt)}${_b64(digest)}"

    def verify(self, password: str, encoded: str) -> bool:
        parsed = _parse(encoded)
        if parsed is None:
            return False
        n, r, p, salt, expected = parsed
        try:
            digest = self._derive(password, salt, n, r, p, len(expected))
        except ValueError, MemoryError:
            return False
        return hmac.compare_digest(digest, expected)

    def needs_rehash(self, encoded: str) -> bool:
        parsed = _parse(encoded)
        return parsed is None or parsed[:3] != (self.n, self.r, self.p)


def _parse(encoded: str) -> tuple[int, int, int, bytes, bytes] | None:
    parts = encoded.split("$")
    if len(parts) != 6 or parts[0] != "scrypt":
        return None
    try:
        n, r, p = int(parts[1]), int(parts[2]), int(parts[3])
        salt, digest = _unb64(parts[4]), _unb64(parts[5])
    except ValueError, binascii.Error:
        return None
    # n muss eine Zweierpotenz sein; Obergrenze gegen Hashes, die den Speicher sprengen
    if n < 2 or n & (n - 1) or n > 2**20 or not 1 <= r <= 32 or not 1 <= p <= 16:
        return None
    if not salt or not digest:
        return None
    return n, r, p, salt, digest


def new_session_token() -> str:
    """Zufaellige Sitzungs-ID mit 256 Bit; nur sie steht im Cookie."""
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    """Was die Datenbank von der Sitzungs-ID speichert."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class SessionPolicy:
    idle: timedelta = timedelta(hours=12)
    absolute: timedelta = timedelta(days=30)
    touch_every: timedelta = timedelta(minutes=10)

    def expires_at(self, created: datetime) -> datetime:
        return created + self.absolute

    def is_active(
        self, *, expires_at: datetime, last_seen: datetime, revoked: bool, now: datetime
    ) -> bool:
        return not revoked and now < expires_at and now - last_seen < self.idle

    def needs_touch(self, last_seen: datetime, now: datetime) -> bool:
        return now - last_seen >= self.touch_every


@dataclass(frozen=True)
class Failures:
    """Fehlversuche je Konto (seit seinem letzten Erfolg) und je IP (seit dem letzten Erfolg dort)."""

    by_user: int
    by_ip: int


@dataclass(frozen=True)
class LockoutPolicy:
    max_failures: int = 5
    window: timedelta = timedelta(minutes=15)

    def since(self, now: datetime) -> datetime:
        return now - self.window

    def is_locked(self, failures: Failures) -> bool:
        return max(failures.by_user, failures.by_ip) >= self.max_failures
