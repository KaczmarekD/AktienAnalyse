"""Fundamental- und Marktdaten via yfinance.

Pro Ticker werden Bewertungs- und Qualitaetskennzahlen extrahiert. yfinance
beschriftet seine Statement-Zeilen inkonsistent (mal "Total Revenue", mal
"TotalRevenue", mal "Revenue"); ``FIELD_MAP`` zentralisiert alle Varianten
an einer Stelle, sodass eine yfinance-Umbenennung nur hier zu pflegen ist.

Caching: tagesgenauer Parquet-Cache. Re-Runs am selben Tag treffen den Cache,
``force_refresh=True`` umgeht ihn.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yfinance as yf
from tenacity import retry, stop_after_attempt, wait_exponential

from .fundamentals import (
    Fundamentals,
    Growth,
    Identity,
    MarketData,
    QualityMetrics,
    ValueMetrics,
)
from .universe import Ticker

log = logging.getLogger(__name__)


# Zentralisiertes Mapping: yfinance-Variantennamen pro logischem Feld.
# Reihenfolge = Vorrang.
FIELD_MAP: dict[str, tuple[str, ...]] = {
    "revenue": ("Total Revenue", "TotalRevenue", "Revenue"),
    "ebit": ("EBIT", "Operating Income", "OperatingIncome"),
    "ebitda": ("EBITDA", "Normalized EBITDA"),
    "gross_profit": ("Gross Profit", "GrossProfit"),
    "operating_inc": ("Operating Income", "OperatingIncome"),
    "net_income": (
        "Net Income",
        "NetIncome",
        "Net Income Common Stockholders",
        "Net Income Continuous Operations",
    ),
    "pretax_income": ("Pretax Income", "PretaxIncome", "Income Before Tax"),
    "tax_expense": ("Tax Provision", "Income Tax Expense", "IncomeTaxExpense"),
    "diluted_eps": ("Diluted EPS", "Basic EPS"),
    "total_assets": ("Total Assets", "TotalAssets"),
    "total_equity": (
        "Stockholders Equity",
        "Total Stockholder Equity",
        "Common Stock Equity",
    ),
    "total_debt": ("Total Debt", "TotalDebt", "Long Term Debt", "LongTermDebt"),
    "cash": (
        "Cash And Cash Equivalents",
        "Cash",
        "Cash Cash Equivalents And Short Term Investments",
    ),
    "fcf": ("Free Cash Flow", "FreeCashFlow"),
    "op_cash": (
        "Operating Cash Flow",
        "Total Cash From Operating Activities",
        "OperatingCashFlow",
    ),
    "capex": ("Capital Expenditure", "CapitalExpenditure", "Capital Expenditures"),
    "buybacks": (
        "Repurchase Of Capital Stock",
        "Common Stock Repurchased",
        "RepurchaseOfStock",
    ),
}


@dataclass
class FetcherConfig:
    sleep_between: float = 0.4
    default_tax_rate: float = 0.27
    # Unter dieser Erfolgsquote (Anteil Ticker mit Marktkapitalisierung) wird
    # nicht gecached - sonst liefert ein Re-Run nach einem yfinance-Ausfall am
    # selben Tag weiter die kaputten Daten.
    min_cache_success_share: float = 0.8


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------


def _safe_div(num: float | None, den: float | None) -> float | None:
    try:
        if num is None or den is None:
            return None
        nv, dv = float(num), float(den)
        if not np.isfinite(nv) or not np.isfinite(dv) or dv == 0:
            return None
        return nv / dv
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def _f(value: Any) -> float | None:
    """Robuste Konvertierung zu float oder None."""
    if value is None:
        return None
    try:
        v = float(value)
        if not np.isfinite(v):
            return None
        return v
    except (TypeError, ValueError):
        return None


def _pick(df: pd.DataFrame | None, key: str) -> pd.Series | None:
    """Findet die yfinance-Zeile fuer einen logischen Feldnamen aus FIELD_MAP."""
    if df is None or df.empty:
        return None
    candidates = FIELD_MAP.get(key, ())
    for c in candidates:
        if c in df.index:
            row = df.loc[c]
            # df.loc[scalar] kann theoretisch DataFrame zurueckgeben (Multi-Index);
            # bei den yfinance-Statements ist es immer Series.
            return row if isinstance(row, pd.Series) else None
    lower_map = {str(i).lower(): i for i in df.index}
    for c in candidates:
        if c.lower() in lower_map:
            row = df.loc[lower_map[c.lower()]]
            return row if isinstance(row, pd.Series) else None
    return None


def _latest(series: pd.Series | None) -> float | None:
    if series is None or series.empty:
        return None
    cleaned = series.dropna()
    if cleaned.empty:
        return None
    return _f(cleaned.iloc[0])


def _series_n(series: pd.Series | None, n: int) -> list[float] | None:
    if series is None:
        return None
    vals = [v for v in (_f(x) for x in series.iloc[:n].tolist()) if v is not None]
    return vals if len(vals) >= max(2, n - 1) else None


def _cagr(values: list[float]) -> float | None:
    """CAGR aus Zeitreihe (juengstes Element zuerst). None bei Vorzeichenwechsel."""
    if not values or len(values) < 2:
        return None
    first, last = values[0], values[-1]
    if last == 0 or first / last <= 0:
        return None
    years = len(values) - 1
    try:
        return float((first / last) ** (1.0 / years) - 1.0)
    except (ZeroDivisionError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Per-Ticker Extraktion
# ---------------------------------------------------------------------------


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1.5, min=2, max=15))
def _ticker_data(symbol: str) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    yt = yf.Ticker(symbol)
    info = yt.info or {}
    income = yt.income_stmt if hasattr(yt, "income_stmt") else yt.financials
    balance = yt.balance_sheet
    cashflow = yt.cashflow
    return info, income, balance, cashflow


@lru_cache(maxsize=16)
@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1.5, min=2, max=15))
def _fx_rate(from_ccy: str, to_ccy: str) -> float:
    """Wechselkurs 1 from_ccy -> to_ccy (z.B. USD -> EUR). Pro Run gecached."""
    rate = _f(yf.Ticker(f"{from_ccy}{to_ccy}=X").fast_info.get("lastPrice"))
    if rate is None or rate <= 0:
        msg = f"kein Kurs fuer {from_ccy}{to_ccy}=X"
        raise ValueError(msg)
    return rate


def _statement_fx(info: dict[str, Any], errors: list[str]) -> float | None:
    """Faktor von Berichts- in Handelswaehrung.

    1.0, wenn beide gleich (oder unbekannt). None, wenn der Kurs nicht zu
    bekommen ist - dann duerfen Abschlusswerte nicht gegen Marktdaten
    gerechnet werden.
    """
    trading = info.get("currency")
    reporting = info.get("financialCurrency")
    if not trading or not reporting or trading == reporting:
        return 1.0
    try:
        return _fx_rate(reporting, trading)
    except Exception as e:
        errors.append(f"fx {reporting}->{trading} failed: {e}")
        log.warning("Wechselkurs %s->%s fehlgeschlagen: %s", reporting, trading, e)
        return None


def _to_trading(value: float | None, fx: float | None) -> float | None:
    if value is None or fx is None:
        return None
    return value * fx


def fetch_one(ticker: Ticker, cfg: FetcherConfig | None = None) -> Fundamentals:
    cfg = cfg or FetcherConfig()
    fund = Fundamentals(
        identity=Identity(symbol=ticker.symbol, name=ticker.name, index=ticker.index)
    )

    try:
        info, income, balance, cashflow = _ticker_data(ticker.symbol)
    except Exception as e:
        fund.errors.append(f"fetch failed: {e}")
        log.warning("Fetch %s fehlgeschlagen: %s", ticker.symbol, e)
        return fund

    fund.identity.currency = info.get("currency")
    fund.identity.financial_currency = info.get("financialCurrency")
    fund.identity.sector = info.get("sector")
    fund.identity.industry = info.get("industry")

    fund.market = MarketData(
        price=_f(info.get("currentPrice") or info.get("regularMarketPrice")),
        market_cap=_f(info.get("marketCap")),
        enterprise_value=_f(info.get("enterpriseValue")),
        shares_outstanding=_f(info.get("sharesOutstanding")),
    )

    # Statement-Werte
    revenue = _latest(_pick(income, "revenue"))
    ebit = _latest(_pick(income, "ebit"))
    ebitda = _latest(_pick(income, "ebitda"))
    gross_profit = _latest(_pick(income, "gross_profit"))
    operating_inc = _latest(_pick(income, "operating_inc"))
    net_income = _latest(_pick(income, "net_income"))
    pretax_income = _latest(_pick(income, "pretax_income"))
    tax_expense = _latest(_pick(income, "tax_expense"))
    total_assets = _latest(_pick(balance, "total_assets"))
    total_equity = _latest(_pick(balance, "total_equity"))
    total_debt = _latest(_pick(balance, "total_debt"))
    cash = _latest(_pick(balance, "cash"))

    fcf = _latest(_pick(cashflow, "fcf"))
    if fcf is None:
        op_cf = _latest(_pick(cashflow, "op_cash"))
        capex = _latest(_pick(cashflow, "capex"))
        if op_cf is not None and capex is not None:
            fcf = op_cf + capex  # capex i.d.R. negativ in yfinance

    buybacks = _latest(_pick(cashflow, "buybacks"))

    # --- Value ---
    # Marktdaten sind in Handelswaehrung, Abschluesse in Berichtswaehrung (z.B.
    # Qiagen: EUR vs. USD). Fuer Multiples Abschlusswerte umrechnen. Yahoos
    # enterpriseValue/priceToBook/trailingPE mischen die Waehrungen dann
    # unkonvertiert - selbst berechnen.
    fx = _statement_fx(info, fund.errors)
    mcap = fund.market.market_cap
    ebit_t = _to_trading(ebit, fx)
    fcf_t = _to_trading(fcf, fx)
    equity_t = _to_trading(total_equity, fx)
    net_income_t = _to_trading(net_income, fx)
    buybacks_t = _to_trading(buybacks, fx)

    if fx == 1.0:  # gleiche Waehrung - _statement_fx liefert exakt 1.0
        pe_ratio = _f(info.get("trailingPE"))
        pb_ratio = _f(info.get("priceToBook")) or _safe_div(mcap, equity_t)
    else:
        debt_t, cash_t = _to_trading(total_debt, fx), _to_trading(cash, fx)
        fund.market.enterprise_value = (
            mcap + debt_t - cash_t
            if mcap is not None and debt_t is not None and cash_t is not None
            else None
        )
        pe_ratio = (
            _safe_div(mcap, net_income_t) if net_income_t is not None and net_income_t > 0 else None
        )
        pb_ratio = _safe_div(mcap, equity_t)

    div_yield = _dividend_yield(info)
    buyback_yield = _safe_div(abs(buybacks_t), mcap) if buybacks_t is not None else None
    # 0 % ist ein echter Wert (keine Dividende, keine Rueckkaeufe) - nur None, wenn beides fehlt
    yields = [v for v in (div_yield, buyback_yield) if v is not None]
    shareholder_yield = sum(yields) if yields else None

    fund.value = ValueMetrics(
        ev_ebit=_safe_div(fund.market.enterprise_value, ebit_t),
        pe_ratio=pe_ratio,
        pb_ratio=pb_ratio,
        p_fcf=_safe_div(mcap, fcf_t),
        dividend_yield=div_yield,
        buyback_yield=buyback_yield,
        shareholder_yield=shareholder_yield,
    )

    # --- Quality ---
    roic = _roic(
        ebit=ebit,
        equity=total_equity,
        debt=total_debt,
        pretax=pretax_income,
        tax=tax_expense,
        default_tax_rate=cfg.default_tax_rate,
    )

    fund.quality = QualityMetrics(
        roic=roic,
        roa=_safe_div(net_income, total_assets),
        fcf_margin=_safe_div(fcf, revenue),
        gross_margin=_safe_div(gross_profit, revenue),
        operating_margin=_safe_div(operating_inc, revenue),
        net_debt_ebitda=(
            _safe_div((total_debt - cash), ebitda)
            if total_debt is not None and cash is not None and ebitda
            else None
        ),
        debt_to_equity=_safe_div(total_debt, total_equity),
        earnings_stability=_earnings_stability(income),
    )

    # --- Growth ---
    fund.growth = Growth(
        revenue_growth_5y=_cagr(_series_n(_pick(income, "revenue"), 5) or []),
        eps_growth_5y=_cagr(_series_n(_pick(income, "diluted_eps"), 5) or []),
    )

    return fund


def _dividend_yield(info: dict[str, Any]) -> float | None:
    """Dividendenrendite als Dezimal (0.03 = 3 %).

    ``trailingAnnualDividendYield`` ist dezimal und hat Vorrang. ``dividendYield``
    liefert yfinance seit 0.2.5x in Prozent (1.36 = 1,36 %) - daher immer / 100,
    ein Schwellwert wie "> 1" wuerde Renditen unter 1 % um Faktor 100 aufblaehen.
    """
    trailing = _f(info.get("trailingAnnualDividendYield"))
    if trailing is not None:
        return trailing
    pct = _f(info.get("dividendYield"))
    return pct / 100.0 if pct is not None else None


def _roic(
    *,
    ebit: float | None,
    equity: float | None,
    debt: float | None,
    pretax: float | None,
    tax: float | None,
    default_tax_rate: float,
) -> float | None:
    """ROIC = NOPAT / Invested Capital. Effektive Steuerquote wenn moeglich."""
    if ebit is None or equity is None:
        return None
    if pretax and pretax > 0 and tax is not None and tax >= 0:
        eff_tax = min(0.6, max(0.0, tax / pretax))
    else:
        eff_tax = default_tax_rate
    nopat = ebit * (1.0 - eff_tax)
    invested = equity + (debt or 0.0)
    return _safe_div(nopat, invested)


def _earnings_stability(income: pd.DataFrame | None) -> float | None:
    ni_series = _series_n(_pick(income, "net_income"), 5)
    if not ni_series:
        return None
    arr = np.array(ni_series, dtype=float)
    mean_abs = float(np.mean(np.abs(arr)))
    if mean_abs <= 0:
        return None
    cv = float(np.std(arr) / mean_abs)
    return max(0.0, 1.0 - min(cv, 1.0))


# ---------------------------------------------------------------------------
# Batch + Cache
# ---------------------------------------------------------------------------


def _cache_path(cache_dir: Path) -> Path:
    return cache_dir / f"fundamentals_{date.today().isoformat()}.parquet"


def fetch_all(
    tickers: Iterable[Ticker],
    cache_dir: Path,
    force_refresh: bool = False,
    cfg: FetcherConfig | None = None,
) -> pd.DataFrame:
    """Holt alle Ticker. Liefert einen flachen DataFrame."""
    cfg = cfg or FetcherConfig()
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = _cache_path(cache_dir)

    if cache_file.exists() and not force_refresh:
        log.info("Lade Fundamentals aus Cache: %s", cache_file)
        return pd.read_parquet(cache_file)

    ticker_list = list(tickers)
    rows: list[dict[str, Any]] = []
    for i, t in enumerate(ticker_list, 1):
        log.info("(%d/%d) %s", i, len(ticker_list), t.symbol)
        rows.append(fetch_one(t, cfg).to_flat_dict())
        time.sleep(cfg.sleep_between)

    df = pd.DataFrame(rows)
    success_share = _success_share(df)
    if success_share >= cfg.min_cache_success_share:
        df.to_parquet(cache_file, index=False)
        log.info("Fundamentals fuer %d Werte gecached -> %s", len(df), cache_file)
    else:
        log.warning(
            "Nur %.0f %% der Ticker erfolgreich geladen (< %.0f %%) - kein Cache geschrieben",
            success_share * 100,
            cfg.min_cache_success_share * 100,
        )
    return df


def _success_share(df: pd.DataFrame) -> float:
    """Anteil der Zeilen mit Marktkapitalisierung - fehlt sie, ist der Fetch gescheitert."""
    if df.empty or "market_cap" not in df.columns:
        return 0.0
    return float(df["market_cap"].notna().mean())
