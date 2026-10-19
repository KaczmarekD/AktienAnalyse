"""Deklarative Basis mit einheitlichen Typen und Constraint-Namen."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import BigInteger, Date, DateTime, Double, MetaData, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase

APP_SCHEMAS = ("batch", "market_data", "scoring", "reporting")

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    type_annotation_map = {  # noqa: RUF012 - SQLAlchemy-Konvention
        str: Text(),
        int: BigInteger(),
        float: Double(),
        datetime: DateTime(timezone=True),
        date: Date(),
        dict[str, Any]: JSONB(),
    }


def in_values(column: str, values: tuple[str, ...]) -> str:
    """SQL fuer einen CHECK-Constraint ``column IN (...)``."""
    return f"{column} IN ({', '.join(repr(v) for v in values)})"
