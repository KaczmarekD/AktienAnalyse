"""Anwendungsfall Tageskurse (D2.3, WP-06, WP-07, WP-11).

Fuer jedes Wertpapier der Abdeckung mit Kurs-Listing der letzte Schlusskurs aus einem Sammelabruf,
dazu die Waehrungskurse nach EUR. Die Waehrung eines Symbols kommt aus frueheren Kursen, sonst einmal
von Yahoo; ohne Waehrung fehlt der Titel, statt geraten zu werden (London notiert manche ETFs in
USD). Robustheit vor Vollstaendigkeit: Ein Titel ohne Kurs fehlt mit seiner ISIN, ein gescheiterter
Abruf wird als ``failed`` gespeichert und gemeldet, nicht als Fehler geworfen.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Protocol

from ..domain.coverage import CoverageItem
from ..domain.prices import EUR, DailyClose, FxDaily, Quote, to_major_unit

log = logging.getLogger(__name__)

SOURCE = "yahoo"


class PriceStore(Protocol):
    def known_currencies(self, symbols: Collection[str]) -> Mapping[str, str]:
        """Die Notierung (z. B. ``GBp``) aus frueheren Kursen je Symbol."""
        ...

    def write_prices(
        self,
        *,
        source: str,
        started_at: datetime,
        finished_at: datetime,
        status: str,
        closes: Sequence[DailyClose],
        fx: Sequence[FxDaily],
    ) -> int:
        """Ein Abruf mit seinen Kursen in einer Transaktion; gibt die ID von ``price_run``."""
        ...


@dataclass(frozen=True)
class PricesResult:
    price_run_id: int
    trade_date: date
    closes: list[DailyClose] = field(default_factory=list)
    fx: list[FxDaily] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)  # ISINs ohne Kurs


def _utcnow() -> datetime:
    return datetime.now(UTC)


def collect_prices(
    items: Sequence[CoverageItem],
    *,
    store: PriceStore,
    quotes: Callable[[list[str]], Mapping[str, Quote]],
    currency_of: Callable[[str], str | None],
    rate_to_eur: Callable[[str], float | None],
    trade_date: date,
    clock: Callable[[], datetime] = _utcnow,
) -> PricesResult:
    started = clock()
    targets: dict[str, str] = {}  # Symbol -> ISIN, je Symbol einmal
    for item in items:
        if item.price_symbol and item.price_symbol not in targets:
            targets[item.price_symbol] = item.isin
    status = "ok"
    found: Mapping[str, Quote] = {}
    if targets:
        try:
            found = quotes(list(targets))
        except Exception:
            log.warning("Sammelabruf der Tageskurse gescheitert", exc_info=True)
            status = "failed"
    known = dict(store.known_currencies(list(found))) if found else {}
    closes: list[DailyClose] = []
    for symbol, isin in targets.items():
        quote = found.get(symbol)
        if quote is None:
            continue
        currency = known.get(symbol) or _safe_currency(currency_of, symbol)
        if not currency:
            log.warning("Keine Waehrung fuer %s - der Kurs fehlt", symbol)
            continue
        close, unit = to_major_unit(quote.close, currency)
        closes.append(DailyClose(isin, symbol, quote.trade_date, close, unit, currency))
    newest = max((c.trade_date for c in closes), default=trade_date)
    fx: list[FxDaily] = []
    for currency in sorted({c.currency for c in closes} - {EUR}):
        rate = _safe_rate(rate_to_eur, currency)
        if rate is not None and rate > 0:
            # Der Kurs von jetzt gilt fuer den angefragten Tag, nicht fuer den letzten Schlusskurs
            # (an einem Feiertag waere das der Vortag)
            fx.append(FxDaily(currency, trade_date, rate))
    priced = {c.isin for c in closes}
    missing = sorted({item.isin for item in items} - priced)
    run_id = store.write_prices(
        source=SOURCE,
        started_at=started,
        finished_at=clock(),
        status=status,
        closes=closes,
        fx=fx,
    )
    log.info("Tageskurse: %d Kurse, %d fehlen (Abruf #%d)", len(closes), len(missing), run_id)
    return PricesResult(run_id, newest, closes, fx, missing)


def _safe_currency(currency_of: Callable[[str], str | None], symbol: str) -> str | None:
    try:
        return currency_of(symbol)
    except Exception:
        log.warning("Waehrung von %s nicht abrufbar", symbol, exc_info=True)
        return None


def _safe_rate(rate_to_eur: Callable[[str], float | None], currency: str) -> float | None:
    try:
        return rate_to_eur(currency)
    except Exception:
        log.warning("Waehrungskurs %s nicht abrufbar", currency, exc_info=True)
        return None
