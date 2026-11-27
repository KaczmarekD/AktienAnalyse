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

from pydantic import Field, model_validator

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
    # D5.3 (additiv): alle Versionen der Schwellen und der Zielallokation, alle Kenntnisnahmen
    hint_params: list[HintParamsVersionV1] = Field(default_factory=list)
    targets: list[TargetVersionV1] = Field(default_factory=list)
    acks: list[HintAckV1] = Field(default_factory=list)


# --- D4.4: Analyse eines Depots (docs/architecture/depot/analyse.md, Abschnitt Depot) ---------
# Gewichte sind Bruchteile des Depotwerts (0,25 = 25 %), Betraege EUR auf Cent. Die Felder
# entsprechen va_portfolio.domain.analysis; ein Test haelt beide gleich.


class SliceV1(Contract):
    """Ein Teil der Allokation. ``key``: Anlageklasse, Waehrung, Sektor (wie bei yfinance) oder
    Land (ISO 3166); ``cash``, ``bonds``, ``unknown``, ``no_look_through`` ohne Zuordnung."""

    key: str
    value_eur: Decimal
    weight: float


class AllocationV1(Contract):
    asset_class: list[SliceV1] = Field(default_factory=list)
    currency: list[SliceV1] = Field(default_factory=list)
    sector: list[SliceV1] = Field(default_factory=list)
    country: list[SliceV1] = Field(default_factory=list)


class TitleV1(Contract):
    isin: IsinStr
    name: str | None = None
    weight: float


class ConcentrationV1(Contract):
    """Mit Durchschau; ``lower_bound``: ein ETF kennt nur seine groessten Positionen oder keine.
    ``effective_positions``: 1 / Summe Gewicht^2 ueber die Positionen (ETF als eine)."""

    largest: TitleV1 | None = None
    top: list[TitleV1] = Field(default_factory=list)
    top_weight: float
    effective_positions: float | None = None
    lower_bound: bool


class QuintileV1(Contract):
    quintile: int = Field(ge=1, le=5)  # 1 = unterstes Fuenftel des Referenzuniversums
    count: int = Field(ge=0)
    weight: float


class FundQualityV1(Contract):
    isin: IsinStr
    score: float | None = None  # Look-through-Score, erst ab 50 % bewertetem Gewicht
    covered: float
    lower_bound: bool


class QualityV1(Contract):
    """Wertgewichtet ueber die Aktien mit Score; ``covered`` = Anteil ihres Werts mit Composite."""

    equity_eur: Decimal
    covered: float
    composite: float | None = None
    value_score: float | None = None
    quality_score: float | None = None
    value_traps: int = Field(ge=0)
    quintiles: list[QuintileV1] = Field(default_factory=list)
    funds: list[FundQualityV1] = Field(default_factory=list)


class CostsV1(Contract):
    etf_eur: Decimal
    covered: float
    ter: float | None = None  # Prozent pro Jahr, wertgewichtet
    running_costs_eur: Decimal | None = None


class BondPositionV1(Contract):
    isin: IsinStr
    value_eur: Decimal | None = None
    maturity: date | None = None
    ytm: float | None = None
    modified_duration: float | None = None
    accrued: float | None = None  # je 100 Nennwert
    next_coupon: date | None = None
    special: str | None = None  # Grund ohne Rendite: floating, convertible, perpetual, ...


class MaturityYearV1(Contract):
    year: int
    value_eur: Decimal


class BondsV1(Contract):
    bond_eur: Decimal
    covered: float
    ytm: float | None = None
    modified_duration: float | None = None
    maturities: list[MaturityYearV1] = Field(default_factory=list)
    positions: list[BondPositionV1] = Field(default_factory=list)


class DataQualityV1(Contract):
    positions: int = Field(ge=0)
    valued: int = Field(ge=0)
    look_through: float | None = None
    oldest_price: date | None = None
    oldest_score: date | None = None
    oldest_fund_data: date | None = None


class DepotAnalysisV1(Contract):
    """Analyse eines Depots (D4.4, ANA-08 bis 10), bei jeder Anfrage neu gerechnet."""

    value_eur: Decimal | None = None
    allocation: AllocationV1
    concentration: ConcentrationV1
    quality: QualityV1
    costs: CostsV1
    bonds: BondsV1
    data: DataQualityV1


