"""Depots zwischen portfolio und web-api (D3.1, docs/architecture/depot/depots.md).

Ein Depot gehoert einem Nutzer. Sein Bestand ist eine Folge vollstaendiger Depotstaende mit
fortlaufender Version; jede Aenderung ergibt einen neuen. Mengen und Betraege sind ``Decimal``
und stehen im JSON als Zahl im String, nie als ``float``. Diese Modelle reisen nur per
Request/Reply (``rpc.va.portfolio.*``), nicht in ``VA_EVENTS``: Dort stehen keine Mengen.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import Field

from .base import Contract, PositiveId
from .securities import IsinStr

DepotKind = Literal["depot", "watchlist"]  # Beobachtungsliste: ohne Mengen und Kasse
DepotState = Literal["active", "archived"]
HoldingUnit = Literal["pieces", "nominal"]  # Stueck; bei Anleihen der Nennwert
SnapshotSource = Literal["manual", "import", "bank"]

MAX_NAME = 100
MAX_TEXT = 500
MAX_LINES = 1000

# Bis 10^12 mit hoechstens 8 Nachkommastellen (Bruchstuecke aus Sparplaenen)
Quantity = Annotated[Decimal, Field(gt=0, max_digits=20, decimal_places=8)]
Amount = Annotated[Decimal, Field(max_digits=20, decimal_places=8)]
DepotName = Annotated[str, Field(min_length=1, max_length=MAX_NAME)]
Text = Annotated[str, Field(max_length=MAX_TEXT)]


class DepotV1(Contract):
    """Ein Depot mit dem Stand seines Bestands; ``version`` 0 heisst: noch nichts erfasst."""

    id: PositiveId
    kind: DepotKind
    name: str
    description: str | None = None
    status: DepotState
    created_at: datetime
    version: int = Field(ge=0)
    positions: int = Field(ge=0)


class HoldingLineV1(Contract):
    """Eine Position. In einer Beobachtungsliste ohne Menge und Einstand."""

    isin: IsinStr
    quantity: Quantity | None = None
    unit: HoldingUnit = "pieces"
    cost_basis_eur: Annotated[Amount, Field(ge=0)] | None = None  # Einstandswert gesamt
    note: Text | None = None


class CashLineV1(Contract):
    """Guthaben auf dem Verrechnungskonto; vorerst nur EUR (DEP-04)."""

    currency: Literal["EUR"] = "EUR"
    amount: Amount


class HoldingsV1(Contract):
    """Ein Depotstand. ``version`` 0 ist der leere Stand vor der ersten Speicherung."""

    depot_id: PositiveId
    version: int = Field(ge=0)
    source: SnapshotSource | None = None
    created_at: datetime | None = None
    created_by: PositiveId | None = None
    lines: list[HoldingLineV1] = Field(default_factory=list)
    cash: list[CashLineV1] = Field(default_factory=list)


class HistoryEntryV1(Contract):
    """Ein Depotstand im Verlauf, mit dem Unterschied zum vorherigen (nach ISIN)."""

    version: int = Field(ge=1)
    source: SnapshotSource
    created_at: datetime
    created_by: PositiveId | None = None
    positions: int = Field(ge=0)
    added: int = Field(ge=0)
    changed: int = Field(ge=0)
    removed: int = Field(ge=0)


__all__ = [
    "MAX_LINES",
    "MAX_NAME",
    "MAX_TEXT",
    "CashLineV1",
    "DepotKind",
    "DepotName",
    "DepotState",
    "DepotV1",
    "HistoryEntryV1",
    "HoldingLineV1",
    "HoldingUnit",
    "HoldingsV1",
    "SnapshotSource",
    "Text",
]
