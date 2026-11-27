"""Analyse eines Depots (D4.4, ANA-08 bis 10; docs/architecture/depot/analyse.md, Abschnitt Depot).

Reine Rechnung aus der Bewertung (``DepotValue``: Werte, Kurse, Scores je Position) und den
Stammdaten der ETFs und Anleihen. Neu gerechnet bei jeder Anfrage, also immer auf dem Stand von
Depotstand, Kursen, Bewertungslauf und Stammdaten (ANA-10).

- **Anlageklasse** aus den Stammdaten; fehlen sie noch, ist eine Position mit Score eine Aktie.
- **Gewichte** beziehen sich auf den Wert des Depots (bewertete Positionen plus Kasse).
  Positionen ohne Wert zaehlen nicht mit; die Datenlage nennt, wie viele es sind.
- **Allokation** nach Anlageklasse, Waehrung, Sektor und Land. Sektor und Land mit Durchschau
  durch die ETFs (Gewichte aus ihren Stammdaten), sonst ``no_look_through``. Aktien: Sektor aus
  dem Bewertungslauf, Land aus der ISIN (Sitz). ETFs: Waehrung ist die Fondswaehrung.
- **Konzentration**: groesster Einzeltitel und Top 5 mit Durchschau (Untergrenze, wenn ein ETF
  nur seine groessten Positionen kennt oder gar keine), effektive Zahl der Positionen
  ``1 / Summe Gewicht^2`` ueber die Positionen ohne Kasse, ein ETF zaehlt als eine.
- **Qualitaet**: wertgewichteter Composite, Value und Quality ueber die Aktien mit Score,
  Abdeckung, Zahl der Value-Trap-Flags, Verteilung auf die Fuenftel des Referenzuniversums
  (nach Composite-Perzentil), Look-through-Score je ETF.
- **Kosten**: wertgewichtete TER der ETFs, laufende Kosten in EUR pro Jahr.
- **Anleihen**: wertgewichtete Rendite und modifizierte Duration, Faelligkeitsprofil, je Anleihe
  die Kennzahlen aus ``bonds.bond_figures`` zum letzten Kurs.
- **Datenlage**: bewertete Positionen, Anteil der ETFs mit Durchschau, aelteste Kurse, Scores und
  ETF-Daten.

Keine Rendite des Depots, keine Wertentwicklung, kein Vergleich mit einem Index (Nicht-Ziele).
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from .bonds import BondTerms, bond_figures
from .funds import Fund, look_through, look_through_score, running_costs
from .valuation import CENT, DepotValue, PositionValue

# Schluessel der Allokation ohne Zuordnung
CASH = "cash"
UNKNOWN = "unknown"
NO_LOOK_THROUGH = "no_look_through"
BONDS = "bonds"
TOP = 5
QUINTILES = 5

# Sektoren der Quellen -> Sektor wie bei yfinance fuer Aktien (das UI uebersetzt diese). Die ETFs
# melden ihre Sektoren anders: yfinance ``funds_data`` klein mit Unterstrich, iShares nach GICS,
# teils auf Deutsch. Unbekannte Bezeichnungen bleiben, wie sie sind.
SECTOR_KEYS = {
    "technology": "Technology",
    "information technology": "Technology",
    "informationstechnologie": "Technology",
    "it": "Technology",
    "healthcare": "Healthcare",
    "health care": "Healthcare",
    "gesundheitsversorgung": "Healthcare",
    "gesundheitswesen": "Healthcare",
    "financial services": "Financial Services",
    "financial_services": "Financial Services",
    "financials": "Financial Services",
    "finanzen": "Financial Services",
    "consumer cyclical": "Consumer Cyclical",
    "consumer_cyclical": "Consumer Cyclical",
    "consumer discretionary": "Consumer Cyclical",
    "zyklische konsumgüter": "Consumer Cyclical",
    "consumer defensive": "Consumer Defensive",
    "consumer_defensive": "Consumer Defensive",
    "consumer staples": "Consumer Defensive",
    "nichtzyklische konsumgüter": "Consumer Defensive",
    "basiskonsumgüter": "Consumer Defensive",
    "industrials": "Industrials",
    "industrie": "Industrials",
    "basic materials": "Basic Materials",
    "basic_materials": "Basic Materials",
    "materials": "Basic Materials",
    "materialien": "Basic Materials",
    "rohstoffe": "Basic Materials",
    "energy": "Energy",
    "energie": "Energy",
    "utilities": "Utilities",
    "versorger": "Utilities",
    "versorgungsbetriebe": "Utilities",
    "real estate": "Real Estate",
    "realestate": "Real Estate",
    "immobilien": "Real Estate",
    "communication services": "Communication Services",
    "communication_services": "Communication Services",
    "communication": "Communication Services",
    "kommunikation": "Communication Services",
    "kommunikationsdienste": "Communication Services",
    "cash and/or derivatives": CASH,
    "cash und/oder derivate": CASH,
}

# Laender der ETF-Stammdaten (iShares, auf Deutsch oder Englisch) -> ISO 3166, wie die ersten
# zwei Zeichen einer ISIN. Das UI zeigt die Namen; unbekannte Bezeichnungen bleiben.
COUNTRY_CODES = {
    "vereinigte staaten": "US",
    "united states": "US",
    "usa": "US",
    "deutschland": "DE",
    "germany": "DE",
    "japan": "JP",
    "vereinigtes königreich": "GB",
    "united kingdom": "GB",
    "frankreich": "FR",
    "france": "FR",
    "kanada": "CA",
    "canada": "CA",
    "schweiz": "CH",
    "switzerland": "CH",
    "niederlande": "NL",
    "netherlands": "NL",
    "australien": "AU",
    "australia": "AU",
    "china": "CN",
    "taiwan": "TW",
    "indien": "IN",
    "india": "IN",
    "südkorea": "KR",
    "korea": "KR",
    "korea (south)": "KR",
    "italien": "IT",
    "italy": "IT",
    "spanien": "ES",
    "spain": "ES",
    "schweden": "SE",
    "sweden": "SE",
    "dänemark": "DK",
    "denmark": "DK",
    "irland": "IE",
    "ireland": "IE",
    "belgien": "BE",
    "belgium": "BE",
    "finnland": "FI",
    "finland": "FI",
    "norwegen": "NO",
    "norway": "NO",
    "österreich": "AT",
    "austria": "AT",
    "hongkong": "HK",
    "hong kong": "HK",
    "singapur": "SG",
    "singapore": "SG",
    "brasilien": "BR",
    "brazil": "BR",
}


@dataclass(frozen=True)
class EtfData:
    """Was die Analyse aus den Stammdaten eines ETF braucht; Gewichte in Prozent."""

    as_of: date
    holdings: Fund
    ter: float | None = None
    currency: str | None = None  # Fondswaehrung
    sectors: Mapping[str, float] = field(default_factory=dict)
    countries: Mapping[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class BondData:
    terms: BondTerms
    cfi: str | None = None


@dataclass(frozen=True)
class AnalysisInput:
    value: DepotValue
    etfs: Mapping[str, EtfData] = field(default_factory=dict)
    bonds: Mapping[str, BondData] = field(default_factory=dict)
    # Composite je ISIN, auch fuer die Positionen der ETFs (Look-through-Score)
    composites: Mapping[str, float] = field(default_factory=dict)
    # Namen der Positionen der ETFs je ISIN, fuer die Konzentration
    names: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Slice:
    key: str
    value_eur: Decimal
    weight: float


@dataclass(frozen=True)
class Allocation:
    asset_class: list[Slice]
    currency: list[Slice]
    sector: list[Slice]
    country: list[Slice]


@dataclass(frozen=True)
class Title:
    isin: str
    name: str | None
    weight: float


@dataclass(frozen=True)
class Concentration:
    largest: Title | None
    top: list[Title]
    top_weight: float
    effective_positions: float | None
    lower_bound: bool


@dataclass(frozen=True)
class Quintile:
    quintile: int  # 1 = unterstes Fuenftel des Referenzuniversums, 5 = oberstes
    count: int
    weight: float  # Anteil am Wert der Aktien mit Perzentil


@dataclass(frozen=True)
class FundQuality:
    isin: str
    score: float | None
    covered: float
    lower_bound: bool


@dataclass(frozen=True)
class Quality:
    equity_eur: Decimal
    covered: float  # Anteil am Wert der Aktien mit Composite
    composite: float | None
    value_score: float | None
    quality_score: float | None
    value_traps: int
    quintiles: list[Quintile]
    funds: list[FundQuality]


@dataclass(frozen=True)
class Costs:
    etf_eur: Decimal
    covered: float  # Anteil am Wert der ETFs mit TER
    ter: float | None  # Prozent pro Jahr, wertgewichtet
    running_costs_eur: Decimal | None


@dataclass(frozen=True)
class BondPosition:
    isin: str
    value_eur: Decimal | None
    maturity: date | None
    ytm: float | None
    modified_duration: float | None
    accrued: float | None
    next_coupon: date | None
    special: str | None


@dataclass(frozen=True)
class MaturityYear:
    year: int
    value_eur: Decimal


@dataclass(frozen=True)
class Bonds:
    bond_eur: Decimal
    covered: float  # Anteil am Wert der Anleihen mit Rendite
    ytm: float | None
    modified_duration: float | None
    maturities: list[MaturityYear]
    positions: list[BondPosition]


@dataclass(frozen=True)
class DataQuality:
    positions: int
    valued: int
    look_through: float | None  # Anteil am Wert der ETFs, deren Positionen bekannt sind
    oldest_price: date | None
    oldest_score: date | None
    oldest_fund_data: date | None


@dataclass(frozen=True)
class DepotAnalysis:
    value_eur: Decimal | None
    allocation: Allocation
    concentration: Concentration
    quality: Quality
    costs: Costs
    bonds: Bonds
    data: DataQuality


def sector_key(label: str | None) -> str:
    if not label:
        return UNKNOWN
    return SECTOR_KEYS.get(label.strip().casefold(), label.strip())


def country_key(label: str | None) -> str:
    if not label:
        return UNKNOWN
    return COUNTRY_CODES.get(label.strip().casefold(), label.strip())


def _weight(part: Decimal, total: Decimal) -> float:
    return float(part / total) if total > 0 else 0.0


def _slices(values: Mapping[str, Decimal], total: Decimal) -> list[Slice]:
    """Absteigend nach Wert, bei Gleichstand nach Schluessel; Werte auf Cent."""
    ordered = sorted(values.items(), key=lambda item: (-item[1], item[0]))
    return [Slice(k, v.quantize(CENT), _weight(v, total)) for k, v in ordered if v != 0]


def _valued(value: DepotValue) -> list[tuple[PositionValue, Decimal]]:
    return [(p, p.value_eur) for p in value.positions if p.value_eur is not None]


def _asset_class(position: PositionValue) -> str:
    """Aus den Stammdaten; fehlen sie noch ("wird geprueft"), ist eine Position mit Score eine
    Aktie, denn Scores gibt es nur fuer Aktien."""
    if position.security:
        return position.security.asset_class
    return "equity" if position.score else UNKNOWN


def _spread(
    target: dict[str, Decimal],
    amount: Decimal,
    weights: Mapping[str, float],
    key: Callable[[str], str],
) -> None:
    """``amount`` nach Prozentgewichten verteilen; der Rest ohne Zuordnung, ueber 100 % skaliert."""
    positive = {label: w for label, w in weights.items() if w > 0}
    total = sum(positive.values())
    scale = 100 / total if total > 100 else 1.0
    for label, w in positive.items():
        target[key(label)] += amount * Decimal(str(w * scale / 100))
    rest = 1 - min(total, 100) / 100
    if rest > 0:
        target[UNKNOWN] += amount * Decimal(str(rest))


def _allocation(data: AnalysisInput, total: Decimal) -> Allocation:
    classes: dict[str, Decimal] = defaultdict(Decimal)
    currencies: dict[str, Decimal] = defaultdict(Decimal)
    sectors: dict[str, Decimal] = defaultdict(Decimal)
    countries: dict[str, Decimal] = defaultdict(Decimal)
    for position, amount in _valued(data.value):
        isin, kind = position.line.isin, _asset_class(position)
        classes[kind] += amount
        etf = data.etfs.get(isin) if kind == "etf" else None
        currency = (etf.currency if etf else None) or (
            position.security.currency if position.security else None
        )
        currencies[currency or (position.quote.currency if position.quote else UNKNOWN)] += amount
        if kind == "equity":
            sectors[sector_key(position.score.sector if position.score else None)] += amount
            countries[isin[:2]] += amount
        elif kind == "etf":
            if etf and etf.sectors:
                _spread(sectors, amount, etf.sectors, sector_key)
            else:
                sectors[NO_LOOK_THROUGH] += amount
            if etf and etf.countries:
                _spread(countries, amount, etf.countries, country_key)
            else:
                countries[NO_LOOK_THROUGH] += amount
        else:
            sectors[BONDS if kind == "bond" else UNKNOWN] += amount
            countries[isin[:2]] += amount
    cash = data.value.cash_eur
    if cash:
        for target in (classes, sectors, countries):
            target[CASH] += cash
        currencies["EUR"] += cash
    return Allocation(
        _slices(classes, total),
        _slices(currencies, total),
        _slices(sectors, total),
        _slices(countries, total),
    )


def _concentration(data: AnalysisInput, total: Decimal) -> Concentration:
    valued = _valued(data.value)
    direct: dict[str, float] = {}
    funds: list[tuple[float, Fund]] = []
    names: dict[str, str] = dict(data.names)
    unknown_fund = False
    for position, amount in valued:
        isin = position.line.isin
        if position.security:
            names[isin] = position.security.name
        if _asset_class(position) == "etf":
            etf = data.etfs.get(isin)
            if etf and etf.holdings.holdings:
                funds.append((_weight(amount, total), etf.holdings))
            else:
                unknown_fund = True
        else:
            direct[isin] = direct.get(isin, 0.0) + _weight(amount, total)
    exposure = look_through(direct, funds)
    ranked = sorted(exposure.weights.items(), key=lambda item: (-item[1], item[0]))
    top = [Title(isin, names.get(isin), weight) for isin, weight in ranked[:TOP]]
    invested = sum((amount for _, amount in valued), Decimal(0))
    squares = sum(_weight(amount, invested) ** 2 for _, amount in valued)
    return Concentration(
        largest=top[0] if top else None,
        top=top,
        top_weight=sum(t.weight for t in top),
        effective_positions=1 / squares if squares else None,
        lower_bound=exposure.lower_bound or unknown_fund,
    )


def _mean(pairs: Sequence[tuple[Decimal, float]]) -> float | None:
    weight = sum((w for w, _ in pairs), Decimal(0))
    if weight <= 0:
        return None
    return sum(float(w) * v for w, v in pairs) / float(weight)


def _quality(data: AnalysisInput) -> Quality:
    equities = [(p, a) for p, a in _valued(data.value) if _asset_class(p) == "equity"]
    equity_eur = sum((a for _, a in equities), Decimal(0))
    scores = [(p.score, a) for p, a in equities if p.score is not None]
    composite = [(a, s.composite_score) for s, a in scores if s.composite_score is not None]
    percentiles = [
        (s.composite_percentile, a) for s, a in scores if s.composite_percentile is not None
    ]
    with_percentile = sum((a for _, a in percentiles), Decimal(0))
    quintiles = []
    for q in range(1, QUINTILES + 1):
        members = [a for p, a in percentiles if max(1, math.ceil(p * QUINTILES)) == q]
        quintiles.append(
            Quintile(q, len(members), _weight(sum(members, Decimal(0)), with_percentile))
        )
    funds = [
        FundQuality(isin, result.score, result.covered, result.lower_bound)
        for isin, etf in sorted(data.etfs.items())
        if any(p.line.isin == isin for p in data.value.positions)
        for result in [look_through_score(etf.holdings, data.composites)]
    ]
    return Quality(
        equity_eur=equity_eur.quantize(CENT),
        covered=_weight(sum((a for a, _ in composite), Decimal(0)), equity_eur),
        composite=_mean(composite),
        value_score=_mean([(a, s.value_score) for s, a in scores if s.value_score is not None]),
        quality_score=_mean(
            [(a, s.quality_score) for s, a in scores if s.quality_score is not None]
        ),
        value_traps=sum(1 for s, _ in scores if s.value_trap_flag),
        quintiles=quintiles,
        funds=funds,
    )


def _costs(data: AnalysisInput) -> Costs:
    etfs = [(p, a) for p, a in _valued(data.value) if _asset_class(p) == "etf"]
    etf_eur = sum((a for _, a in etfs), Decimal(0))
    known = [
        (a, etf.ter)
        for p, a in etfs
        if (etf := data.etfs.get(p.line.isin)) is not None and etf.ter is not None
    ]
    costs = [running_costs(a, ter) for a, ter in known]
    return Costs(
        etf_eur=etf_eur.quantize(CENT),
        covered=_weight(sum((a for a, _ in known), Decimal(0)), etf_eur),
        ter=_mean(known),
        running_costs_eur=sum((c for c in costs if c is not None), Decimal(0)) if known else None,
    )


def _bonds(data: AnalysisInput) -> Bonds:
    positions: list[BondPosition] = []
    weighted_ytm: list[tuple[Decimal, float]] = []
    weighted_duration: list[tuple[Decimal, float]] = []
    maturities: dict[int, Decimal] = defaultdict(Decimal)
    bond_eur = Decimal(0)
    for position in data.value.positions:
        if _asset_class(position) != "bond":
            continue
        isin, amount = position.line.isin, position.value_eur
        bond = data.bonds.get(isin)
        figures = (
            bond_figures(
                bond.terms,
                clean_price=float(position.quote.close),
                on=position.quote.trade_date,
                cfi=bond.cfi,
            )
            if bond and position.quote and position.quote.percent_of_par
            else None
        )
        if amount is not None:
            bond_eur += amount
            if bond and bond.terms.maturity:
                maturities[bond.terms.maturity.year] += amount
            if figures and figures.ytm is not None and figures.modified_duration is not None:
                weighted_ytm.append((amount, figures.ytm))
                weighted_duration.append((amount, figures.modified_duration))
        positions.append(
            BondPosition(
                isin=isin,
                value_eur=amount,
                maturity=bond.terms.maturity if bond else None,
                ytm=figures.ytm if figures else None,
                modified_duration=figures.modified_duration if figures else None,
                accrued=figures.accrued if figures else None,
                next_coupon=figures.next_coupon if figures else None,
                special=figures.special if figures else None,
            )
        )
    return Bonds(
        bond_eur=bond_eur.quantize(CENT),
        covered=_weight(sum((a for a, _ in weighted_ytm), Decimal(0)), bond_eur),
        ytm=_mean(weighted_ytm),
        modified_duration=_mean(weighted_duration),
        maturities=[MaturityYear(y, v.quantize(CENT)) for y, v in sorted(maturities.items())],
        positions=positions,
    )


def _data_quality(data: AnalysisInput) -> DataQuality:
    value = data.value
    valued = _valued(value)
    etfs = [(p, a) for p, a in valued if _asset_class(p) == "etf"]
    etf_eur = sum((a for _, a in etfs), Decimal(0))
    seen = sum(
        (a for p, a in etfs if (e := data.etfs.get(p.line.isin)) and e.holdings.holdings),
        Decimal(0),
    )
    prices = [p.quote.trade_date for p, _ in valued if p.quote]
    scores = [p.score.as_of for p in value.positions if p.score]
    held = {p.line.isin for p in value.positions}
    fund_dates = [etf.as_of for isin, etf in data.etfs.items() if isin in held]
    return DataQuality(
        positions=len(value.positions),
        valued=len(valued),
        look_through=_weight(seen, etf_eur) if etfs else None,
        oldest_price=min(prices) if prices else None,
        oldest_score=min(scores) if scores else None,
        oldest_fund_data=min(fund_dates) if fund_dates else None,
    )


def analyze(data: AnalysisInput) -> DepotAnalysis:
    """Analyse des Depots; eine Beobachtungsliste hat keinen Wert, also leere Bereiche."""
    total = data.value.value_eur or Decimal(0)
    return DepotAnalysis(
        value_eur=data.value.value_eur,
        allocation=_allocation(data, total),
        concentration=_concentration(data, total),
        quality=_quality(data),
        costs=_costs(data),
        bonds=_bonds(data),
        data=_data_quality(data),
    )
