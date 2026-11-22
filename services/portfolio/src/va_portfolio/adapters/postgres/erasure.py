"""Loeschen der Depots einer Person (D3.1, ADR-0012, docs/architecture/depot/nutzer.md).

Depots werden sonst nur archiviert. Auf ausdruecklichen Wunsch einer Person loescht
``erase_user`` alle ihre Zeilen im Schema ``portfolio``, die Outbox eingeschlossen (dort steht
``owner_user_id``). Die Inbox enthaelt nur Event-IDs und bleibt.

Wie in ``identity`` (D1.6): mit der Rolle des Besitzers (``DATABASE_OWNER_URL``), die Trigger
gegen DELETE nur in dieser Transaktion aus, zuerst alle Tabellen sperren, dann loeschen.
Aufgerufen von ``python -m src.erase_user``, zusammen mit dem Konto in ``identity``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import text

from .models import SCHEMA

if TYPE_CHECKING:
    from sqlalchemy import Engine

TRIGGER = "va_no_delete"  # aus va_platform.db.ddl.protect_table

_DEPOTS = "SELECT id FROM portfolio.depot WHERE owner_user_id = :id"
_SNAPSHOTS = f"SELECT id FROM portfolio.holding_snapshot WHERE depot_id IN ({_DEPOTS})"

# Abhaengige vor denen, auf die sie verweisen
PER_USER: tuple[tuple[str, str], ...] = (
    ("holding_line", f"snapshot_id IN ({_SNAPSHOTS})"),
    ("cash_line", f"snapshot_id IN ({_SNAPSHOTS})"),
    ("holding_snapshot", f"depot_id IN ({_DEPOTS})"),
    ("depot_version", f"depot_id IN ({_DEPOTS})"),
    ("depot_status", f"depot_id IN ({_DEPOTS})"),
    ("outbox", "payload -> 'data' ->> 'owner_user_id' = CAST(:id AS text)"),
    ("depot", "owner_user_id = :id"),
)


def erase_user(engine: Engine, user_id: int) -> dict[str, int]:
    """Loescht alle Zeilen der Person ``user_id`` in ``portfolio``; gibt die Zahl je Tabelle.

    ``engine`` verbindet sich als Besitzer der Tabellen, mit einer anderen Rolle scheitert schon
    das Abschalten der Trigger. Eine Person ohne Depot ergibt lauter Nullen.
    """
    with engine.begin() as conn:
        tables = [table for table, _ in PER_USER]
        for table in tables:
            conn.execute(text(f"ALTER TABLE {SCHEMA}.{table} DISABLE TRIGGER {TRIGGER}"))
        rows: dict[str, int] = {}
        for table, where in PER_USER:
            result = conn.execute(
                text(f"DELETE FROM {SCHEMA}.{table} WHERE {where}"), {"id": user_id}
            )
            rows[f"{SCHEMA}.{table}"] = result.rowcount
        for table in tables:
            conn.execute(text(f"ALTER TABLE {SCHEMA}.{table} ENABLE TRIGGER {TRIGGER}"))
    return rows
