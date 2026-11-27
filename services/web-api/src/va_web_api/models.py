"""Antwortmodelle der REST-API v1 (P3.2).

Sie sind der Vertrag mit dem Frontend: Der OpenAPI-Snapshot und der daraus generierte Client
(P3.5) leiten sich von ihnen ab. Aenderungen nur additiv (frontend.md).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from va_contracts.events.v1.ranking import ValueTrapReason
from va_contracts.portfolio import (
    MAX_FILE_BYTES,
    MAX_LINES,
    MAX_NAME,
    MAX_TEXT,
    Amount,
    Quantity,
)
from va_contracts.profile import ProfileParamsV1
from va_contracts.securities import IsinStr


class _Model(BaseModel):
    # Tippfehler in einer Abfrage sollen auffallen, statt still zu fehlen
    model_config = ConfigDict(extra="forbid")


class RunSummary(_Model):
    id: int
    kind: str  # batch / rescore / import
    status: str  # running / success / partial / no_data / failed
    started_at: datetime
    finished_at: datetime | None
    dry_run: bool
    force_refresh: bool
    universe_mode: str | None
    universe_size: int | None
    scored_count: int | None
    failed_count: int | None
    exit_code: int | None


class RunDetail(RunSummary):
    app_version: str
    error: str | None
    fetch_run_id: int | None
    scoring_run_id: int | None
    report_id: int | None


class RunStart(_Model):
    """Ein Run aus dem UI (P4.7); die Optionen wie ``RunOptionsV1`` im Event."""

    force_refresh: bool = Field(
        default=False, description="Snapshot vom selben Tag nicht wiederverwenden"
    )
    dry_run: bool = Field(default=False, description="Mail rendern und speichern, nicht senden")
    notify: bool = Field(default=True, description="Mail verschicken; aus fuer Test-Runs")


class RunStarted(_Model):
    id: int  # batch.run.id; Fortschritt und Ergebnis kommen ueber den WebSocket


class RankingRow(_Model):
    rank: int | None  # leer: am Groessenfilter gescheitert
    symbol: str
    name: str | None
    index: str | None
    sector: str | None
    passed_filter: bool
    composite_score: float | None  # leer ohne beide Teilscores (M1)
    value_score: float | None
    quality_score: float | None
    value_trap_flag: bool | None
    # F2.3: welche Regel das Flag gesetzt hat; leer ohne Flag und bei aelteren Laeufen
    value_trap_reason: ValueTrapReason | None
    market_cap: float | None
    currency: str | None
    ev_ebit: float | None
    pb_ratio: float | None
    p_fcf: float | None
    shareholder_yield: float | None
    # F2.2: Netto-Emission (im Profil v1 abgeschaltet)
    net_share_issuance: float | None
    roic: float | None
    fcf_margin: float | None
    operating_margin: float | None
    net_debt_ebitda: float | None
    earnings_stability: float | None
    # F2.1: Bilanzqualitaet (im Profil v1 abgeschaltet)
    f_score: int | None
    operating_accruals: float | None
    cfo_assets: float | None


class RunProfile(_Model):
    """Profil eines Bewertungslaufs (Track G, G3)."""

    id: int
    version: int
    name: str | None


class Ranking(_Model):
    scoring_run_id: int
    fetch_run_id: int | None
    origin: str  # live / rescore / import
    created_at: datetime
    fetched_on: date | None  # Tag des Abrufs
    universe_source: str | None
    value_weight: float | None  # Import: keine Konfiguration gespeichert
    quality_weight: float | None
    # Track G (G3), additiv: Profil und Parameter, mit denen gerechnet wurde; leer bei Altdaten
    profile: RunProfile | None = None
    params: ProfileParamsV1 | None = None
    rows: list[RankingRow]


class Snapshot(_Model):
    fetch_run_id: int
    fetched_on: date
    fetch_ok: bool
    price: float | None
    currency: str | None
    market_cap: float | None
    # F2.3: 12-1-Momentum, nur fuer die Value-Trap-Regel
    momentum_12_1: float | None
    ev_ebit: float | None
    pe_ratio: float | None
    pb_ratio: float | None
    p_fcf: float | None
    dividend_yield: float | None
    shareholder_yield: float | None
    # F2.2: Netto-Emission (im Profil v1 abgeschaltet)
    net_share_issuance: float | None
    roic: float | None
    fcf_margin: float | None
    operating_margin: float | None
    net_debt_ebitda: float | None
    earnings_stability: float | None
    # F2.1: Bilanzqualitaet (im Profil v1 abgeschaltet)
    f_score: int | None
    operating_accruals: float | None
    cfo_assets: float | None
    revenue_growth_5y: float | None
    eps_growth_5y: float | None
    errors: list[str]


class ScorePoint(_Model):
    scoring_run_id: int
    created_at: datetime
    origin: str
    rank: int | None
    passed_filter: bool
    composite_score: float | None
    value_score: float | None
    quality_score: float | None
    value_trap_flag: bool | None
    # F2.3: welche Regel das Flag gesetzt hat
    value_trap_reason: ValueTrapReason | None
    # Track G (G3), additiv: Titel mit Rang im selben Lauf, fuer "Rang 1 von N"
    ranked_count: int | None = None


class FactorRanks(_Model):
    """Perzentile je Faktor eines Titels im juengsten Bewertungslauf (Track G, G3)."""

    scoring_run_id: int
    # Faktor -> Anteil der Titel, die schlechter abschneiden (0 bis 1). Genau die Faktoren des
    # Profils dieses Laufs; null, wenn Daten fehlten.
    ranks: dict[str, float | None]


class InstrumentAnchors(_Model):
    """Fundamentale Anker eines Titels im juengsten Bewertungslauf (F3.1, F3.2a).

    Nicht im Composite. ``_r_low`` und ``_r_high``: bei Kapitalkosten 1 Prozentpunkt darunter
    und darueber. Kapitalkosten, Endwachstum und Jahre stehen in den Parametern des Laufs.
    """

    scoring_run_id: int
    epv_per_share: float | None  # Handelswaehrung
    price_to_epv: float | None
    implied_fcf_growth: float | None
    price_to_epv_r_low: float | None
    price_to_epv_r_high: float | None
    implied_fcf_growth_r_low: float | None
    implied_fcf_growth_r_high: float | None


class Instrument(_Model):
    symbol: str
    isin: str | None
    name: str | None
    index: str | None
    sector: str | None
    industry: str | None
    latest: Snapshot | None  # neuester gueltiger Abruf
    score_history: list[ScorePoint]  # aeltester zuerst
    factor_ranks: FactorRanks | None = None  # G3; leer ohne Bewertung im juengsten Lauf
    # F3.2a: leer ohne Anker im juengsten Lauf (Finanzwerte, fehlende Daten)
    anchors: InstrumentAnchors | None = None


class Report(_Model):
    id: int
    run_id: int | None
    scoring_run_id: int | None
    subject: str
    generated_at: datetime
    csv_filename: str
    html: str


# --- Scoring-Profile (P3.3, ADR-0009) -------------------------------------------------------


class Factor(_Model):
    """Ein Faktor des Katalogs. Welche aktiv sind, steht im Profil; die Richtung ist fest."""

    key: str
    group: Literal["value", "quality"]
    label: str
    better: Literal["low", "high"]  # niedriger oder hoeher Wert ist besser
    hint: str  # Methodik-Hinweis fuer das UI


class ProfileVersion(_Model):
    version: int
    params: ProfileParamsV1
    parent_version: int | None  # die Version, auf der diese beruht
    comment: str | None
    created_at: datetime
    active: bool


class ProfileSummary(_Model):
    id: int
    name: str
    created_at: datetime
    latest_version: int | None
    active_version: int | None  # leer, wenn ein anderes Profil aktiv ist


class ProfileDetail(ProfileSummary):
    versions: list[ProfileVersion]  # neueste zuerst


class SaveProfileVersion(_Model):
    params: ProfileParamsV1
    comment: str | None = Field(default=None, max_length=500)


class SavedProfileVersion(_Model):
    profile_id: int
    version: int
    parent_version: int


class ActivateProfileVersion(_Model):
    version: int = Field(ge=1)


class ActivatedProfile(_Model):
    profile_id: int
    version: int


class ActiveProfileRef(_Model):
    profile_id: int
    name: str
    version: int


class PreviewRow(_Model):
    """Ein Titel mit den neuen params und, zum Vergleich, mit dem aktiven Profil."""

    symbol: str
    name: str | None
    index: str | None
    passed_filter: bool
    rank: int | None
    rank_active: int | None
    composite_score: float | None
    value_score: float | None
    quality_score: float | None
    value_trap_flag: bool | None
    # F2.3: welche Regel das Flag mit den neuen params gesetzt hat
    value_trap_reason: ValueTrapReason | None
    value_trap_flag_active: bool | None


class Preview(_Model):
    scoring_run_id: int  # dessen Abruf ist die Grundlage
    fetch_run_id: int
    fetched_on: date | None
    active: ActiveProfileRef | None
    top: int
    entered: list[str]  # neu in den Top ``top``, nach neuem Rang
    left: list[str]  # nicht mehr in den Top ``top``, nach altem Rang
    trap_changed: list[str]  # Value-Trap-Markierung geaendert
    rows: list[PreviewRow]  # nach neuem Rang


# D1.1: Anmeldung (docs/architecture/depot/nutzer.md)
PASSWORD_MAX = 1024  # Obergrenze gegen sehr lange Eingaben vor dem teuren Hash


class LoginRequest(_Model):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=PASSWORD_MAX)


class Me(_Model):
    """Das eigene Konto, ohne Anmeldedaten."""

    id: int
    username: str
    role: Literal["admin", "user"]
    display_name: str | None
    email: str | None
    # D1.4: Einmal-Passwort; bis es ersetzt ist, antworten die anderen Endpunkte mit 403
    must_change_password: bool
    # D1.6: neue Adresse, die auf den Link aus der Mail wartet; bis dahin gilt ``email``
    pending_email: str | None = None


class SessionState(_Model):
    """Wer angemeldet ist; ``user`` fehlt ohne gueltige Sitzung (D1.4)."""

    user: Me | None


# D1.4: eigenes Konto und Nutzerverwaltung (NUT-11, Rollen)
class PasswordChange(_Model):
    current_password: str = Field(min_length=1, max_length=PASSWORD_MAX)
    new_password: str = Field(min_length=1, max_length=PASSWORD_MAX)


class ProfileUpdate(_Model):
    """Anzeigename; leer entfernt ihn. Eine neue Mail-Adresse gilt erst nach dem Link aus der Mail
    (D1.6); ohne ``email`` bleibt die Adresse, wie sie ist."""

    display_name: str | None = Field(default=None, max_length=100)
    email: str | None = Field(default=None, max_length=254)


class EmailConfirmation(_Model):
    """Das Token aus dem Link der Bestaetigungsmail (D1.6)."""

    token: str = Field(min_length=1, max_length=200)


class DataExport(_Model):
    """Alle eigenen Daten (D1.6, NUT-12), je Tabelle eine Liste, ohne Hashes und Tokens."""

    exported_at: datetime
    account: list[dict[str, Any]]
    profiles: list[dict[str, Any]]
    statuses: list[dict[str, Any]]
    credentials: list[dict[str, Any]]  # wann ein Passwort gesetzt wurde, ohne Hash
    sessions: list[dict[str, Any]]
    logins: list[dict[str, Any]]
    email_confirmations: list[dict[str, Any]]
    # D3.2: die eigenen Depots aus portfolio, auch archivierte, mit allen Depotstaenden
    depots: list[DepotExport] = Field(default_factory=list)


class SessionInfo(_Model):
    """Eine gueltige Sitzung des eigenen Kontos; ``current`` ist die dieser Anfrage."""

    created_at: datetime
    last_seen: datetime
    expires_at: datetime
    user_agent: str | None
    current: bool


class Account(_Model):
    """Ein Konto in der Nutzerverwaltung."""

    id: int
    username: str
    role: Literal["admin", "user"]
    display_name: str | None
    email: str | None
    active: bool
    must_change_password: bool
    created_at: datetime | None


class NewAccount(_Model):
    """Neues Konto mit Einmal-Passwort, das der Nutzer bei der ersten Anmeldung ersetzt."""

    username: str = Field(min_length=1, max_length=64)
    role: Literal["admin", "user"] = "user"
    display_name: str | None = Field(default=None, max_length=100)
    email: str | None = Field(default=None, max_length=254)
    one_time_password: str = Field(min_length=1, max_length=PASSWORD_MAX)


class PasswordReset(_Model):
    """Neues Einmal-Passwort; alle Sitzungen des Kontos enden."""

    one_time_password: str = Field(min_length=1, max_length=PASSWORD_MAX)


# D2.1: Wertpapiere ueber die ISIN (docs/architecture/depot/wertpapiere.md)
AssetClass = Literal["equity", "etf", "bond", "other"]


class Listing(_Model):
    """Handel an einem Boersenplatz; ``symbol`` ist das Yahoo-Symbol, falls es eines gibt."""

    symbol: str | None
    ticker: str | None
    exchange: str | None
    currency: str | None


class SecurityHit(_Model):
    """Ein Treffer der Suche. Treffer der Yahoo-Suche haben keine ISIN."""

    isin: str | None
    name: str
    asset_class: AssetClass
    listings: list[Listing]
    source: str  # catalog, openfigi, yahoo; weitere Quellen ohne neue API-Version


class BondTerms(_Model):
    """Ausstattung einer Anleihe aus ESMA FIRDS."""

    coupon: float | None
    maturity: date | None
    denomination: float | None
    seniority: str | None
    floating: bool


class EtfHolding(_Model):
    """Eine Position eines Fonds; Bezeichnungen wie bei der Quelle."""

    name: str
    weight: float  # in Prozent des Fondsvermoegens, bei Geldmarkt auch negativ
    isin: str | None
    ticker: str | None
    asset_class: str | None
    sector: str | None
    country: str | None
    currency: str | None


class Etf(_Model):
    """Stand eines Fonds aus dem letzten Wochenlauf (D2.4): Fondsdaten, Gewichte in Prozent und
    die groessten Positionen. ``complete`` sagt, ob die Quelle alle Positionen kennt."""

    source: str  # ishares, yahoo
    as_of: date
    complete: bool
    name: str | None  # Name beim Anbieter; der aus FIRDS ist oft gekuerzt
    ter: float | None  # laufende Kosten in Prozent pro Jahr
    fund_size: float | None  # in Millionen der Fondswaehrung
    fund_currency: str | None
    distribution: Literal["accumulating", "distributing"] | None
    provider: str | None
    effective_duration: float | None  # Anleihe-ETFs, in Jahren
    holdings_count: int
    top_holdings: list[EtfHolding]
    sectors: dict[str, float]
    countries: dict[str, float]
    asset_classes: dict[str, float]


class Security(_Model):
    """Ein Wertpapier mit Stammdaten, Listings und dem Listing fuer den Datenabruf."""

    isin: str
    name: str
    asset_class: AssetClass
    currency: str | None
    lei: str | None
    cfi: str | None
    bond: BondTerms | None
    listings: list[Listing]
    listing: Listing | None
    etf: Etf | None  # D2.4: nur bei ETFs, sofern eine Quelle sie kennt


# --- Depots (D3.2, docs/architecture/depot/depots.md) ------------------------------------
# Mengen und Betraege als Decimal: im JSON eine Zahl im String ("12.5"), nie float. Eingaben
# duerfen Zahl oder String sein. Die Grenzen sind die der Contracts (va_contracts.portfolio).

DepotKindName = Literal["depot", "watchlist"]


class PositionScore(_Model):
    """Scores einer Aktie im Depot (D4.2) aus dem juengsten Bewertungslauf, der sie kennt.

    ``reference``: ``universe`` = Titel des Rankings, mit denselben Werten wie dort und seinem
    Rang; ``below_size_filter`` = Universumstitel unter dem Groessenfilter, ``outside`` = Aktie
    ausserhalb von DAX/MDAX, beide ins Referenzuniversum eingeordnet. Ohne Composite nennt
    ``reason`` den Grund. ``as_of``: Stand des Abrufs dieses Bewertungslaufs.
    """

    scoring_run_id: int
    as_of: date
    symbol: str
    reference: Literal["universe", "below_size_filter", "outside"]
    rank: int | None
    value_score: float | None
    quality_score: float | None
    composite_score: float | None
    composite_percentile: float | None
    value_trap_flag: bool
    value_trap_reason: Literal["quality", "momentum"] | None
    industry_rule: bool
    reason: Literal["no_value", "no_quality", "no_data"] | None


class PositionValue(_Model):
    """Eine bewertete Position (D3.4): letzter Kurs mit Datum und Quelle, Wert in EUR.

    ``price`` in ``price_currency``, bei ``percent_of_par`` in Prozent vom Nennwert; ``fx_rate``
    ist 1 Einheit dieser Waehrung in EUR. Ohne Wert nennt ``missing`` den Grund (``price``,
    ``fx``, ``unit``), in einer Beobachtungsliste fehlt er ohne Grund. ``pending``: noch ohne
    Stammdaten ("wird geprueft").
    """

    isin: str
    name: str | None
    asset_class: AssetClass | None
    pending: bool
    quantity: Decimal | None
    unit: Literal["pieces", "nominal"]
    price: Decimal | None
    price_currency: str | None
    price_date: date | None
    price_source: str | None
    percent_of_par: bool
    fx_rate: Decimal | None
    value_eur: Decimal | None
    cost_basis_eur: Decimal | None
    difference_eur: Decimal | None
    missing: Literal["price", "fx", "unit"] | None
    score: PositionScore | None  # D4.2: nur bei Aktien, die ein Bewertungslauf kennt


class DepotValuation(_Model):
    """Bewertung eines Depots (D3.4): bewertete Positionen plus Kasse, in EUR.

    ``complete`` falsch heisst: ``unvalued`` Positionen haben keinen Wert, ``value_eur`` enthaelt
    sie nicht. ``price_date``: der aelteste Kurs der bewerteten Positionen. Einstand und Differenz
    nur, wo bekannt. ``positions`` nur bei ``GET /depots/{id}``.
    """

    value_eur: Decimal | None
    positions_eur: Decimal | None
    cash_eur: Decimal
    complete: bool
    unvalued: int
    pending: int
    cost_basis_eur: Decimal | None
    difference_eur: Decimal | None
    price_date: date | None
    positions: list[PositionValue]


# --- Analyse (D4.4, docs/architecture/depot/analyse.md) ----------------------------------
# Gewichte sind Bruchteile des Depotwerts (0,25 = 25 %), Betraege EUR auf Cent.


class AllocationSlice(_Model):
    """``key``: Anlageklasse, Waehrung, Sektor (wie bei yfinance) oder Land (ISO 3166); ohne
    Zuordnung ``cash``, ``bonds``, ``unknown`` oder ``no_look_through`` (ETF ohne Daten)."""

    key: str
    value_eur: Decimal
    weight: float


class Allocation(_Model):
    """Sektor und Land mit Durchschau durch die ETFs; Aktien nach ISIN-Land."""

    asset_class: list[AllocationSlice]
    currency: list[AllocationSlice]
    sector: list[AllocationSlice]
    country: list[AllocationSlice]


class ConcentrationTitle(_Model):
    isin: str
    name: str | None
    weight: float


class Concentration(_Model):
    """Mit Durchschau; ``lower_bound``: mindestens ein ETF kennt nur seine groessten Positionen
    oder keine (dann "mindestens"). ``effective_positions`` = 1 / Summe Gewicht^2."""

    largest: ConcentrationTitle | None
    top: list[ConcentrationTitle]
    top_weight: float
    effective_positions: float | None
    lower_bound: bool


class Quintile(_Model):
    quintile: int  # 1 = unterstes Fuenftel des Referenzuniversums, 5 = oberstes
    count: int
    weight: float


class FundQuality(_Model):
    """Look-through-Score eines ETF, erst ab 50 % bewertetem Gewicht (``covered``)."""

    isin: str
    score: float | None
    covered: float
    lower_bound: bool


class DepotQuality(_Model):
    """Wertgewichtet ueber die Aktien mit Score; ``covered``: Anteil ihres Werts mit Composite."""

    equity_eur: Decimal
    covered: float
    composite: float | None
    value_score: float | None
    quality_score: float | None
    value_traps: int
    quintiles: list[Quintile]
    funds: list[FundQuality]


class DepotCosts(_Model):
    etf_eur: Decimal
    covered: float
    ter: float | None  # Prozent pro Jahr, wertgewichtet
    running_costs_eur: Decimal | None


class BondPosition(_Model):
    """Kennzahlen zum letzten Kurs; ohne Rendite nennt ``special`` den Grund."""

    isin: str
    value_eur: Decimal | None
    maturity: date | None
    ytm: float | None
    modified_duration: float | None
    accrued: float | None
    next_coupon: date | None
    special: str | None


class MaturityYear(_Model):
    year: int
    value_eur: Decimal


class DepotBonds(_Model):
    bond_eur: Decimal
    covered: float
    ytm: float | None
    modified_duration: float | None
    maturities: list[MaturityYear]
    positions: list[BondPosition]


class DataQuality(_Model):
    positions: int
    valued: int
    look_through: float | None
    oldest_price: date | None
    oldest_score: date | None
    oldest_fund_data: date | None


class DepotAnalysis(_Model):
    """Analyse eines Depots (D4.4), bei jeder Anfrage aus dem neuesten Depotstand, den letzten
    Kursen, dem juengsten Bewertungslauf und den Stammdaten gerechnet."""

    value_eur: Decimal | None
    allocation: Allocation
    concentration: Concentration
    quality: DepotQuality
    costs: DepotCosts
    bonds: DepotBonds
    data: DataQuality


class Depot(_Model):
    """Ein eigenes Depot; ``version`` 0 heisst: noch kein Depotstand gespeichert.

    ``valuation`` (D3.4): fehlt, solange portfolio keine Marktdaten hat oder sie nicht lesbar sind.
    """

    id: int
    kind: DepotKindName
    name: str
    description: str | None
    status: Literal["active", "archived"]
    created_at: datetime
    version: int
    positions: int
    valuation: DepotValuation | None


class HoldingLine(_Model):
    """Eine Position; in einer Beobachtungsliste ohne Menge und Einstand."""

    isin: IsinStr
    quantity: Quantity | None = None  # Stueck, bei Anleihen der Nennwert
    unit: Literal["pieces", "nominal"] = "pieces"
    cost_basis_eur: Annotated[Amount, Field(ge=0)] | None = None  # Einstand der ganzen Position
    note: Annotated[str, Field(max_length=MAX_TEXT)] | None = None


class CashLine(_Model):
    """Guthaben auf dem Verrechnungskonto, in EUR."""

    currency: Literal["EUR"] = "EUR"
    amount: Amount


class Holdings(_Model):
    """Ein Depotstand; ``version`` 0 ist der leere Stand vor der ersten Speicherung."""

    depot_id: int
    version: int
    source: Literal["manual", "import", "bank"] | None
    created_at: datetime | None
    created_by: int | None
    lines: list[HoldingLine]
    cash: list[CashLine]


# D3.5: Base64 von hoechstens ``MAX_FILE_BYTES`` (4 Zeichen je 3 Bytes, aufgerundet)
MAX_FILE_BASE64 = -(-MAX_FILE_BYTES // 3) * 4


class ImportFile(_Model):
    """Eine Datei im eigenen Format (D3.5, DEP-05): ``isin;menge;einstand;notiz`` und optional
    ``einheit``, ``;``, Dezimalkomma, UTF-8 (BOM erlaubt) oder Windows-1252, hoechstens 640 KiB.
    Als JSON statt multipart, damit schreibende Endpunkte nur JSON annehmen."""

    filename: Annotated[str, Field(max_length=255)] | None = None  # nur zur Anzeige
    content_base64: Annotated[str, Field(min_length=1, max_length=MAX_FILE_BASE64)]


class ImportEntry(_Model):
    """Eine ISIN im Abgleich: ``new``, ``changed``, ``unchanged`` oder ``removed``; ``pending``:
    noch ohne Stammdaten ("wird geprueft")."""

    isin: str
    status: Literal["new", "changed", "unchanged", "removed"]
    before: HoldingLine | None
    after: HoldingLine | None
    pending: bool


class RejectedRow(_Model):
    """Eine Zeile der Datei, die nicht erkannt wurde."""

    line: int
    reason: str


class ImportPreview(_Model):
    """Abgleich mit dem Depotstand ``base_version`` (als ``If-Match`` fuers Uebernehmen).
    Uebernehmen geht nur ohne ``rejected``."""

    base_version: int
    entries: list[ImportEntry]
    rejected: list[RejectedRow]


class HistoryEntry(_Model):
    """Ein Depotstand im Verlauf, mit dem Unterschied zum vorherigen."""

    version: int
    source: Literal["manual", "import", "bank"]
    created_at: datetime
    created_by: int | None
    positions: int
    added: int
    changed: int
    removed: int


class CreateDepot(_Model):
    kind: DepotKindName = "depot"
    name: Annotated[str, Field(min_length=1, max_length=MAX_NAME)]
    description: Annotated[str, Field(max_length=MAX_TEXT)] | None = None


class UpdateDepot(_Model):
    name: Annotated[str, Field(min_length=1, max_length=MAX_NAME)]
    description: Annotated[str, Field(max_length=MAX_TEXT)] | None = None


class SaveHoldings(_Model):
    """Der ganze neue Depotstand; die Basisversion steht in ``If-Match``."""

    lines: list[HoldingLine] = Field(default_factory=list, max_length=MAX_LINES)
    cash: list[CashLine] = Field(default_factory=list, max_length=1)


class DepotExport(_Model):
    """Ein Depot mit allen Depotstaenden, aelteste zuerst (Datenexport)."""

    depot: Depot
    versions: list[Holdings]
