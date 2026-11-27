"""Depots zwischen portfolio und web-api (D3.1, docs/architecture/depot/depots.md).

Ein Depot gehoert einem Nutzer. Sein Bestand ist eine Folge vollstaendiger Depotstaende mit
fortlaufender Version; jede Aenderung ergibt einen neuen. Mengen und Betraege sind ``Decimal``
und stehen im JSON als Zahl im String, nie als ``float``. Diese Modelle reisen nur per
Request/Reply (``rpc.va.portfolio.*``), nicht in ``VA_EVENTS``: Dort stehen keine Mengen.

Seit D3.4 traegt ``DepotV1`` seine Bewertung (``DepotValuationV1``): Wert in EUR aus den
letzten Kursen, Einstand und Differenz, bei ``depots.get`` dazu jede Position. Seit D4.2 traegt
jede Aktie ihre Scores aus dem juengsten Bewertungslauf (``PositionScoreV1``).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import Field

from .base import Contract, PositiveId
from .securities import AssetClass, IsinStr

DepotKind = Literal["depot", "watchlist"]  # Beobachtungsliste: ohne Mengen und Kasse
DepotState = Literal["active", "archived"]
HoldingUnit = Literal["pieces", "nominal"]  # Stueck; bei Anleihen der Nennwert
SnapshotSource = Literal["manual", "import", "bank"]
# D3.4: Warum eine Position mit Menge keinen Wert hat: kein Kurs, kein Waehrungskurs, oder der
# Kurs passt nicht zur Einheit (Prozent vom Nennwert je Stueck)
ValueMissing = Literal["price", "fx", "unit"]
# D3.5: Abgleich einer Datei mit dem aktuellen Depotstand, je ISIN
ImportStatus = Literal["new", "changed", "unchanged", "removed"]
# D4.2: Woher die Scores einer Aktie kommen: aus dem Ranking (DAX/MDAX), eingeordnet als
# Universumstitel unter dem Groessenfilter oder eingeordnet von ausserhalb (D4.1)
ScoreReference = Literal["universe", "below_size_filter", "outside"]
# Wie ``PlacementReason`` und ``ValueTrapReason`` der Events (ein Test haelt sie gleich)
ScoreReason = Literal["no_value", "no_quality", "no_data"]
TrapReason = Literal["quality", "momentum"]

MAX_NAME = 100
MAX_TEXT = 500
MAX_LINES = 1000
# D3.5: Datei im eigenen Format; Base64 im JSON bleibt unter 1 MB (nginx, NATS max_payload)
MAX_FILE_BYTES = 640 * 1024

# Bis 10^12 mit hoechstens 8 Nachkommastellen (Bruchstuecke aus Sparplaenen)
Quantity = Annotated[Decimal, Field(gt=0, max_digits=20, decimal_places=8)]
Amount = Annotated[Decimal, Field(max_digits=20, decimal_places=8)]
DepotName = Annotated[str, Field(min_length=1, max_length=MAX_NAME)]
Text = Annotated[str, Field(max_length=MAX_TEXT)]


class PositionScoreV1(Contract):
    """Scores einer Aktie im Depot (D4.2, ANA-01): aus dem juengsten Bewertungslauf, der sie kennt.

    ``reference``: ``universe`` heisst Titel des Rankings, mit denselben Werten wie dort und dem
    Rang (``rank``). Sonst ist sie eingeordnet ins Referenzuniversum (D4.1): als Universumstitel
    unter dem Groessenfilter oder von ausserhalb. Ohne Composite nennt ``reason`` den Grund.
    ``as_of``: Stand des Abrufs, auf dem der Bewertungslauf beruht.
    """

    scoring_run_id: PositiveId
    as_of: date
    symbol: str
    reference: ScoreReference
    rank: PositiveId | None = None
    value_score: float | None = Field(default=None, ge=0, le=1)
    quality_score: float | None = Field(default=None, ge=0, le=1)
    composite_score: float | None = Field(default=None, ge=0)
    composite_percentile: float | None = Field(default=None, ge=0, le=1)
    value_trap_flag: bool = False
    value_trap_reason: TrapReason | None = None
    industry_rule: bool = False
    reason: ScoreReason | None = None


class PositionValueV1(Contract):
    """Eine bewertete Position (D3.4, DEP-07): Kurs mit Datum und Quelle, Wert in EUR.

    ``price`` in ``price_currency`` (Hauptwaehrung), bei ``percent_of_par`` in Prozent vom
    Nennwert. ``fx_rate``: 1 Einheit ``price_currency`` in EUR. ``value_eur`` fehlt mit Grund
    (``missing``), nie als 0; in einer Beobachtungsliste fehlt er ohne Grund. ``pending``: noch
    ohne Stammdaten ("wird geprueft", WP-13).
    """

    isin: IsinStr
    name: str | None = None
    asset_class: AssetClass | None = None
    pending: bool = False
    quantity: Quantity | None = None
    unit: HoldingUnit = "pieces"
    price: Decimal | None = None
    price_currency: str | None = None
    price_date: date | None = None
    price_source: str | None = None  # yahoo, bundesbank
    percent_of_par: bool = False
    fx_rate: Decimal | None = None
    value_eur: Decimal | None = None
    cost_basis_eur: Decimal | None = None
    difference_eur: Decimal | None = None
    missing: ValueMissing | None = None
    # D4.2 (additiv): nur bei Aktien, die ein Bewertungslauf kennt
    score: PositionScoreV1 | None = None


class DepotValuationV1(Contract):
    """Bewertung eines Depots (D3.4, DEP-07, DEP-13).

    ``value_eur`` = bewertete Positionen + Kasse; ohne Wert bei einer Beobachtungsliste.
    ``complete`` heisst: jede Position mit Menge hat einen Wert; sonst zaehlt ``unvalued`` die
    fehlenden. ``price_date``: der aelteste Kurs der bewerteten Positionen. Einstand und Differenz
    nur ueber Positionen, fuer die sie bekannt sind. ``positions`` nur bei ``depots.get``.
    """

    value_eur: Decimal | None = None
    positions_eur: Decimal | None = None
    cash_eur: Decimal = Decimal(0)
    complete: bool = True
    unvalued: int = Field(default=0, ge=0)
    pending: int = Field(default=0, ge=0)
    cost_basis_eur: Decimal | None = None
    difference_eur: Decimal | None = None
    price_date: date | None = None
    positions: list[PositionValueV1] = Field(default_factory=list)


class DepotV1(Contract):
    """Ein Depot mit dem Stand seines Bestands; ``version`` 0 heisst: noch nichts erfasst.

    ``valuation`` (D3.4): fehlt, wenn portfolio keine Marktdaten hat oder sie nicht lesbar sind.
    """

    id: PositiveId
    kind: DepotKind
    name: str
    description: str | None = None
    status: DepotState
    created_at: datetime
    version: int = Field(ge=0)
    positions: int = Field(ge=0)
    valuation: DepotValuationV1 | None = None


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


class ImportEntryV1(Contract):
    """Eine ISIN im Abgleich (D3.5, DEP-05): vorher und nachher; ``pending``: noch ohne
    Stammdaten ("wird geprueft")."""

    isin: IsinStr
    status: ImportStatus
    before: HoldingLineV1 | None = None
    after: HoldingLineV1 | None = None
    pending: bool = False


class RejectedRowV1(Contract):
    """Eine Zeile der Datei, die nicht erkannt wurde, mit Grund."""

    line: int = Field(ge=1)
    reason: str


class ImportPreviewV1(Contract):
    """Abgleich einer Datei mit dem Depotstand ``base_version``. Uebernommen wird nur eine Datei
    ohne abgelehnte Zeilen, sonst entfielen deren Positionen still."""

    base_version: int = Field(ge=0)
    entries: list[ImportEntryV1] = Field(default_factory=list)
    rejected: list[RejectedRowV1] = Field(default_factory=list)


class DepotExportV1(Contract):
    """Ein Depot mit allen seinen Depotstaenden, aelteste zuerst (Datenexport, NUT-12, D3.2)."""

    depot: DepotV1
    versions: list[HoldingsV1] = Field(default_factory=list)


__all__ = [
    "MAX_FILE_BYTES",
    "MAX_LINES",
    "MAX_NAME",
    "MAX_TEXT",
    "Amount",
    "CashLineV1",
    "DepotExportV1",
    "DepotKind",
    "DepotName",
    "DepotState",
    "DepotV1",
    "DepotValuationV1",
    "HistoryEntryV1",
    "HoldingLineV1",
    "HoldingUnit",
    "HoldingsV1",
    "ImportEntryV1",
    "ImportPreviewV1",
    "ImportStatus",
    "PositionValueV1",
    "Quantity",
    "RejectedRowV1",
    "SnapshotSource",
    "Text",
    "ValueMissing",
]
