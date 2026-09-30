"""Fixtures fuer DB-Tests gegen ein echtes PostgreSQL.

``TEST_DATABASE_URL`` muss auf eine Rolle mit CREATEDB/CREATEROLE zeigen
(z.B. ``postgresql+psycopg://postgres:test@localhost:55432/postgres``).
Ohne die Variable werden alle DB-Tests uebersprungen.

Weil die Tabellen DELETE/TRUNCATE verbieten, bekommt jeder Test eine eigene,
frische Datenbank - kopiert aus einer einmal migrierten Template-DB.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from src.db.engine import create_db_engine, normalize_url
from src.db.migrate import upgrade

ADMIN_URL = os.environ.get("TEST_DATABASE_URL")
ROLE_PASSWORDS = {"va_app": "va_app_test", "va_read": "va_read_test"}


def _admin() -> Engine:
    assert ADMIN_URL
    return create_engine(normalize_url(ADMIN_URL), isolation_level="AUTOCOMMIT")


def _url_for(database: str, user: str | None = None, password: str | None = None) -> str:
    assert ADMIN_URL
    url = make_url(normalize_url(ADMIN_URL)).set(database=database)
    if user:
        url = url.set(username=user, password=password)
    return url.render_as_string(hide_password=False)


@pytest.fixture(scope="session")
def db_template() -> Iterator[str]:
    if not ADMIN_URL:
        pytest.skip("TEST_DATABASE_URL nicht gesetzt - DB-Tests uebersprungen")
    admin = _admin()
    name = f"va_tmpl_{uuid.uuid4().hex[:8]}"
    with admin.connect() as conn:
        for role, password in ROLE_PASSWORDS.items():
            exists = conn.execute(
                text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": role}
            ).scalar()
            verb = "ALTER" if exists else "CREATE"
            conn.execute(text(f"{verb} ROLE {role} WITH LOGIN PASSWORD '{password}'"))
        conn.execute(text(f'CREATE DATABASE "{name}"'))
    upgrade(_url_for(name))
    yield name
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
    admin.dispose()


@pytest.fixture
def db_url(db_template: str) -> Iterator[str]:
    admin = _admin()
    name = f"va_test_{uuid.uuid4().hex[:8]}"
    with admin.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{name}" TEMPLATE "{db_template}"'))
    yield _url_for(name)
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
    admin.dispose()


@pytest.fixture
def engine(db_url: str) -> Iterator[Engine]:
    eng = create_db_engine(db_url)
    yield eng
    eng.dispose()


@pytest.fixture
def session(engine: Engine) -> Iterator[Session]:
    with Session(engine, expire_on_commit=False) as s:
        yield s


def _role_engine(db_url: str, role: str) -> Engine:
    database = make_url(db_url).database
    assert database
    return create_db_engine(_url_for(database, role, ROLE_PASSWORDS[role]))


@pytest.fixture
def app_engine(db_url: str) -> Iterator[Engine]:
    eng = _role_engine(db_url, "va_app")
    yield eng
    eng.dispose()


@pytest.fixture
def read_engine(db_url: str) -> Iterator[Engine]:
    eng = _role_engine(db_url, "va_read")
    yield eng
    eng.dispose()
