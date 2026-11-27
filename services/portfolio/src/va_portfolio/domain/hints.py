"""Hinweise am Depot (D5.1, HIN-01, 02, 04; docs/architecture/depot/analyse.md, Hinweise).

Regelbasierte Beobachtungen aus Analyse und Bewertung, nie eine Anlageempfehlung: Jeder Hinweis
nennt Messwert, Schwelle und Datenstand, der Katalog Begruendung und Ansatzpunkt zum Pruefen.
Kein Text sagt "kaufen", "verkaufen" oder nennt ein Kursziel (ein Test prueft den Katalog).

- Schluessel: Regel und Gegenstand, ``HIN-K01:<ISIN>``, ``HIN-A02:depot``, ``HIN-K03:<Sektor>``.
- Anteile beziehen sich wie in der Analyse auf den Wert des Depots.
- HIN-K01 und HIN-K02 zaehlen Aktien, direkt und in den ETFs; Anleihen decken HIN-B03 und
  HIN-K06 ab. HIN-K04 kennt ``XS`` (internationale Anleihen) nicht als Land, HIN-K05 eine
  unbekannte Waehrung nicht als Fremdwaehrung.
- HIN-K06 nur fuer Emittenten mit mindestens zwei Wertpapieren (sonst wie HIN-K01), zusammengefuehrt
  ueber die LEI; HIN-B03 nur mit mindestens zwei Anleihen.
- HIN-Q03 (seit D5.2) vergleicht mit dem vorherigen Bewertungslauf, der die Aktie kannte.
- HIN-A01 (seit D5.3) vergleicht jede Anlageklasse mit der Zielallokation, sofern es eine gibt;
  eine Klasse ohne Ziel zaehlt mit 0 %.
- Noch nicht gerechnet: HIN-N01/N02 (News, D6), HIN-D02 (Bank, D8). Sie stehen schon im Katalog.
- Kenntnisnahme (D5.3, HIN-05, ``still_acknowledged``): Ein Hinweis bleibt zur Kenntnis genommen,
  bis er schwerer wird oder sich sein Messwert um die Spanne der Regel (``ACK_SPANS``)
  verschlechtert; ohne Messwert, solange er besteht.
- Lebenszyklus (D5.2, HIN-03, ``track``): gegen den vorherigen Lauf neu, besteht oder erledigt;
  ein erledigter Hinweis steht einmal da und faellt im naechsten Lauf weg.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from itertools import combinations
from typing import TYPE_CHECKING, Literal

from .funds import look_through, overlap

if TYPE_CHECKING:
    from va_contracts.portfolio import HintParamsV1

    from .analysis import AnalysisInput, DepotAnalysis, Slice
    from .valuation import PositionValue, Score

Severity = Literal["info", "warning", "critical"]
Status = Literal["new", "existing", "resolved"]
SEVERITY_ORDER = {"critical": 0, "warning": 1, "info": 2}
DEPOT = "depot"
# Schluessel der Allokation, die keinen Sektor oder kein Land bezeichnen
UNASSIGNED = {"cash", "bonds", "unknown", "no_look_through"}
# XS: ISIN internationaler Anleihen (Eurobonds), kein Land
NO_COUNTRY = UNASSIGNED | {"XS"}
TOP = 5


@dataclass(frozen=True)
class HintRule:
    """Ein Eintrag im Katalog, wie ``FACTOR_INFO`` fuer die Faktoren."""

    id: str
    group: str
    title: str
    reason: str
    approach: str


def _rule(rule_id: str, group: str, title: str, reason: str, approach: str) -> HintRule:
    return HintRule(rule_id, group, title, reason, approach)


HINT_CATALOG: dict[str, HintRule] = {
    r.id: r
    for r in (
        _rule(
            "HIN-K01",
            "Konzentration",
            "Großer Einzeltitel",
            "Ein einzelnes Unternehmen trägt einen großen Teil des Depots, direkt und über ETFs.",
            "Gewicht und Doppelung über ETFs prüfen.",
        ),
        _rule(
            "HIN-K02",
            "Konzentration",
            "Fünf Titel tragen das Depot",
            "Die fünf größten Einzeltitel machen zusammen einen großen Teil des Werts aus.",
            "Streuung prüfen.",
        ),
        _rule(
            "HIN-K03",
            "Konzentration",
            "Großer Sektor",
            "Ein Sektor macht mit Durchschau durch die ETFs einen großen Teil aus.",
            "Abhängigkeit von einer Branche prüfen.",
        ),
        _rule(
            "HIN-K04",
            "Konzentration",
            "Großes Land",
            "Ein Land macht mit Durchschau einen großen Teil aus.",
            "Heimatmarkt-Übergewicht prüfen.",
        ),
        _rule(
            "HIN-K05",
            "Konzentration",
            "Viel Fremdwährung",
            "Ein großer Teil des Werts lautet nicht auf Euro.",
            "Währungsrisiko prüfen.",
        ),
        _rule(
            "HIN-K06",
            "Konzentration",
            "Großer Emittent",
            "Aktien und Anleihen desselben Emittenten machen zusammen einen großen Teil aus.",
            "Emittentenrisiko prüfen.",
        ),
        _rule(
            "HIN-A01",
            "Allokation",
            "Abweichung von der Zielallokation",
            "Eine Anlageklasse weicht von der eingestellten Zielallokation ab.",
            "Zielallokation und Gewichte prüfen.",
        ),
        _rule(
            "HIN-A02",
            "Allokation",
            "Viel Kasse",
            "Ein großer Teil des Depots liegt als Guthaben auf dem Verrechnungskonto.",
            "Liquiditätsbedarf prüfen.",
        ),
        _rule(
            "HIN-Q01",
            "Qualität",
            "Verdacht auf eine Value-Falle",
            "Günstig bewertet, aber mit schwacher Qualität: solche Titel sind oft zu Recht billig.",
            "Geschäftsbericht und Ursache der niedrigen Quality prüfen.",
        ),
        _rule(
            "HIN-Q02",
            "Qualität",
            "Unteres Fünftel",
            "Der Composite liegt im unteren Fünftel von DAX/MDAX.",
            "Kennzahlen im Titel-Detail prüfen.",
        ),
        _rule(
            "HIN-Q03",
            "Qualität",
            "Composite-Perzentil gefallen",
            "Der Titel steht deutlich schlechter da als im vorherigen Bewertungslauf.",
            "Prüfen, welche Faktoren sich verschlechtert haben.",
        ),
        _rule(
            "HIN-Q04",
            "Qualität",
            "Niedrige Quality",
            "Der Quality-Score ist niedrig: schwache Profitabilität oder hohe Verschuldung.",
            "Profitabilität und Verschuldung prüfen.",
        ),
        _rule(
            "HIN-Q05",
            "Qualität",
            "Keine Bewertung möglich",
            "Für den Titel fehlen Kennzahlen, etwa Quality bei Banken, oder noch jeder Score.",
            "Qualitativ beurteilen.",
        ),
        _rule(
            "HIN-Q06",
            "Qualität",
            "Vergleich eingeschränkt",
            "Der Titel steht nicht im Ranking und ist nur in DAX/MDAX eingeordnet.",
            "Den Score nur als grobe Einordnung lesen.",
        ),
        _rule(
            "HIN-E01",
            "ETFs",
            "Hohe laufende Kosten",
            "Die TER des ETF liegt über der Schwelle.",
            "Kosten prüfen.",
        ),
        _rule(
            "HIN-E02",
            "ETFs",
            "Zwei ETFs überschneiden sich",
            "Zwei ETFs halten zu einem großen Teil dieselben Titel.",
            "Doppelte Abdeckung prüfen.",
        ),
        _rule(
            "HIN-E03",
            "ETFs",
            "Kleiner Fonds",
            "Das Fondsvolumen ist klein; kleine Fonds werden eher geschlossen.",
            "Schließungsrisiko prüfen.",
        ),
        _rule(
            "HIN-B01",
            "Anleihen",
            "Bald fällig",
            "Die Anleihe wird bald zurückgezahlt.",
            "Wiederanlage planen.",
        ),
        _rule(
            "HIN-B02",
            "Anleihen",
            "Niedriger Kurs",
            "Der Kurs liegt deutlich unter dem Nennwert; der Markt zweifelt womöglich an der Bonität.",
            "Bonität des Emittenten prüfen.",
        ),
        _rule(
            "HIN-B03",
            "Anleihen",
            "Ein Fälligkeitsjahr überwiegt",
            "Ein großer Teil der Anleihen wird im selben Jahr fällig.",
            "Laufzeitenstruktur prüfen.",
        ),
        _rule(
            "HIN-N01",
            "News",
            "Ad-hoc-Mitteilung",
            "Zu einer Position gibt es eine neue Ad-hoc-Mitteilung.",
            "Mitteilung lesen.",
        ),
        _rule(
            "HIN-N02",
            "News",
            "Eigengeschäfte von Führungskräften",
            "Führungskräfte haben Geschäfte in der Aktie gemeldet.",
            "Meldung lesen.",
        ),
        _rule(
            "HIN-D01",
            "Datenlage",
            "Kurs fehlt oder ist alt",
            "Für die Position gibt es keinen aktuellen Kurs; der Depotwert ist unvollständig.",
            "Prüfen, ob das Wertpapier noch gehandelt wird.",
        ),
        _rule(
            "HIN-D02",
            "Datenlage",
            "Bankstand alt",
            "Der Bestand von der Bank ist älter als die Schwelle.",
            "Bestand neu abrufen.",
        ),
        _rule(
            "HIN-D03",
            "Datenlage",
            "Wertpapier nicht erkannt",
            "Zur ISIN gibt es noch keine Stammdaten.",
            "ISIN prüfen.",
        ),
    )
}


@dataclass(frozen=True)
class Hint:
    """Ein Hinweis: Regel, Gegenstand, Schwere, Messwert, Schwelle und Datenstand."""

    rule: str
    subject: str
    severity: Severity
    measured: float | None = None
    threshold: float | None = None
    as_of: date | None = None

    @property
    def key(self) -> str:
        return f"{self.rule}:{self.subject}"


@dataclass(frozen=True)
class HintInput:
    data: AnalysisInput
    analysis: DepotAnalysis
    today: date
    leis: Mapping[str, str] = field(default_factory=dict)  # ISIN -> LEI (FIRDS)
    # D5.2: je ISIN die Scores des vorherigen Bewertungslaufs, der sie kannte (HIN-Q03)
    previous_scores: Mapping[str, Score] = field(default_factory=dict)
    # D5.3: Zielallokation je Anlageklasse (Anteil), leer ohne Ziel (HIN-A01)
    target: Mapping[str, float] = field(default_factory=dict)
    # ISIN -> Fondsvolumen in Mio. EUR, nur aus Anbieterdateien (HIN-E03)
    fund_sizes: Mapping[str, float] = field(default_factory=dict)


def _kind(position: PositionValue) -> str:
    if position.security:
        return position.security.asset_class
    return "equity" if position.score else "unknown"


def _valued(data: AnalysisInput) -> list[tuple[PositionValue, Decimal]]:
    return [(p, p.value_eur) for p in data.value.positions if p.value_eur is not None]


def _share(amount: Decimal, total: Decimal) -> float:
    return float(amount / total) if total > 0 else 0.0


def _concentration(source: HintInput, params: HintParamsV1) -> Iterable[Hint]:
    data, as_of = source.data, source.analysis.data.oldest_price
    total = data.value.value_eur or Decimal(0)
    direct: dict[str, float] = {}
    funds = []
    for position, amount in _valued(data):
        kind = _kind(position)
        if kind == "equity":
            direct[position.line.isin] = direct.get(position.line.isin, 0.0) + _share(amount, total)
        elif kind == "etf" and (etf := data.etfs.get(position.line.isin)) is not None:
            funds.append((_share(amount, total), etf.holdings))
    titles = look_through(direct, funds).weights
    for isin, weight in sorted(titles.items()):
        if weight > params.k01_critical:
            yield Hint("HIN-K01", isin, "critical", weight, params.k01_critical, as_of)
        elif weight > params.k01_warning:
            yield Hint("HIN-K01", isin, "warning", weight, params.k01_warning, as_of)
    # Wie HIN-K01: die fuenf groessten Aktien, nicht die Anleihen
    top = sum(sorted(titles.values(), reverse=True)[:TOP])
    if top > params.k02_top5:
        yield Hint("HIN-K02", DEPOT, "info", top, params.k02_top5, as_of)
    allocation = source.analysis.allocation
    yield from _slices("HIN-K03", allocation.sector, params.k03_sector, "warning", as_of)
    yield from _slices(
        "HIN-K04", allocation.country, params.k04_country, "info", as_of, skip=NO_COUNTRY
    )
    # Eine unbekannte Waehrung ist keine Fremdwaehrung
    foreign = sum(s.weight for s in allocation.currency if s.key not in ("EUR", "unknown"))
    if foreign > params.k05_foreign_currency:
        yield Hint("HIN-K05", DEPOT, "info", foreign, params.k05_foreign_currency, as_of)
    issuers: dict[str, list[float]] = defaultdict(list)
    for position, amount in _valued(data):
        if (lei := source.leis.get(position.line.isin)) and _kind(position) in ("equity", "bond"):
            issuers[lei].append(_share(amount, total))
    for lei, weights in sorted(issuers.items()):
        if len(weights) >= 2 and sum(weights) > params.k06_issuer:
            yield Hint("HIN-K06", lei, "warning", sum(weights), params.k06_issuer, as_of)


def _slices(
    rule: str,
    slices: Iterable[Slice],
    threshold: float,
    severity: Severity,
    as_of: date | None,
    *,
    skip: set[str] = UNASSIGNED,
) -> Iterable[Hint]:
    for s in slices:
        if s.key not in skip and s.weight > threshold:
            yield Hint(rule, s.key, severity, s.weight, threshold, as_of)


def _allocation(source: HintInput, params: HintParamsV1) -> Iterable[Hint]:
    as_of = source.analysis.data.oldest_price
    if source.target and source.data.value.value_eur is not None:
        actual = {s.key: s.weight for s in source.analysis.allocation.asset_class}
        for kind in sorted(set(source.target) | (set(actual) - {"unknown"})):
            deviation = round(abs(actual.get(kind, 0.0) - source.target.get(kind, 0.0)), 9)
            if deviation > params.a01_deviation:
                yield Hint("HIN-A01", kind, "info", deviation, params.a01_deviation, as_of)
    cash = next((s.weight for s in source.analysis.allocation.asset_class if s.key == "cash"), 0.0)
    if cash > params.a02_cash:
        yield Hint(
            "HIN-A02", DEPOT, "info", cash, params.a02_cash, source.analysis.data.oldest_price
        )


def _quality(source: HintInput, params: HintParamsV1) -> Iterable[Hint]:
    for position in source.data.value.positions:
        if _kind(position) != "equity":
            continue
        isin, score = position.line.isin, position.score
        if score is None:
            yield Hint("HIN-Q05", isin, "info")
            continue
        as_of = score.as_of
        if score.value_trap_flag:
            yield Hint("HIN-Q01", isin, "warning", as_of=as_of)
        p = score.composite_percentile
        if p is not None and p <= params.q02_percentile:
            yield Hint("HIN-Q02", isin, "info", p, params.q02_percentile, as_of)
        before = source.previous_scores.get(isin)
        if p is not None and before is not None and before.composite_percentile is not None:
            # Gerundet: 0,7 - 0,5 ergibt in Gleitkomma knapp unter 0,2
            drop = round(before.composite_percentile - p, 9)
            if drop >= params.q03_drop:
                yield Hint("HIN-Q03", isin, "info", drop, params.q03_drop, as_of)
        q = score.quality_score
        if q is not None and q <= params.q04_quality:
            yield Hint("HIN-Q04", isin, "info", q, params.q04_quality, as_of)
        if score.reason is not None:
            yield Hint("HIN-Q05", isin, "info", as_of=as_of)
        if score.reference in ("outside", "below_size_filter"):
            yield Hint("HIN-Q06", isin, "info", as_of=as_of)


def _etfs(source: HintInput, params: HintParamsV1) -> Iterable[Hint]:
    held = sorted(
        {p.line.isin for p in source.data.value.positions if _kind(p) == "etf"}
        & set(source.data.etfs)
    )
    for isin in held:
        etf = source.data.etfs[isin]
        if etf.ter is not None and etf.ter > params.e01_ter:
            yield Hint("HIN-E01", isin, "info", etf.ter, params.e01_ter, etf.as_of)
        size = source.fund_sizes.get(isin)
        if size is not None and size < params.e03_fund_size:
            yield Hint("HIN-E03", isin, "info", size, params.e03_fund_size, etf.as_of)
    for a, b in combinations(held, 2):
        first, second = source.data.etfs[a], source.data.etfs[b]
        share, _ = overlap(first.holdings, second.holdings)
        if share >= params.e02_overlap:
            as_of = min(first.as_of, second.as_of)
            yield Hint("HIN-E02", f"{a}+{b}", "info", share, params.e02_overlap, as_of)


def _bonds(source: HintInput, params: HintParamsV1) -> Iterable[Hint]:
    bonds = source.analysis.bonds
    soon = source.today + timedelta(days=params.b01_days)
    for position in source.data.value.positions:
        if _kind(position) != "bond":
            continue
        isin = position.line.isin
        bond = source.data.bonds.get(isin)
        maturity = bond.terms.maturity if bond else None
        if maturity is not None and source.today <= maturity <= soon:
            days = float((maturity - source.today).days)
            yield Hint("HIN-B01", isin, "info", days, float(params.b01_days), maturity)
        quote = position.quote
        if quote is not None and quote.percent_of_par and float(quote.close) < params.b02_price:
            yield Hint(
                "HIN-B02", isin, "warning", float(quote.close), params.b02_price, quote.trade_date
            )
    if len(bonds.positions) >= 2 and bonds.bond_eur > 0:
        for year in bonds.maturities:
            share = _share(year.value_eur, bonds.bond_eur)
            if share > params.b03_maturity_year:
                yield Hint("HIN-B03", str(year.year), "info", share, params.b03_maturity_year)


def _business_days(start: date, end: date) -> int:
    """Handelstage (Montag bis Freitag) nach ``start`` bis einschliesslich ``end``."""
    days, day = 0, start
    while day < end:
        day += timedelta(days=1)
        days += day.weekday() < 5
    return days


def _data(source: HintInput, params: HintParamsV1) -> Iterable[Hint]:
    for position in source.data.value.positions:
        isin = position.line.isin
        if position.pending:
            yield Hint("HIN-D03", isin, "warning")
        quote = position.quote
        if position.missing == "price":
            yield Hint("HIN-D01", isin, "warning")
        elif quote is not None:
            age = _business_days(quote.trade_date, source.today)
            if age > params.d01_trading_days:
                yield Hint(
                    "HIN-D01",
                    isin,
                    "warning",
                    float(age),
                    float(params.d01_trading_days),
                    quote.trade_date,
                )


RULES: tuple[Callable[[HintInput, HintParamsV1], Iterable[Hint]], ...] = (
    _concentration,
    _allocation,
    _quality,
    _etfs,
    _bonds,
    _data,
)


def evaluate(source: HintInput, params: HintParamsV1) -> list[Hint]:
    """Die Hinweise des Depots, kritische zuerst, dann nach Regel und Gegenstand; abgeschaltete
    Regeln fehlen."""
    disabled = set(params.disabled)
    hints = [h for rule in RULES for h in rule(source, params) if h.rule not in disabled]
    return sorted(hints, key=lambda h: (SEVERITY_ORDER[h.severity], h.rule, h.subject))


@dataclass(frozen=True)
class TrackedHint:
    """Ein Hinweis mit Status gegen den vorherigen Lauf (HIN-03)."""

    hint: Hint
    status: Status


def track(previous: Sequence[TrackedHint], current: Sequence[Hint]) -> list[TrackedHint]:
    """Neu, besteht (die Schwere kann sich aendern) oder erledigt; erledigte zuletzt."""
    before = {t.hint.key: t for t in previous if t.status != "resolved"}
    tracked = [TrackedHint(h, "existing" if h.key in before else "new") for h in current]
    now = {h.key for h in current}
    tracked += [
        TrackedHint(t.hint, "resolved") for key, t in sorted(before.items()) if key not in now
    ]
    return tracked


# Was einen neuen Lauf ausloest (D5.2, ANA-10); "request": erster Abruf ohne Lauf
# D5.3: "settings" nach neuen Schwellen oder neuer Zielallokation
TRIGGERS = ("holdings", "prices", "scores", "securities", "request", "settings")


@dataclass(frozen=True)
class StoredSettings:
    """D5.3: Schwellen und Zielallokation eines Depots, je mit Version (0: Standard bzw. ohne)."""

    hint_params: Mapping[str, object] = field(default_factory=dict)
    hint_params_version: int = 0
    target: Mapping[str, float] = field(default_factory=dict)
    target_version: int = 0


@dataclass(frozen=True)
class StoredRun:
    """Ein gespeicherter Lauf der Analyse mit seinen Hinweisen (``portfolio.analysis_run``)."""

    id: int
    depot_id: int
    version: int
    fingerprint: str
    computed_at: datetime
    hints: list[TrackedHint] = field(default_factory=list)


# D5.3 (HIN-05): Richtung und Spanne, um die sich ein Messwert verschlechtern darf, bevor ein zur
# Kenntnis genommener Hinweis wieder erscheint. Ohne Eintrag: nur, wenn er schwerer wird.
ACK_SPANS: dict[str, tuple[Literal["up", "down"], float]] = {
    "HIN-K01": ("up", 0.05),
    "HIN-K02": ("up", 0.05),
    "HIN-K03": ("up", 0.05),
    "HIN-K04": ("up", 0.05),
    "HIN-K05": ("up", 0.05),
    "HIN-K06": ("up", 0.05),
    "HIN-A01": ("up", 0.05),
    "HIN-A02": ("up", 0.05),
    "HIN-Q02": ("down", 0.10),
    "HIN-Q03": ("up", 0.10),
    "HIN-Q04": ("down", 0.05),
    "HIN-E01": ("up", 0.10),
    "HIN-E02": ("up", 0.10),
    "HIN-E03": ("down", 20.0),
    "HIN-B02": ("down", 5.0),
    "HIN-B03": ("up", 0.10),
    "HIN-D01": ("up", 5.0),
}


@dataclass(frozen=True)
class Ack:
    """Ein zur Kenntnis genommener Hinweis: Messwert und Schwere in diesem Moment."""

    key: str
    measured: float | None
    severity: Severity
    at: datetime
    # der juengste Lauf beim Zur-Kenntnis-Nehmen; erscheint der Hinweis danach neu (nach dem
    # Erledigen), gilt die Kenntnisnahme nicht mehr
    run_id: int = 0


@dataclass(frozen=True)
class SettingsVersion:
    """D5.3: eine gespeicherte Version der Schwellen oder der Zielallokation (Datenexport)."""

    version: int
    values: Mapping[str, object]
    created_at: datetime


@dataclass(frozen=True)
class SettingsHistory:
    """D5.3: alle Versionen der Schwellen und Ziele eines Depots und alle Kenntnisnahmen."""

    hint_params: list[SettingsVersion] = field(default_factory=list)
    targets: list[SettingsVersion] = field(default_factory=list)
    acks: list[Ack] = field(default_factory=list)


def still_acknowledged(hint: Hint, ack: Ack) -> bool:
    """``True``, solange der Hinweis nicht schwerer ist und sich nicht um die Spanne verschlechtert hat."""
    if SEVERITY_ORDER[hint.severity] < SEVERITY_ORDER[ack.severity]:
        return False
    span = ACK_SPANS.get(hint.rule)
    if span is None or hint.measured is None or ack.measured is None:
        return True
    direction, width = span
    change = hint.measured - ack.measured if direction == "up" else ack.measured - hint.measured
    return round(change, 9) <= width
