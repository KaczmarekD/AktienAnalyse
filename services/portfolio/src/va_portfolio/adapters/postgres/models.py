"""Schema ``portfolio`` (D3.1): Depots und Depotstaende, persoenliche Daten.

Alles nur zum Anfuegen (Migration 0023, ``protect_table``). Gueltig ist je Depot die juengste
Zeile in ``depot_version`` (Name) und ``depot_status``, der neueste Depotstand ist der mit der
hoechsten Version. Fremdschluessel nur im Schema; ``owner_user_id`` verweist per ID auf
``identity.user_account``. Mengen und Betraege als ``numeric``.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import get_args

from sqlalchemy import CheckConstraint, ForeignKey, Identity, Index, Numeric, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from va_contracts.portfolio import DepotKind, DepotState, HoldingUnit, SnapshotSource
from va_platform.db import Base, in_values
from va_platform.messaging import InboxMixin, OutboxMixin, outbox_table_args

SCHEMA = "portfolio"
KINDS: tuple[str, ...] = get_args(DepotKind)
STATES: tuple[str, ...] = get_args(DepotState)
UNITS: tuple[str, ...] = get_args(HoldingUnit)
SOURCES: tuple[str, ...] = get_args(SnapshotSource)


class Depot(Base):
    __tablename__ = "depot"
    __table_args__ = (
        CheckConstraint(in_values("kind", KINDS), name="kind"),
        Index("ix_depot_owner_user_id", "owner_user_id"),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(Identity(always=True), primary_key=True)
    owner_user_id: Mapped[int]
    kind: Mapped[str]
    created_at: Mapped[datetime]


class DepotVersion(Base):
    """Name und Beschreibung; gueltig ist die juengste Zeile."""

    __tablename__ = "depot_version"
    __table_args__ = (Index("ix_depot_version_depot_id", "depot_id"), {"schema": SCHEMA})

    id: Mapped[int] = mapped_column(Identity(always=True), primary_key=True)
    depot_id: Mapped[int] = mapped_column(ForeignKey(f"{SCHEMA}.depot.id"))
    name: Mapped[str]
    description: Mapped[str | None]
    created_at: Mapped[datetime]


class DepotStatus(Base):
    """Aktiv oder archiviert (DEP-06); gueltig ist die juengste Zeile."""

    __tablename__ = "depot_status"
    __table_args__ = (
        CheckConstraint(in_values("status", STATES), name="status"),
        Index("ix_depot_status_depot_id", "depot_id"),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(Identity(always=True), primary_key=True)
    depot_id: Mapped[int] = mapped_column(ForeignKey(f"{SCHEMA}.depot.id"))
    status: Mapped[str]
    at: Mapped[datetime]


class HoldingSnapshot(Base):
    """Ein Depotstand; ``version`` fortlaufend je Depot. Die Eindeutigkeit erkennt zwei
    gleichzeitige Speicherungen auf dieselbe Basis."""

    __tablename__ = "holding_snapshot"
    __table_args__ = (
        UniqueConstraint("depot_id", "version", name="uq_holding_snapshot_depot_id_version"),
        CheckConstraint(in_values("source", SOURCES), name="source"),
        CheckConstraint("version >= 1", name="version"),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(Identity(always=True), primary_key=True)
    depot_id: Mapped[int] = mapped_column(ForeignKey(f"{SCHEMA}.depot.id"))
    version: Mapped[int]
    source: Mapped[str]
    source_ref: Mapped[str | None]  # Datei-Hash oder Abruf der Bank (ab D3.5/D8)
    as_of: Mapped[datetime | None]  # Stand laut Herkunft, etwa der Bank
    created_by: Mapped[int | None]  # Nutzer; leer bei einem Abruf der Bank
    created_at: Mapped[datetime]


class HoldingLine(Base):
    __tablename__ = "holding_line"
    __table_args__ = (
        UniqueConstraint("snapshot_id", "isin", name="uq_holding_line_snapshot_id_isin"),
        CheckConstraint(in_values("unit", UNITS), name="unit"),
        CheckConstraint("quantity IS NULL OR quantity > 0", name="quantity"),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(Identity(always=True), primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey(f"{SCHEMA}.holding_snapshot.id"))
    position: Mapped[int]  # Reihenfolge der Eingabe
    isin: Mapped[str]
    quantity: Mapped[Decimal | None] = mapped_column(Numeric)
    unit: Mapped[str]
    cost_basis_eur: Mapped[Decimal | None] = mapped_column(Numeric)
    note: Mapped[str | None]


class CashLine(Base):
    __tablename__ = "cash_line"
    __table_args__ = {"schema": SCHEMA}  # noqa: RUF012

    id: Mapped[int] = mapped_column(Identity(always=True), primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey(f"{SCHEMA}.holding_snapshot.id"))
    currency: Mapped[str]
    amount: Mapped[Decimal] = mapped_column(Numeric)


class PortfolioOutbox(OutboxMixin, Base):
    """Events von portfolio, bis sie veroeffentlicht sind."""

    __table_args__ = outbox_table_args(SCHEMA)


class PortfolioInbox(InboxMixin, Base):
    """Events, die portfolio verarbeitet hat, je Consumer einmal."""

    __table_args__ = {"schema": SCHEMA}  # noqa: RUF012
