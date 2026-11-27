"""Kennzahlen eines Titels als reine Funktionen (P1.3).

Keine Ein-/Ausgabe, kein Provider: Der Abruf (Adapter
``va_market_data.adapters.yahoo``) liest die Zahlen aus und uebergibt sie als ``StatementFigures`` und
``MarketFigures``. Fehlt ein Wert, ist er ``None``; jede Kennzahl, die ihn braucht, auch.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np

# Zeitreihen ueber die letzten fuenf Geschaeftsjahre, davon muessen vier vorliegen
HISTORY_YEARS = 5
MIN_HISTORY = max(2, HISTORY_YEARS - 1)
# Effektive Steuerquote begrenzen: Verlustjahre und Einmaleffekte sonst als Ausreisser
MAX_TAX_RATE = 0.6
# Netto-Emission (F2.2): Abstand der beiden Zeitpunkte, Fenster der Mediane und hoechstes Alter
# der juengsten Aktienanzahl
ISSUANCE_LAG_DAYS = 365
ISSUANCE_WINDOW_DAYS = 30
ISSUANCE_MAX_AGE_DAYS = 120


@dataclass(frozen=True)
class FiscalYear:
    """Posten eines Geschaeftsjahres in Berichtswaehrung (F2.1, ADR-0011).

    Ueber GuV, Bilanz und Cashflow am selben Stichtag ausgerichtet, damit Vorjahresvergleiche
    dieselben Jahre vergleichen. ``None`` heisst: Der Posten fehlt in diesem Jahr.
    """

    net_income: float | None = None
    revenue: float | None = None
    gross_profit: float | None = None
    cost_of_revenue: float | None = None
    total_assets: float | None = None
    long_term_debt: float | None = None
    current_assets: float | None = None
    current_liabilities: float | None = None
    shares: float | None = None
    operating_cash_flow: float | None = None


@dataclass(frozen=True)
class StatementFigures:
    """Jahresabschluss in Berichtswaehrung: juengste Werte und Reihen (juengstes Jahr zuerst).

    Die Reihen enthalten einen Wert je Geschaeftsjahr, ``None`` fuer ein fehlendes. Welche
    Jahre zaehlen (die letzten ``HISTORY_YEARS``, davon mindestens ``MIN_HISTORY``
    gueltige), entscheidet die Domain. ``capex`` ist wie bei Yahoo negativ, ``buybacks``
    ebenso.
    """

    revenue: float | None = None
    ebit: float | None = None
    ebitda: float | None = None
    gross_profit: float | None = None
    operating_income: float | None = None
    net_income: float | None = None
    pretax_income: float | None = None
    tax_expense: float | None = None
    total_assets: float | None = None
    total_equity: float | None = None
    total_debt: float | None = None
    cash: float | None = None
    fcf: float | None = None
    operating_cash_flow: float | None = None
    capex: float | None = None
    buybacks: float | None = None
    revenue_history: Sequence[float | None] = ()
    eps_history: Sequence[float | None] = ()
    net_income_history: Sequence[float | None] = ()
    ebit_history: Sequence[float | None] = ()  # F3.1, juengstes Jahr zuerst
    # Geschaeftsjahre nach Stichtag, juengstes zuerst (F2.1: F-Score, Accruals, CFO/Bilanzsumme)
    years: Sequence[FiscalYear] = ()


@dataclass(frozen=True)
class MarketFigures:
    """Marktdaten in Handelswaehrung, wie der Provider sie liefert."""

    market_cap: float | None = None
    enterprise_value: float | None = None
    trailing_pe: float | None = None
    price_to_book: float | None = None
    dividend_yield: float | None = None  # dezimal, 0.03 = 3 %


@dataclass(frozen=True)
class ShareHistory:
    """Aktienanzahl und Splits eines Titels je Tag (F2.2, ADR-0011).

    ``counts`` ist roh, wie Yahoo sie liefert: Am Tag eines 2:1-Splits verdoppelt sie sich.
    ``splits`` sind die Verhaeltnisse aus der Kurshistorie (2.0 = 2:1, 0.1 = 1:10), ``as_of``
    der Tag des Abrufs.
    """

    counts: Mapping[date, float]
    splits: Mapping[date, float]
    as_of: date


@dataclass(frozen=True)
class Metrics:
    """Kennzahlen eines Titels. Value-Multiples in Handelswaehrung, Quality waehrungsfrei."""

    enterprise_value: float | None
    ev_ebit: float | None
    pe_ratio: float | None
    pb_ratio: float | None
    p_fcf: float | None
    dividend_yield: float | None
    buyback_yield: float | None
    shareholder_yield: float | None
    net_share_issuance: float | None
    nopat_normalized: float | None
    roic: float | None
    roa: float | None
    fcf_margin: float | None
    gross_margin: float | None
    operating_margin: float | None
    net_debt_ebitda: float | None
    debt_to_equity: float | None
    earnings_stability: float | None
    f_score: int | None
    operating_accruals: float | None
    cfo_assets: float | None
    revenue_growth_5y: float | None
    eps_growth_5y: float | None


def safe_div(num: float | None, den: float | None) -> float | None:
    """Quotient oder ``None``: bei fehlendem Wert, Nenner 0 und Ueberlauf (inf)."""
    try:
        if num is None or den is None:
            return None
        nv, dv = float(num), float(den)
        if not np.isfinite(nv) or not np.isfinite(dv) or dv == 0:
            return None
        result = nv / dv
        # Float-Division laeuft bei winzigem Nenner ueber (inf) statt zu werfen
        return result if np.isfinite(result) else None
    except TypeError, ValueError, ZeroDivisionError:
        return None


def cagr(values: Sequence[float]) -> float | None:
    """Jaehrliche Wachstumsrate aus einer Reihe (juengstes Element zuerst).

    ``None`` bei weniger als zwei Werten, Vorzeichenwechsel und Ueberlauf.
    """
    if len(values) < 2:
        return None
    # safe_div: None bei 0 und bei Ueberlauf (aeltester Wert fast 0 -> inf)
    ratio = safe_div(values[0], values[-1])
    if ratio is None or ratio <= 0:
        return None
    years = len(values) - 1
    return float(ratio ** (1.0 / years) - 1.0)


def roic(
    *,
    ebit: float | None,
    equity: float | None,
    debt: float | None,
    pretax: float | None,
    tax: float | None,
    default_tax_rate: float,
) -> float | None:
    """ROIC = NOPAT / investiertes Kapital, mit effektiver Steuerquote wenn moeglich."""
    if ebit is None or equity is None:
        return None
    nopat = ebit * (1.0 - effective_tax_rate(pretax, tax, default_tax_rate))
    invested = equity + (debt or 0.0)
    return safe_div(nopat, invested)


def effective_tax_rate(pretax: float | None, tax: float | None, default_tax_rate: float) -> float:
    """Steuerquote des juengsten Jahres, begrenzt auf [0, ``MAX_TAX_RATE``]; ohne positiven
    Vorsteuergewinn ``default_tax_rate``."""
    if pretax and pretax > 0 and tax is not None and tax >= 0:
        return min(MAX_TAX_RATE, max(0.0, tax / pretax))
    return default_tax_rate


def nopat_normalized(
    ebit_history: Sequence[float | None],
    *,
    pretax: float | None,
    tax: float | None,
    fx: float | None,
    default_tax_rate: float,
) -> float | None:
    """Grundlage des Ertragskraftwerts (F3.1, ADR-0011, Punkt 6): Mittelwert der juengsten
    EBIT-Jahre (wie die Gewinnstabilitaet: bis zu fuenf, davon mindestens vier) nach der
    effektiven Steuerquote, in Handelswaehrung. Verluste bleiben negativ."""
    values = _recent(ebit_history)
    if values is None or fx is None:
        return None
    mean = sum(values) / len(values)
    return mean * (1.0 - effective_tax_rate(pretax, tax, default_tax_rate)) * fx


def _recent(history: Sequence[float | None]) -> list[float] | None:
    """Gueltige Werte der letzten ``HISTORY_YEARS`` Jahre, ``None`` bei zu wenigen."""
    values = [v for v in history[:HISTORY_YEARS] if v is not None and math.isfinite(v)]
    return values if len(values) >= MIN_HISTORY else None


def earnings_stability(net_income: Sequence[float | None]) -> float | None:
    """1 - min(Variationskoeffizient, 1) des Jahresueberschusses; hoeher = stabiler.

    Ueber die letzten ``HISTORY_YEARS`` Jahre, davon mindestens ``MIN_HISTORY`` gueltige.
    """
    values = _recent(net_income)
    if values is None:
        return None
    arr = np.array(values, dtype=float)
    mean_abs = float(np.mean(np.abs(arr)))
    if mean_abs <= 0:
        return None
    cv = float(np.std(arr) / mean_abs)
    return max(0.0, 1.0 - min(cv, 1.0))


# --- F2.1 (ADR-0011): Bilanzqualitaet ---------------------------------------------------------

F_SCORE_SIGNALS = (
    "roa_positive",
    "cfo_positive",
    "roa_up",
    "cfo_above_net_income",
    "leverage_down",
    "liquidity_up",
    "no_new_shares",
    "margin_up",
    "turnover_up",
)


def _improved(now: float | None, before: float | None) -> int | None:
    """1 bei einer Verbesserung, 0 sonst (Gleichstand zaehlt nicht), ``None`` ohne Werte."""
    return None if now is None or before is None else int(now > before)


def _positive(value: float | None) -> int | None:
    return None if value is None else int(value > 0)


def _average(a: float | None, b: float | None) -> float | None:
    return None if a is None or b is None else (a + b) / 2.0


def _gross_profit(year: FiscalYear) -> float | None:
    """Bruttoergebnis, ohne die Zeile aus Umsatz minus Umsatzkosten."""
    if year.gross_profit is not None:
        return year.gross_profit
    if year.revenue is None or year.cost_of_revenue is None:
        return None
    return year.revenue - year.cost_of_revenue


def _leverage(years: Sequence[FiscalYear]) -> tuple[float | None, float | None]:
    """Langfristige Schulden je durchschnittlicher Bilanzsumme, dieses Jahr und Vorjahr.

    Fehlt die Zeile in beiden Jahren, gibt es keine langfristigen Schulden (0). Fehlt sie in
    einem, ist das eine Luecke.
    """
    t, p, b = years[0], years[1], years[2]
    if t.long_term_debt is None and p.long_term_debt is None:
        return 0.0, 0.0
    return (
        safe_div(t.long_term_debt, _average(t.total_assets, p.total_assets)),
        safe_div(p.long_term_debt, _average(p.total_assets, b.total_assets)),
    )


def f_score_signals(years: Sequence[FiscalYear]) -> dict[str, int] | None:
    """Die neun Signale des F-Scores, je 1 oder 0; ``None``, wenn einem ein Wert fehlt.

    Quelle: Piotroski, J. (2000), "Value Investing: The Use of Historical Financial Statement
    Information to Separate Winners from Losers", Journal of Accounting Research 38, S. 1-41.
    ROA, operativer Cashflow und Kapitalumschlag beziehen sich auf die Bilanzsumme am
    Jahresanfang, die Verschuldung auf die durchschnittliche Bilanzsumme. Dafuer braucht es drei
    Geschaeftsjahre (``years``, juengstes zuerst). Eine Verbesserung zaehlt, Gleichstand nicht;
    keine neuen Aktien heisst: Die Aktienanzahl ist nicht gestiegen.
    """
    if len(years) < 3:
        return None
    t, p, b = years[0], years[1], years[2]
    roa = safe_div(t.net_income, p.total_assets)
    roa_before = safe_div(p.net_income, b.total_assets)
    cfo = safe_div(t.operating_cash_flow, p.total_assets)
    leverage, leverage_before = _leverage(years)
    shares = None if t.shares is None or p.shares is None else int(t.shares <= p.shares)
    signals = {
        "roa_positive": _positive(roa),
        "cfo_positive": _positive(t.operating_cash_flow),
        "roa_up": _improved(roa, roa_before),
        "cfo_above_net_income": _improved(cfo, roa),
        # Weniger Verschuldung ist die Verbesserung
        "leverage_down": _improved(leverage_before, leverage),
        "liquidity_up": _improved(
            safe_div(t.current_assets, t.current_liabilities),
            safe_div(p.current_assets, p.current_liabilities),
        ),
        "no_new_shares": shares,
        "margin_up": _improved(
            safe_div(_gross_profit(t), t.revenue), safe_div(_gross_profit(p), p.revenue)
        ),
        "turnover_up": _improved(
            safe_div(t.revenue, p.total_assets), safe_div(p.revenue, b.total_assets)
        ),
    }
    if any(value is None for value in signals.values()):
        return None
    return {key: int(value) for key, value in signals.items() if value is not None}


def f_score(years: Sequence[FiscalYear]) -> int | None:
    """Piotroski-F-Score 0 bis 9, hoeher ist besser; ``None`` bei fehlenden Werten."""
    signals = f_score_signals(years)
    return None if signals is None else sum(signals.values())


def _average_assets(years: Sequence[FiscalYear]) -> float | None:
    if len(years) < 2:
        return None
    return _average(years[0].total_assets, years[1].total_assets)


def operating_accruals(years: Sequence[FiscalYear]) -> float | None:
    """(Jahresueberschuss - operativer Cashflow) / durchschnittliche Bilanzsumme.

    Quelle: Sloan, R. (1996), "Do Stock Prices Fully Reflect Information in Accruals and Cash
    Flows about Future Earnings?", The Accounting Review 71, S. 289-315. Niedriger ist besser:
    Ein hoher Wert heisst, der Gewinn steht vor allem auf dem Papier.
    """
    if not years or years[0].net_income is None or years[0].operating_cash_flow is None:
        return None
    return safe_div(years[0].net_income - years[0].operating_cash_flow, _average_assets(years))


def cfo_assets(years: Sequence[FiscalYear]) -> float | None:
    """Operativer Cashflow / durchschnittliche Bilanzsumme (cash-basierte Profitabilitaet)."""
    if not years:
        return None
    return safe_div(years[0].operating_cash_flow, _average_assets(years))


def _window_median(counts: Mapping[date, float], end: date) -> float | None:
    window = [
        value
        for day, value in counts.items()
        if end - timedelta(days=ISSUANCE_WINDOW_DAYS) < day <= end
    ]
    return float(np.median(window)) if window else None


def net_share_issuance(history: ShareHistory | None) -> float | None:
    """Veraenderung der Aktienanzahl ueber 12 Monate, um Splits bereinigt (JKP ``chcsho_12m``).

    - Stichtag ist der juengste Tag mit Aktienanzahl, hoechstens ``ISSUANCE_MAX_AGE_DAYS`` vor
      dem Abruf. Jede Aktienanzahl wird mit den Splits danach bis zum Stichtag auf dessen
      Basis gebracht.
    - Verglichen werden die Mediane der ``ISSUANCE_WINDOW_DAYS`` Tage bis zum Stichtag und bis
      ``ISSUANCE_LAG_DAYS`` davor. Der Median faengt doppelte und abweichende Tage von Yahoo ab.
    - Negativ heisst: Aktien zurueckgekauft. ``None`` ohne Werte in einem der Fenster.
    """
    if history is None or not history.counts:
        return None
    latest = max(history.counts)
    if (history.as_of - latest).days > ISSUANCE_MAX_AGE_DAYS:
        return None
    splits = [(day, ratio) for day, ratio in history.splits.items() if ratio > 0]

    def adjusted(day: date, count: float) -> float:
        return count * math.prod(ratio for split, ratio in splits if day < split <= latest)

    counts = {day: adjusted(day, count) for day, count in history.counts.items()}
    now = _window_median(counts, latest)
    before = _window_median(counts, latest - timedelta(days=ISSUANCE_LAG_DAYS))
    change = safe_div(now, before)
    return None if change is None else change - 1


def _growth(history: Sequence[float | None]) -> float | None:
    values = _recent(history)
    return None if values is None else cagr(values)


def _to_trading(value: float | None, fx: float | None) -> float | None:
    if value is None or fx is None:
        return None
    return value * fx


def compute_metrics(
    statements: StatementFigures,
    market: MarketFigures,
    *,
    fx: float | None,
    default_tax_rate: float,
    shares: ShareHistory | None = None,
) -> Metrics:
    """Alle Kennzahlen eines Titels.

    ``shares`` ist die Historie der Aktienanzahl fuer die Netto-Emission (F2.2).

    ``fx`` rechnet Berichts- in Handelswaehrung um (1.0 = gleich, ``None`` = unbekannt).
    Marktdaten sind in Handelswaehrung, Abschluesse in Berichtswaehrung (z. B. Qiagen:
    EUR gegen USD). Fuer die Multiples werden die Abschlusswerte umgerechnet. Weichen die
    Waehrungen ab, mischen Yahoos ``enterpriseValue``, ``priceToBook`` und ``trailingPE``
    sie unkonvertiert - dann werden die drei selbst berechnet. Ohne Kurs bleiben die
    gemischten Multiples leer.
    """
    s = statements
    fcf = s.fcf
    if fcf is None and s.operating_cash_flow is not None and s.capex is not None:
        fcf = s.operating_cash_flow + s.capex  # capex ist negativ

    mcap = market.market_cap
    enterprise_value = market.enterprise_value
    ebit_t = _to_trading(s.ebit, fx)
    fcf_t = _to_trading(fcf, fx)
    equity_t = _to_trading(s.total_equity, fx)
    net_income_t = _to_trading(s.net_income, fx)
    buybacks_t = _to_trading(s.buybacks, fx)

    if fx == 1.0:  # gleiche Waehrung - der Abruf liefert dann exakt 1.0
        pe_ratio = market.trailing_pe
        pb_ratio = market.price_to_book or safe_div(mcap, equity_t)
    else:
        debt_t, cash_t = _to_trading(s.total_debt, fx), _to_trading(s.cash, fx)
        enterprise_value = (
            mcap + debt_t - cash_t
            if mcap is not None and debt_t is not None and cash_t is not None
            else None
        )
        pe_ratio = (
            safe_div(mcap, net_income_t) if net_income_t is not None and net_income_t > 0 else None
        )
        pb_ratio = safe_div(mcap, equity_t)

    div_yield = market.dividend_yield
    buyback_yield = safe_div(abs(buybacks_t), mcap) if buybacks_t is not None else None
    # 0 % ist ein echter Wert (keine Dividende, keine Rueckkaeufe) - nur None, wenn beides fehlt
    yields = [v for v in (div_yield, buyback_yield) if v is not None]

    return Metrics(
        enterprise_value=enterprise_value,
        ev_ebit=safe_div(enterprise_value, ebit_t),
        pe_ratio=pe_ratio,
        pb_ratio=pb_ratio,
        p_fcf=safe_div(mcap, fcf_t),
        dividend_yield=div_yield,
        buyback_yield=buyback_yield,
        shareholder_yield=sum(yields) if yields else None,
        net_share_issuance=net_share_issuance(shares),
        nopat_normalized=nopat_normalized(
            s.ebit_history,
            pretax=s.pretax_income,
            tax=s.tax_expense,
            fx=fx,
            default_tax_rate=default_tax_rate,
        ),
        roic=roic(
            ebit=s.ebit,
            equity=s.total_equity,
            debt=s.total_debt,
            pretax=s.pretax_income,
            tax=s.tax_expense,
            default_tax_rate=default_tax_rate,
        ),
        roa=safe_div(s.net_income, s.total_assets),
        fcf_margin=safe_div(fcf, s.revenue),
        gross_margin=safe_div(s.gross_profit, s.revenue),
        operating_margin=safe_div(s.operating_income, s.revenue),
        net_debt_ebitda=(
            safe_div(s.total_debt - s.cash, s.ebitda)
            if s.total_debt is not None and s.cash is not None and s.ebitda
            else None
        ),
        debt_to_equity=safe_div(s.total_debt, s.total_equity),
        earnings_stability=earnings_stability(s.net_income_history),
        f_score=f_score(s.years),
        operating_accruals=operating_accruals(s.years),
        cfo_assets=cfo_assets(s.years),
        revenue_growth_5y=_growth(s.revenue_history),
        eps_growth_5y=_growth(s.eps_history),
    )
