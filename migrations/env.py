"""Alembic-Umgebung.

URL-Quelle (in dieser Reihenfolge): ``config.attributes["url"]`` (von
``src.db.migrate``), ``DATABASE_OWNER_URL``, ``DATABASE_URL``.
Neue Migration:  DATABASE_OWNER_URL=... alembic revision --autogenerate -m "..."
"""

from __future__ import annotations

import os

from alembic import context
from sqlalchemy import create_engine, pool

from src.db.engine import normalize_url
from src.db.models import APP_SCHEMAS, Base

config = context.config


def _url() -> str:
    url = (
        config.attributes.get("url")
        or os.environ.get("DATABASE_OWNER_URL")
        or os.environ.get("DATABASE_URL")
    )
    if not url:
        msg = "Keine Datenbank-URL: DATABASE_OWNER_URL oder DATABASE_URL setzen"
        raise RuntimeError(msg)
    return normalize_url(url)


def _include_name(name: str | None, type_: str, _parent_names: object) -> bool:
    if type_ == "schema":
        return name in APP_SCHEMAS
    return True


def run_migrations_online() -> None:
    engine = create_engine(_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=Base.metadata,
            include_schemas=True,
            include_name=_include_name,
            version_table_schema="public",
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    msg = "Offline-Migrationen werden nicht unterstuetzt"
    raise RuntimeError(msg)
run_migrations_online()
