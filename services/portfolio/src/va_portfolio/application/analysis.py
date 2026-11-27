"""Eingabe der Depot-Analyse aus den Kopien der Marktdaten (D4.4).

Die Stammdaten liegen als ganzes ``SecurityV1`` in ``security_view`` (D3.4). Hier werden daraus
die Daten, die ``va_portfolio.domain.analysis`` braucht: ETF (TER, Fondswaehrung, Gewichte,
groesste Positionen) und Anleihe (Kupon, Faelligkeit, CFI). Ein Eintrag, der sich nicht lesen
laesst, fehlt nur in der Analyse. Die Positionen eines ETF tragen die Kennung der Quelle
(``EtfHoldingV1.isin`` ist nicht geprueft); ohne die Form einer ISIN zaehlen sie wie ohne ISIN.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from decimal import Decimal
from typing import Any

from pydantic import ValidationError

from va_contracts.securities import ISIN_PATTERN, SecurityV1

from ..domain.analysis import AnalysisInput, BondData, EtfData
from ..domain.bonds import BondTerms
from ..domain.funds import Fund, FundHolding
from ..domain.valuation import DepotValue, Score

log = logging.getLogger(__name__)


def _security(isin: str, payload: Mapping[str, Any]) -> SecurityV1 | None:
    try:
        return SecurityV1.model_validate(payload)
    except ValidationError:
        log.warning("Stammdaten von %s nicht lesbar - fehlen in der Analyse", isin)
        return None


def _isin(value: str | None) -> str | None:
    """Die Kennung einer Position, wenn sie die Form einer ISIN hat (Futures, Kasse: nein)."""
    return value if value and re.fullmatch(ISIN_PATTERN, value) else None


def securities(payloads: Mapping[str, Mapping[str, Any]]) -> dict[str, SecurityV1]:
    return {
        isin: security
        for isin, payload in payloads.items()
        if (security := _security(isin, payload)) is not None
    }


def fund_isins(found: Mapping[str, SecurityV1]) -> set[str]:
    """ISINs der bekannten Positionen der ETFs, fuer ihre Scores (Look-through-Score)."""
    return {
        isin
        for security in found.values()
        if security.etf is not None
        for holding in security.etf.top_holdings
        if (isin := _isin(holding.isin))
    }


def analysis_input(
    value: DepotValue, found: Mapping[str, SecurityV1], scores: Mapping[str, Score]
) -> AnalysisInput:
    etfs: dict[str, EtfData] = {}
    bonds: dict[str, BondData] = {}
    names: dict[str, str] = {}
    for isin, security in found.items():
        if security.etf is not None:
            etf = security.etf
            etfs[isin] = EtfData(
                as_of=etf.as_of,
                ter=etf.ter,
                currency=etf.fund_currency or security.currency,
                sectors=etf.sectors,
                countries=etf.countries,
                holdings=Fund(
                    holdings=tuple(FundHolding(_isin(h.isin), h.weight) for h in etf.top_holdings),
                    complete=etf.complete,
                ),
            )
            names.update({i: h.name for h in etf.top_holdings if (i := _isin(h.isin))})
        if security.bond is not None:
            bond = security.bond
            bonds[isin] = BondData(
                BondTerms(coupon=bond.coupon, maturity=bond.maturity, floating=bond.floating),
                security.cfi,
            )
    composites = {i: s.composite_score for i, s in scores.items() if s.composite_score is not None}
    return AnalysisInput(value=value, etfs=etfs, bonds=bonds, composites=composites, names=names)


def fund_sizes(found: Mapping[str, SecurityV1], fx: Mapping[str, Decimal]) -> dict[str, float]:
    """D5.2: Fondsvolumen in Mio. EUR, nur aus Anbieterdateien (iShares; HIN-E03)."""
    sizes: dict[str, float] = {}
    for isin, security in found.items():
        etf = security.etf
        if etf is None or etf.source != "ishares" or etf.fund_size is None:
            continue
        currency = etf.fund_currency or security.currency or "EUR"
        rate = Decimal(1) if currency == "EUR" else fx.get(currency)
        if rate is not None:
            sizes[isin] = etf.fund_size * float(rate)
    return sizes