# --- D5: Hinweise (docs/architecture/depot/analyse.md, Abschnitt Hinweise) ---------------------
# Schwere eines Hinweises (HIN-02)
HintSeverity = Literal["info", "warning", "critical"]
MAX_HINT_KEY = 200  # Schluessel eines Hinweises: Regel und Gegenstand (D5.3)
# Die Regeln des Katalogs; ein Test haelt sie gleich mit va_portfolio.domain.hints.HINT_CATALOG
HintRuleId = Literal[
    "HIN-K01",
    "HIN-K02",
    "HIN-K03",
    "HIN-K04",
    "HIN-K05",
    "HIN-K06",
    "HIN-A01",
    "HIN-A02",
    "HIN-Q01",
    "HIN-Q02",
    "HIN-Q03",
    "HIN-Q04",
    "HIN-Q05",
    "HIN-Q06",
    "HIN-E01",
    "HIN-E02",
    "HIN-E03",
    "HIN-B01",
    "HIN-B02",
    "HIN-B03",
    "HIN-N01",
    "HIN-N02",
    "HIN-D01",
    "HIN-D02",
    "HIN-D03",
]
Share = Annotated[float, Field(gt=0, le=1)]  # Anteil am Depot, 0,1 = 10 %


class HintParamsV1(Contract):
    """Schwellen der Hinweise je Depot (HIN-04), mit Standardwerten aus dem Katalog.

    Anteile als Bruchteil (0,1 = 10 %), TER und Kurs in Prozent, Fondsvolumen in Millionen EUR.
    ``disabled``: abgeschaltete Regeln. Ein gespeicherter Stand ohne ein spaeter neues Feld bekommt
    beim Lesen den Standardwert, wie bei den Scoring-Profilen.
    """

    k01_warning: Share = 0.10  # Einzeltitel, Warnung
    k01_critical: Share = 0.20  # Einzeltitel, kritisch
    k02_top5: Share = 0.50
    k03_sector: Share = 0.30
    k04_country: Share = 0.50
    k05_foreign_currency: Share = 0.50
    k06_issuer: Share = 0.10
    a01_deviation: Share = 0.05  # Prozentpunkte zur Zielallokation (D5.3)
    a02_cash: Share = 0.10
    q02_percentile: Share = 0.20
    q03_drop: Share = 0.20  # Rueckgang des Composite-Perzentils (D5.2)
    q04_quality: Share = 0.30
    e01_ter: float = Field(default=0.5, gt=0, le=5)
    e02_overlap: Share = 0.50
    e03_fund_size: float = Field(default=100.0, gt=0, le=100_000)
    b01_days: int = Field(default=90, ge=1, le=3650)
    b02_price: float = Field(default=80.0, gt=0, le=200)
    b03_maturity_year: Share = 0.50
    d01_trading_days: int = Field(default=5, ge=1, le=60)
    d02_bank_days: int = Field(default=30, ge=1, le=365)  # D8
    n01_days: int = Field(default=7, ge=1, le=90)  # D6
    n02_days: int = Field(default=30, ge=1, le=365)  # D6
    disabled: list[HintRuleId] = Field(default_factory=list)
    candidates: bool = False  # Pruefkandidaten (HIN-06), standardmaessig aus

    @model_validator(mode="after")
    def _critical_above_warning(self) -> HintParamsV1:
        if self.k01_critical <= self.k01_warning:
            msg = "k01_critical muss ueber k01_warning liegen"
            raise ValueError(msg)
        return self


# D5.2: Status gegen den vorherigen Lauf (HIN-03)
HintStatus = Literal["new", "existing", "resolved"]


class HintV1(Contract):
    """Ein Hinweis (D5.2) mit den Texten seines Katalogeintrags, damit das web-api den Katalog
    nicht kennen muss. ``measured``/``threshold``: Anteile als Bruchteil, TER und Kurs in Prozent,
    Tage und Handelstage als Zahl; ``as_of``: Datenstand."""

    key: str
    rule: HintRuleId
    subject: str
    severity: HintSeverity
    status: HintStatus
    measured: float | None = None
    threshold: float | None = None
    as_of: date | None = None
    group: str
    title: str
    reason: str
    approach: str
    # D5.3 (additiv): zur Kenntnis genommen; gilt nicht mehr, sobald der Hinweis schwerer wird
    # oder sich der Messwert um die Spanne der Regel verschlechtert
    acknowledged: bool = False


class ComparisonCandidateV1(Contract):
    """D5.5: ein Titel zum Vergleich: Referenzuniversum, selber Sektor, hoeherer Composite, ohne
    Value-Trap-Flag, nicht im Depot. Werte wie im Ranking desselben Bewertungslaufs."""

    isin: IsinStr
    symbol: str
    name: str | None = None
    rank: int | None = None
    composite_score: float
    composite_percentile: float | None = None
    value_score: float | None = None
    quality_score: float | None = None


class DepotComparisonV1(Contract):
    """D5.5 (HIN-06): Pruefkandidaten zu einer Aktie des Depots, hoechstens drei.
    ``enabled`` falsch, solange sie in den Schwellen aus sind (Standard)."""

    isin: IsinStr
    enabled: bool
    sector: str | None = None
    scoring_run_id: int | None = None
    as_of: date | None = None
    candidates: list[ComparisonCandidateV1] = Field(default_factory=list)


