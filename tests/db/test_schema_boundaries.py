"""Jedes Schema gehoert genau einem Modul, Fremdschluessel bleiben in ihrem Schema (P1.7).

Die Schemas sind die spaeteren Services. Ein Fremdschluessel ueber eine Schema-Grenze
wuerde zwei Services an eine Datenbank ketten - zwischen Schemas wird per ID verwiesen.
Die Pruefung der Modelle braucht keine Datenbank, die der Migrationen schon.
"""

from __future__ import annotations

import importlib

import pytest
from sqlalchemy import Engine, text

from src.db.models import Base
from va_platform.db import APP_SCHEMAS

# Modul, das ein Schema besitzt -> Schema
OWNERS = {
    "src.db.models.batch": "batch",
    "va_market_data.adapters.postgres.models": "market_data",
    "va_scoring.adapters.postgres.models": "scoring",
    "va_notification.adapters.postgres.models": "reporting",
}


def _tables_of(module_name: str) -> set[str]:
    module = importlib.import_module(module_name)
    return {
        obj.__table__.fullname
        for obj in vars(module).values()
        if isinstance(obj, type) and hasattr(obj, "__table__") and obj.__module__ == module_name
    }


def test_every_schema_has_exactly_one_owner():
    assert sorted(OWNERS.values()) == sorted(APP_SCHEMAS)


@pytest.mark.parametrize(("module_name", "schema"), OWNERS.items())
def test_owner_defines_tables_only_in_its_schema(module_name, schema):
    tables = _tables_of(module_name)
    assert tables, f"{module_name} definiert keine Tabelle"
    assert {t.split(".")[0] for t in tables} == {schema}


def test_every_table_belongs_to_an_owner():
    owned = set().union(*(_tables_of(m) for m in OWNERS))
    assert set(Base.metadata.tables) == owned


def test_models_have_no_foreign_keys_across_schemas():
    crossing = [
        f"{table.fullname}.{fk.parent.name} -> {fk.target_fullname}"
        for table in Base.metadata.tables.values()
        for fk in table.foreign_keys
        if fk.column.table.schema != table.schema
    ]
    assert crossing == []


def test_migrated_database_has_no_foreign_keys_across_schemas(engine: Engine):
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT con.conname, src.nspname, dst.nspname
                FROM pg_constraint con
                JOIN pg_class src_t ON src_t.oid = con.conrelid
                JOIN pg_namespace src ON src.oid = src_t.relnamespace
                JOIN pg_class dst_t ON dst_t.oid = con.confrelid
                JOIN pg_namespace dst ON dst.oid = dst_t.relnamespace
                WHERE con.contype = 'f' AND src.nspname = ANY(:schemas)
                """
            ),
            {"schemas": list(APP_SCHEMAS)},
        ).all()
    assert rows, "keine Fremdschluessel gefunden - Abfrage pruefen"
    assert [r for r in rows if r[1] != r[2]] == []
