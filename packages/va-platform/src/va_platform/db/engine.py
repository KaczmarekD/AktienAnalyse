"""Engine- und Session-Erzeugung."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session


def normalize_url(url: str) -> str:
    """``postgresql://`` -> ``postgresql+psycopg://`` (sonst sucht SQLAlchemy psycopg2)."""
    for prefix in ("postgresql://", "postgres://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix) :]
    return url


def create_db_engine(url: str, *, read_only: bool = False) -> Engine:
    """``read_only``: Jede Transaktion ist schreibgeschuetzt (``default_transaction_read_only``),
    egal mit welcher Rolle. Fuer Werkzeuge, die nur lesen duerfen (Replay-Regression)."""
    connect_args = {"options": "-c default_transaction_read_only=on"} if read_only else {}
    return create_engine(normalize_url(url), pool_pre_ping=True, connect_args=connect_args)


@contextmanager
def session_scope(engine: Engine) -> Iterator[Session]:
    """Eine Transaktion: Commit bei Erfolg, Rollback bei Exception.

    ``expire_on_commit=False``, damit gelesene Objekte nach dem Commit nutzbar bleiben.
    """
    session = Session(engine, expire_on_commit=False)
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
