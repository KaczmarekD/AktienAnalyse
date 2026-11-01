"""``python -m src.db.migrate`` legt Login-Rollen an, die in einer bestehenden Datenbank fehlen.

Rollen gelten fuer den ganzen Postgres-Cluster. Der Test arbeitet deshalb mit einer eigenen,
einmaligen Rolle statt mit va_profiles, die die Test-Vorlage schon hat.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError

from src.db.migrate import ensure_login_role
from tests.db.conftest import _admin, _url_for
from va_platform.db import normalize_url


@pytest.fixture
def role() -> Iterator[str]:
    name = f"va_mig_{uuid.uuid4().hex[:8]}"
    yield name
    with _admin().connect() as conn:
        conn.execute(text(f"DROP ROLE IF EXISTS {name}"))


def _can_login(db_url: str, role: str, password: str) -> bool:
    database = make_url(db_url).database
    assert database
    engine = create_engine(normalize_url(_url_for(database, role, password)))
    try:
        with engine.connect() as conn:
            return conn.execute(text("SELECT current_user")).scalar_one() == role
    except OperationalError:
        return False
    finally:
        engine.dispose()


def test_creates_a_missing_role_with_login(db_url, role):
    ensure_login_role(db_url, role, "erstes-pw")
    assert _can_login(db_url, role, "erstes-pw")


def test_an_existing_role_gets_the_password_from_the_env(db_url, role):
    ensure_login_role(db_url, role, "erstes-pw")
    ensure_login_role(db_url, role, "neues-pw")
    assert _can_login(db_url, role, "neues-pw")
    assert not _can_login(db_url, role, "erstes-pw")


def test_quotes_in_the_password_stay_harmless(db_url, role):
    ensure_login_role(db_url, role, "a'b; DROP TABLE x; --")
    assert _can_login(db_url, role, "a'b; DROP TABLE x; --")
