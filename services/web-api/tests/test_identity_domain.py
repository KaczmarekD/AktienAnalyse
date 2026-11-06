"""Fachregeln der Anmeldung (D1.1, docs/architecture/depot/nutzer.md): rein, ohne Datenbank.

Benutzernamen, Passwortregeln (NUT-05), Hash mit scrypt, Sitzungsfristen (NUT-01) und die
Sperre nach Fehlversuchen (NUT-06).
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

import pytest

from va_web_api.identity.domain import (
    MIN_PASSWORD_LENGTH,
    Failures,
    InvalidUsername,
    LockoutPolicy,
    PasswordHasher,
    SessionPolicy,
    new_session_token,
    normalize_username,
    password_problems,
    token_hash,
)

# Schnell fuer Tests; der Standard (N = 2**17) braucht 128 MiB je Hash
FAST = PasswordHasher(n=2**10)
T0 = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)


class TestUsername:
    def test_is_trimmed_and_lowercased(self):
        assert normalize_username("  Alice.B ") == "alice.b"

    @pytest.mark.parametrize("raw", ["ab", "a" * 33, "mit leer", "jürgen", "-start", "", "a;b"])
    def test_invalid_names_are_rejected(self, raw):
        with pytest.raises(InvalidUsername):
            normalize_username(raw)

    @pytest.mark.parametrize("raw", ["abc", "dennis", "d.k", "user_1", "a-b-c", "x" * 32])
    def test_valid_names(self, raw):
        assert normalize_username(raw) == raw


class TestPasswordRules:
    def test_a_long_unusual_password_passes(self):
        assert password_problems("Kiefer-Wolke-Rhein-42", username="dennis") == []

    def test_too_short(self):
        problems = password_problems("Kurz-1!", username="dennis")
        assert any(str(MIN_PASSWORD_LENGTH) in p for p in problems)

    @pytest.mark.parametrize("common", ["passwort1234", "Password1234", "123456789012"])
    def test_common_passwords_are_rejected(self, common):
        assert password_problems(common, username="dennis")

    def test_must_not_contain_the_username(self):
        assert password_problems("xx-Dennis-Sommer-xx", username="dennis")

    def test_one_repeated_character_is_rejected(self):
        assert password_problems("a" * 20, username="dennis")


class TestHasher:
    def test_format_carries_the_parameters(self):
        encoded = FAST.hash("Kiefer-Wolke-Rhein-42")
        algorithm, n, r, p, salt, digest = encoded.split("$")
        assert (algorithm, n, r, p) == ("scrypt", "1024", "8", "1")
        assert salt
        assert digest

    def test_verify(self):
        encoded = FAST.hash("Kiefer-Wolke-Rhein-42")
        assert FAST.verify("Kiefer-Wolke-Rhein-42", encoded)
        assert not FAST.verify("kiefer-wolke-rhein-42", encoded)

    def test_salt_differs_per_hash(self):
        assert FAST.hash("Kiefer-Wolke-Rhein-42") != FAST.hash("Kiefer-Wolke-Rhein-42")

    def test_verify_uses_the_parameters_of_the_hash(self):
        """Ein Hash mit anderen Parametern bleibt pruefbar, etwa nach einer Erhoehung von N."""
        older = PasswordHasher(n=2**9).hash("Kiefer-Wolke-Rhein-42")
        assert FAST.verify("Kiefer-Wolke-Rhein-42", older)
        assert FAST.needs_rehash(older)
        assert not FAST.needs_rehash(FAST.hash("x" * 12))

    @pytest.mark.parametrize("broken", ["", "scrypt$1$2", "bcrypt$x$y$z$a$b", "scrypt$a$b$c$d$e"])
    def test_broken_hashes_never_verify(self, broken):
        assert not FAST.verify("egal", broken)

    def test_default_cost_follows_owasp(self):
        default = PasswordHasher()
        assert (default.n, default.r, default.p) == (2**17, 8, 1)


class TestSessionToken:
    def test_has_256_bit(self):
        token = new_session_token()
        assert len(token) >= 43  # 32 Byte base64url
        assert token != new_session_token()

    def test_only_the_hash_is_stored(self):
        token = new_session_token()
        assert token_hash(token) == hashlib.sha256(token.encode()).hexdigest()


class TestSessionPolicy:
    policy = SessionPolicy(
        idle=timedelta(hours=12), absolute=timedelta(days=30), touch_every=timedelta(minutes=10)
    )

    def test_expires_after_the_absolute_lifetime(self):
        assert self.policy.expires_at(T0) == T0 + timedelta(days=30)

    def test_active_within_the_idle_time(self):
        assert self.policy.is_active(
            expires_at=T0 + timedelta(days=30),
            last_seen=T0,
            revoked=False,
            now=T0 + timedelta(hours=11, minutes=59),
        )

    def test_idle_too_long(self):
        assert not self.policy.is_active(
            expires_at=T0 + timedelta(days=30),
            last_seen=T0,
            revoked=False,
            now=T0 + timedelta(hours=12),
        )

    def test_absolute_end_even_when_active(self):
        now = T0 + timedelta(days=30)
        assert not self.policy.is_active(
            expires_at=T0 + timedelta(days=30), last_seen=now, revoked=False, now=now
        )

    def test_revoked(self):
        assert not self.policy.is_active(
            expires_at=T0 + timedelta(days=30), last_seen=T0, revoked=True, now=T0
        )

    def test_touch_at_most_every_ten_minutes(self):
        assert not self.policy.needs_touch(T0, T0 + timedelta(minutes=9))
        assert self.policy.needs_touch(T0, T0 + timedelta(minutes=10))


class TestLockout:
    policy = LockoutPolicy(max_failures=5, window=timedelta(minutes=15))

    def test_four_failures_are_allowed(self):
        assert not self.policy.is_locked(Failures(by_user=4, by_ip=4))

    @pytest.mark.parametrize(("by_user", "by_ip"), [(5, 0), (0, 5), (7, 9)])
    def test_five_failures_lock(self, by_user, by_ip):
        assert self.policy.is_locked(Failures(by_user=by_user, by_ip=by_ip))

    def test_window_start(self):
        assert self.policy.since(T0) == T0 - timedelta(minutes=15)