class HintRuleV1(Contract):
    """D5.4: ein Eintrag des Katalogs der Hinweise mit seinen Texten, fuer das UI."""

    rule: HintRuleId
    group: str
    title: str
    reason: str
    approach: str
    # False: steht im Katalog, wird aber erst mit den News (D6) oder der Bank (D8) gerechnet
    available: bool = True


class DepotHintsV1(Contract):
    """Die Hinweise des juengsten Laufs; ``analysis_run_id`` leer ohne Lauf (ohne Marktdaten)."""

    analysis_run_id: PositiveId | None = None
    computed_at: datetime | None = None
    version: int = Field(default=0, ge=0)  # Depotstand des Laufs
    hints: list[HintV1] = Field(default_factory=list)
    # D5.5 (additiv): Pruefkandidaten eingeschaltet (HIN-06), das UI bietet sie dann an
    candidates: bool = False


# --- D5.3: Einstellungen je Depot (Schwellen, Zielallokation) ----------------------------------
# Anlageklassen der Zielallokation (DEP-10), wie in der Allokation der Analyse
TargetClass = Literal["equity", "etf", "bond", "other", "cash"]
TARGET_TOLERANCE = 0.001  # Rundung: Anteile muessen zusammen 100 % ergeben


class TargetAllocationV1(Contract):
    """Zielallokation je Anlageklasse (DEP-10, HIN-A01), zusammen 100 %; leer heisst ohne Ziel.
    Eine Region je Klasse sieht die Spezifikation als Kann vor; sie fehlt vorerst."""

    shares: dict[TargetClass, Annotated[float, Field(ge=0, le=1)]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _all_of_it(self) -> TargetAllocationV1:
        if self.shares and abs(sum(self.shares.values()) - 1) > TARGET_TOLERANCE:
            msg = "Die Anteile der Zielallokation muessen zusammen 100 % ergeben"
            raise ValueError(msg)
        return self


class DepotSettingsV1(Contract):
    """Schwellen der Hinweise und Zielallokation eines Depots, je mit Version (0: Standard bzw.
    ohne Ziel). Jede Aenderung legt eine neue Version an, die alten bleiben."""

    hint_params: HintParamsV1 = Field(default_factory=HintParamsV1)
    hint_params_version: int = Field(default=0, ge=0)
    target: TargetAllocationV1 = Field(default_factory=TargetAllocationV1)
    target_version: int = Field(default=0, ge=0)


class HintParamsVersionV1(Contract):
    """D5.3: eine gespeicherte Version der Schwellen eines Depots (Datenexport, NUT-12)."""

    version: int = Field(ge=1)
    params: HintParamsV1
    created_at: datetime


class TargetVersionV1(Contract):
    """D5.3: eine gespeicherte Version der Zielallokation eines Depots (Datenexport, NUT-12)."""

    version: int = Field(ge=1)
    target: TargetAllocationV1
    created_at: datetime


class HintAckV1(Contract):
    """D5.3: ein Hinweis zur Kenntnis genommen, mit Messwert und Schwere in diesem Moment."""

    key: str = Field(max_length=MAX_HINT_KEY)
    measured: float | None = None
    severity: HintSeverity
    at: datetime


DepotExportV1.model_rebuild()


__all__ = [
    "MAX_FILE_BYTES",
    "MAX_HINT_KEY",
    "MAX_LINES",
    "MAX_NAME",
    "MAX_TEXT",
    "TARGET_TOLERANCE",
    "AllocationV1",
    "Amount",
    "BondPositionV1",
    "BondsV1",
    "CashLineV1",
    "ComparisonCandidateV1",
    "ConcentrationV1",
    "CostsV1",
    "DataQualityV1",
    "DepotAnalysisV1",
    "DepotComparisonV1",
    "DepotExportV1",
    "DepotHintsV1",
    "DepotKind",
    "DepotName",
    "DepotSettingsV1",
    "DepotState",
    "DepotV1",
    "DepotValuationV1",
    "FundQualityV1",
    "HintAckV1",
    "HintParamsV1",
    "HintParamsVersionV1",
    "HintRuleId",
    "HintRuleV1",
    "HintSeverity",
    "HintStatus",
    "HintV1",
    "HistoryEntryV1",
    "HoldingLineV1",
    "HoldingUnit",
    "HoldingsV1",
    "ImportEntryV1",
    "ImportPreviewV1",
    "ImportStatus",
    "MaturityYearV1",
    "PositionScoreV1",
    "PositionValueV1",
    "QualityV1",
    "Quantity",
    "QuintileV1",
    "RejectedRowV1",
    "ScoreReason",
    "ScoreReference",
    "SliceV1",
    "SnapshotSource",
    "TargetAllocationV1",
    "TargetClass",
    "TargetVersionV1",
    "Text",
    "TitleV1",
    "ValueMissing",
]
