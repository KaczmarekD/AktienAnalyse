"""``python -m va_web_api.admin create-user`` (D1.1, NUT-04): der erste Admin ohne Standardpasswort.

Das Kommando laeuft im Container des web-api mit ``WEB_API_IDENTITY_DATABASE_URL`` (Rolle
``va_identity``). Hier gegen die Test-Datenbank, das Passwort kommt per ``--password-stdin``.
"""

from __future__ import annotations

import io

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url

from tests.db.conftest import ROLE_PASSWORDS, _url_for
from va_web_api import admin

PASSWORD = "Kiefer-Wolke-Rhein-42"


@pytest.fixture
def identity_url(db_url, monkeypatch) -> str:
    database = make_url(db_url).database
    assert database
    url = _url_for(database, "va_identity", ROLE_PASSWORDS["va_identity"])
    monkeypatch.setenv("WEB_API_DATABASE_URL", "postgresql+psycopg://x:x@127.0.0.1:1/none")
    monkeypatch.setenv("WEB_API_IDENTITY_DATABASE_URL", url)
    return url


def _run(*argv: str, stdin: str = PASSWORD + "\n") -> int:
    return admin.main(list(argv), stdin=io.StringIO(stdin))


def _roles(engine) -> dict[str, str]:
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT username, role FROM identity.user_account")).all()
    return {str(name): str(role) for name, role in rows}


def test_creates_the_first_admin(identity_url, engine, capsys):
    assert _run("create-user", "Dennis", "--admin", "--password-stdin") == 0
    assert _roles(engine) == {"dennis": "admin"}
    out = capsys.readouterr().out
    assert "dennis" in out
    assert PASSWORD not in out


def test_without_admin_flag_a_normal_user(identity_url, engine):
    assert _run("create-user", "anna", "--password-stdin", "--email", "anna@example.com") == 0
    assert _roles(engine) == {"anna": "user"}


def test_stores_only_the_hash(identity_url, engine):
    _run("create-user", "dennis", "--admin", "--password-stdin")
    with engine.connect() as conn:
        stored = conn.execute(text("SELECT hash FROM identity.password_credential")).scalar_one()
    assert stored.startswith("scrypt$")
    assert PASSWORD not in stored


def test_a_weak_password_creates_nobody(identity_url, engine, capsys):
    assert _run("create-user", "dennis", "--admin", "--password-stdin", stdin="kurz\n") == 1
    assert _roles(engine) == {}
    assert "12" in capsys.readouterr().err


def test_an_existing_name_is_an_error(identity_url, engine, capsys):
    assert _run("create-user", "dennis", "--admin", "--password-stdin") == 0
    assert _run("create-user", "Dennis", "--password-stdin") == 1
    assert "gibt es schon" in capsys.readouterr().err


def test_without_any_settings_no_traceback(monkeypatch, capsys):
    monkeypatch.delenv("WEB_API_DATABASE_URL", raising=False)
    monkeypatch.delenv("WEB_API_IDENTITY_DATABASE_URL", raising=False)
    assert _run("create-user", "dennis", "--password-stdin") == 2
    assert "WEB_API_IDENTITY_DATABASE_URL" in capsys.readouterr().err


def test_without_identity_database(monkeypatch, capsys):
    monkeypatch.setenv("WEB_API_DATABASE_URL", "postgresql+psycopg://x:x@127.0.0.1:1/none")
    monkeypatch.delenv("WEB_API_IDENTITY_DATABASE_URL", raising=False)
    assert _run("create-user", "dennis", "--password-stdin") == 2
    assert "WEB_API_IDENTITY_DATABASE_URL" in capsys.readouterr().err
