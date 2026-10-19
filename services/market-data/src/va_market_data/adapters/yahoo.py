"""Fundamental- und Marktdaten via yfinance.

Pro Ticker werden Bewertungs- und Qualitaetskennzahlen extrahiert. yfinance
beschriftet seine Statement-Zeilen inkonsistent (mal "Total Revenue", mal
"TotalRevenue", mal "Revenue"); ``FIELD_MAP`` zentralisiert alle Varianten
an einer Stelle, sodass eine yfinance-Umbenennung nur hier zu pflegen ist.

Adapter fuer den Port ``FundamentalsProvider`` (``YahooFundamentals``). Die Rohdaten
des Providers haengen als ``Fundamentals.raw`` am Ergebnis; die Kennzahlen rechnet
``domain.metrics``.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, fields
from datetime import UTC, date, datetime, timedelta
from functools import lru_cache, partial
from typing import Any

import pandas as pd
import yfinance as yf
from tenacity import retry, retry_if_not_exception_type, stop_after_attempt, wait_exponential
from yfinance.exceptions import YFRateLimitError

from ..domain.consensus import MAX_ERROR_LENGTH, ConsensusEntry, collect_consensus, to_payload
from ..domain.fundamentals import (
    Fundamentals,
    Growth,
    Identity,
    MarketData,
    Provenance,
    QualityMetrics,
    RawFetch,
    ValueMetrics,
)
from ..domain.history import HistoryState, split_days
from ..domain.metrics import (
    MarketFigures,
    Metrics,
    StatementFigures,
    compute_metrics,
)
from ..domain.periods import period_end
from ..domain.universe import Ticker

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

# Konsens-Snapshots (ADR-0010): stabiler Name der Art in der DB -> Attribut von yf.Ticker.
# Benennt yfinance ein Attribut um, wird nur hier nachgezogen - die DB-Namen bleiben.
CONSENSUS_FIELDS: dict[str, str] = {
    "eps_trend": "eps_trend",
    "eps_revisions": "eps_revisions",
    "earnings_estimate": "earnings_estimate",
    "revenue_estimate": "revenue_estimate",
    "growth_estimates": "growth_estimates",
    "analyst_price_targets": "analyst_price_targets",
}

# Arten, die yfinance aus einem gemeinsamen Abruf (Modul earningsTrend) liest. Scheitert
# er, loggt yfinance den Fehler nur beim ersten Zugriff; die anderen kaemen still leer.
CONSENSUS_SHARED_SOURCE: tuple[str, ...] = (
    "eps_trend",
    "eps_revisions",
    "earnings_estimate",
    "revenue_estimate",
    "growth_estimates",
)

# Quartalsabschluesse (ADR-0010, F1.2): Statement -> Attribut von yf.Ticker.
QUARTERLY_FIELDS: dict[str, str] = {
    "income": "quarterly_income_stmt",
    "balance": "quarterly_balance_sheet",
    "cashflow": "quarterly_cashflow",
}

# Kurshistorie (ADR-0010, F1.4): eigene Spalte -> Spalte von
# yf.Ticker.history(auto_adjust=False, actions=True)
PRICE_FIELDS: dict[str, str] = {
    "close": "Close",
    "adj_close": "Adj Close",
    "dividend": "Dividends",
    "split": "Stock Splits",
}


@dataclass
class FetcherConfig:
    sleep_between: float = 0.4
    default_tax_rate: float = 0.27
    # Erster Abruf der Aktienanzahl (F1.3); Yahoo liefert meist erst ab 2015
    shares_history_start: date = date(2000, 1, 1)
    # Kurse (F1.4): ab dem letzten gespeicherten Tag minus 8 Wochen (~40 Handelstage).
    # Spaete Korrekturen werden sichtbar, ausgefallene Laeufe hinterlassen keine Luecke.
    price_overlap_days: int = 56


PROVIDER = "yfinance"


def provider_version() -> str:
    """Version des Datenproviders - wird mit jedem Abruf gespeichert."""
    return str(getattr(yf, "__version__", "unknown"))


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------


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
    return _to_float(cleaned.iloc[0])


def _to_float(value: Any) -> float | None:
    """Endliche Zahl als ``float``, sonst ``None`` (auch fuer NaN, inf und Text)."""
    if value is None:
        return None
    try:
        number = float(value)
    except TypeError, ValueError:
        return None
    return number if math.isfinite(number) else None


def _history(series: pd.Series | None) -> list[float | None]:
    """Ein Wert je Geschaeftsjahr (juengstes zuerst), ``None`` fuer ein fehlendes.

    Welche Jahre fuer Wachstum und Stabilitaet zaehlen, entscheidet die Domain.
    """
    return [] if series is None else [_to_float(x) for x in series.tolist()]


def _dividend_yield(info: dict[str, Any]) -> float | None:
    """Dividendenrendite als Dezimal (0.03 = 3 %).

    ``trailingAnnualDividendYield`` ist dezimal und hat Vorrang. ``dividendYield``
    liefert yfinance seit 0.2.5x in Prozent (1.36 = 1,36 %) - daher immer / 100,
    ein Schwellwert wie "> 1" wuerde Renditen unter 1 % um Faktor 100 aufblaehen.
    Mit yfinance 1.7 unveraendert: Live-Vergleich gegen 0.2.66 am 30.09.2026 ergab
    fuer alle 90 Titel identische Werte.
    """
    trailing = _to_float(info.get("trailingAnnualDividendYield"))
    if trailing is not None:
        return trailing
    pct = _to_float(info.get("dividendYield"))
    return pct / 100.0 if pct is not None else None


def _fields_of(
    metrics: Metrics, group: type[ValueMetrics | QualityMetrics | Growth]
) -> dict[str, Any]:
    """Die Kennzahlen, die zu einer Gruppe in ``Fundamentals`` gehoeren."""
    return {f.name: getattr(metrics, f.name) for f in fields(group)}


def _dated_columns(
    df: pd.DataFrame | None, statement: str, errors: list[str]
) -> pd.DataFrame | None:
    """Nur Spalten mit Periodenende - genau die, die ``statement_value`` speichert.

    Sonst stuenden im Snapshot Kennzahlen aus Werten, die nicht in der Historie
    landen und sich daraus nicht nachrechnen lassen.
    """
    if df is None or df.empty:
        return df
    keep = [period_end(c) is not None for c in df.columns]
    if all(keep):
        return df
    errors.append(f"{statement}: {keep.count(False)} Spalte(n) ohne Periodenende verworfen")
    return df.loc[:, keep]


def _fiscal_period_end(income: pd.DataFrame | None) -> date | None:
    """Geschaeftsjahresende der juengsten Umsatz-Spalte (sonst erste befuellte Spalte)."""
    labels: list[Any] = []
    revenue = _pick(income, "revenue")
    if revenue is not None:
        labels += list(revenue.dropna().index)
    if income is not None and not income.empty:
        labels += [c for c in income.columns if income[c].notna().any()]
    # Erstes gueltiges Label - eine Spalte ohne Datum darf das Jahr nicht kosten
    return next((d for d in map(period_end, labels) if d is not None), None)


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


class _RateLimitGuard:
    """Merkt sich ein Rate-Limit waehrend der Zusatzabrufe eines Titels (ADR-0010).

    Danach bleiben die restlichen Zusatzabrufe dieses Titels aus, statt weiter in die
    Drosselung zu laufen. ``fetch_one`` setzt den Zustand je Titel zurueck, der Batch
    laeuft in einem Thread.
    """

    def __init__(self) -> None:
        self.hit = False


_RATE_LIMIT = _RateLimitGuard()


def note_rate_limit(error: BaseException) -> bool:
    """True bei einem Rate-Limit. Es gilt dann fuer die restlichen Zusatzabrufe des Titels."""
    if isinstance(error, YFRateLimitError):
        _RATE_LIMIT.hit = True
        return True
    return False


@contextmanager
def _yahoo_errors_raised() -> Iterator[None]:
    """Fehler von yfinance durchreichen statt verschlucken.

    yfinance faengt Fehler standardmaessig ab (``config.debug.hide_exceptions``) und
    liefert eine leere Antwort, auch bei einem Rate-Limit. In den Zusatzabrufen sollen
    sie ankommen: fuer Retry, Abbruch nach Rate-Limit und Log. Der Retry hilft nur bei
    Netzfehlern - eine HTTP-Fehlerantwort cacht yfinance, der zweite Versuch liest sie
    nur erneut.
    """
    debug = yf.config.debug
    hidden = debug.hide_exceptions
    debug.hide_exceptions = False
    try:
        yield
    finally:
        debug.hide_exceptions = hidden


class YahooResponseError(Exception):
    """yfinance hat einen HTTP-Fehler nur geloggt und eine leere Antwort geliefert."""


class _YfErrorCapture(logging.Handler):
    """Sammelt die ERROR-Meldungen, die yfinance waehrend eines Aufrufs loggt."""

    def __init__(self) -> None:
        super().__init__(level=logging.ERROR)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


@retry(
    retry=retry_if_not_exception_type((YFRateLimitError, YahooResponseError)),
    stop=stop_after_attempt(2),
    wait=wait_exponential(multiplier=1, min=1, max=4),
    reraise=True,
)
def _consensus_value(yt: Any, attr: str) -> Any:
    """Ein Attribut von ``yf.Ticker`` abrufen.

    yfinance verschluckt HTTP-Fehler wie 401, 404 oder 5xx: Es loggt sie und liefert
    leer. Das wird hier zum Fehler, statt als "keine Daten" gespeichert zu werden. Ein
    Retry hilft dann nicht, weil yfinance das leere Ergebnis cacht. Ebenso wenig
    wird nach einem Rate-Limit sofort wiederholt.
    """
    capture = _YfErrorCapture()
    yf_logger = logging.getLogger("yfinance")
    yf_logger.addHandler(capture)
    try:
        value = getattr(yt, attr)
    finally:
        yf_logger.removeHandler(capture)
    if capture.messages and to_payload(value) is None:
        raise YahooResponseError(capture.messages[-1])
    return value


def _mark_follow_up_errors(entries: dict[str, ConsensusEntry]) -> None:
    """Ist der gemeinsame Abruf gescheitert (HTTP-Fehler, den yfinance nur loggt), ist
    "leer" bei den anderen Arten kein Befund (keine Analystenabdeckung), sondern derselbe
    Ausfall. Ein Fehler, der nur eine Art betrifft (etwa beim Parsen), zaehlt nicht."""
    failed = next(
        (
            k
            for k in CONSENSUS_SHARED_SOURCE
            if k in entries
            and (entries[k].error or "").startswith(f"{YahooResponseError.__name__}:")
        ),
        None,
    )
    if failed is None:
        return
    reason = f"Folgefehler nach {failed}: {entries[failed].error}"[:MAX_ERROR_LENGTH]
    for kind in CONSENSUS_SHARED_SOURCE:
        if kind in entries and entries[kind].status == "empty":
            entries[kind] = ConsensusEntry("error", None, reason)


def fetch_consensus(symbol: str) -> dict[str, ConsensusEntry]:
    """Konsens-Snapshots (ADR-0010, F1.1). Wirft nie: Fehler stehen je Art im Ergebnis.

    Nach einem Rate-Limit werden die restlichen Arten uebersprungen, damit der
    naechste Titel nicht in eine andauernde Drosselung laeuft.
    """
    yt = yf.Ticker(symbol)
    entries = collect_consensus(
        {kind: partial(_consensus_value, yt, attr) for kind, attr in CONSENSUS_FIELDS.items()},
        stop_after=note_rate_limit,
    )
    _mark_follow_up_errors(entries)
    failed = [kind for kind, entry in entries.items() if entry.status == "error"]
    if failed:
        log.warning("Konsensdaten %s nicht abrufbar: %s", symbol, ", ".join(failed))
    return entries


@retry(
    retry=retry_if_not_exception_type(YFRateLimitError),
    stop=stop_after_attempt(2),
    wait=wait_exponential(multiplier=1, min=1, max=4),
    reraise=True,
)
def _quarterly_frame(yt: Any, attr: str) -> pd.DataFrame | None:
    with _yahoo_errors_raised():
        frame = getattr(yt, attr)
    return frame if isinstance(frame, pd.DataFrame) else None


def quarterly_frames(yt: Any, symbol: str) -> dict[str, pd.DataFrame | None]:
    """Quartalsabschluesse je Statement. Ein Fehler kostet nur diesen Abschluss.

    Nach einem Rate-Limit bleiben die restlichen Abschluesse aus, damit der naechste
    Titel nicht in eine andauernde Drosselung laeuft.
    """
    frames: dict[str, pd.DataFrame | None] = {}
    for statement, attr in QUARTERLY_FIELDS.items():
        try:
            frames[statement] = _quarterly_frame(yt, attr)
        except Exception as e:
            log.warning("Quartalsabschluss %s %s nicht abrufbar: %s", symbol, statement, e)
            frames[statement] = None
            if note_rate_limit(e):
                break
    return frames


def fetch_quarterly(symbol: str) -> dict[str, pd.DataFrame | None]:
    """Quartalsabschluesse (ADR-0010, F1.2). Wirft nie: Fehlt einer, fehlt er diese Woche."""
    return quarterly_frames(yf.Ticker(symbol), symbol)


@retry(
    retry=retry_if_not_exception_type(YFRateLimitError),
    stop=stop_after_attempt(2),
    wait=wait_exponential(multiplier=1, min=1, max=4),
    reraise=True,
)
def _shares_full(yt: Any, start: date) -> pd.Series | None:
    with _yahoo_errors_raised():
        series = yt.get_shares_full(start=start)
    return series if isinstance(series, pd.Series) else None


def share_count_series(yt: Any, symbol: str, start: date) -> pd.Series | None:
    """Historie der Aktienanzahl ab ``start``. Ein Fehler kostet nur diese Woche.

    Nach einem Rate-Limit wird nicht sofort wiederholt. Die Luecke schliesst der
    naechste Lauf, weil er ab dem letzten gespeicherten Tag abruft.
    """
    try:
        return _shares_full(yt, start)
    except Exception as e:
        note_rate_limit(e)
        log.warning("Aktienanzahl %s nicht abrufbar: %s", symbol, e)
        return None


def fetch_share_counts(symbol: str, start: date) -> pd.Series | None:
    """Aktienanzahl (ADR-0010, F1.3). Wirft nie: Fehlt sie, fehlt sie diese Woche."""
    return share_count_series(yf.Ticker(symbol), symbol, start)


def normalize_prices(frame: pd.DataFrame | None) -> pd.DataFrame | None:
    """yfinance-Spalten -> eigene Namen (``PRICE_FIELDS``). Fehlende Spalten bleiben leer."""
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return None
    renamed = frame.rename(columns={yahoo: own for own, yahoo in PRICE_FIELDS.items()})
    return renamed.reindex(columns=list(PRICE_FIELDS))


@retry(
    retry=retry_if_not_exception_type(YFRateLimitError),
    stop=stop_after_attempt(2),
    wait=wait_exponential(multiplier=1, min=1, max=4),
    reraise=True,
)
def _price_history(yt: Any, start: date | None) -> pd.DataFrame | None:
    window: dict[str, Any] = {"period": "max"} if start is None else {"start": start}
    with _yahoo_errors_raised():
        frame = yt.history(**window, auto_adjust=False, actions=True)
    return frame if isinstance(frame, pd.DataFrame) and not frame.empty else None


def price_frames(
    yt: Any, symbol: str, start: date | None, known_splits: frozenset[date]
) -> pd.DataFrame | None:
    """Kurshistorie ab ``start`` (``None``: die ganze). Ein Fehler kostet nur diese Woche.

    Ein Split passt bei Yahoo alle frueheren Kurse an. Steht im Fenster ein Split, der
    noch nicht gespeichert ist, wird deshalb die ganze Historie geholt - so entstehen
    fuer alle betroffenen Tage neue Versionen. Scheitert das, gibt es diese Woche keine
    Kurse: Gespeichert gaelte der Split als bekannt, und die Altkurse blieben unbereinigt.
    So steht er naechste Woche wieder im Fenster und loest den Vollabruf erneut aus.
    """
    try:
        frame = _price_history(yt, start)
    except Exception as e:
        note_rate_limit(e)
        log.warning("Kurshistorie %s nicht abrufbar: %s", symbol, e)
        return None
    if frame is None or start is None:
        return frame
    new_splits = split_days(normalize_prices(frame)) - known_splits
    if not new_splits:
        return frame
    log.info("Neuer Split bei %s (%s) - hole die ganze Kurshistorie", symbol, min(new_splits))
    try:
        full = _price_history(yt, None)
    except Exception as e:
        note_rate_limit(e)
        log.warning("Kurshistorie %s nach Split nicht abrufbar, diese Woche ohne: %s", symbol, e)
        return None
    if full is None:
        log.warning("Kurshistorie %s nach Split leer, diese Woche ohne Kurse", symbol)
    return full


def fetch_prices(
    symbol: str, start: date | None, known_splits: frozenset[date]
) -> pd.DataFrame | None:
    """Kurshistorie (ADR-0010, F1.4) mit eigenen Spaltennamen. Wirft nie."""
    return normalize_prices(price_frames(yf.Ticker(symbol), symbol, start, known_splits))


@lru_cache(maxsize=16)
@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1.5, min=2, max=15))
def _fx_rate(from_ccy: str, to_ccy: str) -> float:
    """Wechselkurs 1 from_ccy -> to_ccy (z.B. USD -> EUR). Pro Run gecached."""
    rate = _to_float(yf.Ticker(f"{from_ccy}{to_ccy}=X").fast_info.get("lastPrice"))
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


def _additional[T](label: str, symbol: str, fetch: Callable[[], T], fallback: T) -> T:
    """Ein Zusatzabruf (ADR-0010). Nach einem Rate-Limit entfaellt er; ein unerwarteter
    Fehler kostet nur diese Daten, nie den Titel."""
    if _RATE_LIMIT.hit:
        return fallback
    try:
        return fetch()
    except Exception:
        log.exception("%s fuer %s nicht abrufbar - der Titel bleibt", label, symbol)
        return fallback


def fetch_one(
    ticker: Ticker, cfg: FetcherConfig | None = None, history: HistoryState | None = None
) -> Fundamentals:
    """Ein Titel. ``history`` sagt, bis wann seine Zeitreihen schon gespeichert sind."""
    cfg = cfg or FetcherConfig()
    _RATE_LIMIT.hit = False
    fund = Fundamentals(
        identity=Identity(symbol=ticker.symbol, name=ticker.name, index=ticker.index),
        provenance=Provenance(fetched_at=datetime.now(UTC)),
    )

    try:
        info, income, balance, cashflow = _ticker_data(ticker.symbol)
    except Exception as e:
        fund.errors.append(f"fetch failed: {e}")
        log.warning("Fetch %s fehlgeschlagen: %s", ticker.symbol, e)
        return fund

    state = history or HistoryState()
    # Ab dem letzten gespeicherten Tag: Er kommt erneut mit, eine Korrektur wird sichtbar
    shares_start = state.last_share_date or cfg.shares_history_start
    price_start = (
        None
        if state.last_price_date is None
        else state.last_price_date - timedelta(days=cfg.price_overlap_days)
    )
    # Zusatzdaten (ADR-0010): nach einem Rate-Limit bleibt der Rest dieses Titels aus
    symbol = ticker.symbol
    consensus = _additional("Konsens", symbol, lambda: fetch_consensus(symbol), {})
    quarterly = _additional("Quartale", symbol, lambda: fetch_quarterly(symbol), {})
    shares = _additional(
        "Aktienanzahl", symbol, lambda: fetch_share_counts(symbol, shares_start), None
    )
    prices = _additional(
        "Kurse",
        symbol,
        lambda: fetch_prices(symbol, price_start, state.price_split_days),
        None,
    )
    if _RATE_LIMIT.hit:
        log.warning("Rate-Limit bei %s - restliche Zusatzdaten fehlen diese Woche", ticker.symbol)
    fund.raw = RawFetch(
        provider=PROVIDER,
        provider_version=provider_version(),
        info=info,
        statements={"income": income, "balance": balance, "cashflow": cashflow},
        consensus=consensus,
        quarterly=quarterly,
        shares=shares,
        prices=prices,
    )
    # Rohdaten bleiben unveraendert, gerechnet wird nur mit datierten Spalten
    income = _dated_columns(income, "income", fund.errors)
    balance = _dated_columns(balance, "balance", fund.errors)
    cashflow = _dated_columns(cashflow, "cashflow", fund.errors)
    fund.provenance.fiscal_period_end = _fiscal_period_end(income)

    fund.identity.currency = info.get("currency")
    fund.identity.financial_currency = info.get("financialCurrency")
    fund.identity.sector = info.get("sector")
    fund.identity.industry = info.get("industry")

    fund.market = MarketData(
        price=_to_float(info.get("currentPrice") or info.get("regularMarketPrice")),
        market_cap=_to_float(info.get("marketCap")),
        enterprise_value=_to_float(info.get("enterpriseValue")),
        shares_outstanding=_to_float(info.get("sharesOutstanding")),
    )

    statements = StatementFigures(
        revenue=_latest(_pick(income, "revenue")),
        ebit=_latest(_pick(income, "ebit")),
        ebitda=_latest(_pick(income, "ebitda")),
        gross_profit=_latest(_pick(income, "gross_profit")),
        operating_income=_latest(_pick(income, "operating_inc")),
        net_income=_latest(_pick(income, "net_income")),
        pretax_income=_latest(_pick(income, "pretax_income")),
        tax_expense=_latest(_pick(income, "tax_expense")),
        total_assets=_latest(_pick(balance, "total_assets")),
        total_equity=_latest(_pick(balance, "total_equity")),
        total_debt=_latest(_pick(balance, "total_debt")),
        cash=_latest(_pick(balance, "cash")),
        fcf=_latest(_pick(cashflow, "fcf")),
        operating_cash_flow=_latest(_pick(cashflow, "op_cash")),
        capex=_latest(_pick(cashflow, "capex")),
        buybacks=_latest(_pick(cashflow, "buybacks")),
        revenue_history=_history(_pick(income, "revenue")),
        eps_history=_history(_pick(income, "diluted_eps")),
        net_income_history=_history(_pick(income, "net_income")),
    )
    market = MarketFigures(
        market_cap=fund.market.market_cap,
        enterprise_value=fund.market.enterprise_value,
        trailing_pe=_to_float(info.get("trailingPE")),
        price_to_book=_to_float(info.get("priceToBook")),
        dividend_yield=_dividend_yield(info),
    )
    fx = _statement_fx(info, fund.errors)
    fund.provenance.statement_fx = fx
    metrics = compute_metrics(statements, market, fx=fx, default_tax_rate=cfg.default_tax_rate)
    # Bei abweichender Berichtswaehrung aus umgerechneten Abschluessen neu berechnet
    fund.market.enterprise_value = metrics.enterprise_value
    fund.value = ValueMetrics(**_fields_of(metrics, ValueMetrics))
    fund.quality = QualityMetrics(**_fields_of(metrics, QualityMetrics))
    fund.growth = Growth(**_fields_of(metrics, Growth))
    return fund


class YahooFundamentals:
    """``FundamentalsProvider`` ueber yfinance."""

    def __init__(self, cfg: FetcherConfig | None = None) -> None:
        self.cfg = cfg or FetcherConfig()

    def fetch(self, ticker: Ticker, history: HistoryState | None = None) -> Fundamentals:
        return fetch_one(ticker, self.cfg, history=history)
