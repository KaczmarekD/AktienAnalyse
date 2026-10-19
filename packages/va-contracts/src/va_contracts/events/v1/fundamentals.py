"""Fundamentaldaten eines Titels, wie market-data sie im Snapshot-Event mitschickt.

Dieselben Gruppen und Feldnamen wie die Dataclasses in ``src.fundamentals``, aber ohne
Rohdaten. Flach (``to_flat``) entsprechen sie den Spalten von DataFrame und CSV.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import AwareDatetime, Field

from ...base import Contract

# Mehrere Fehler eines Titels stehen flach (DataFrame, CSV) als ein Text
ERRORS_SEPARATOR = "; "


class IdentityV1(Contract):
    symbol: str
    name: str
    index: str
    sector: str | None = None
    industry: str | None = None
    currency: str | None = None  # Handelswaehrung (Kurs, Marktkapitalisierung)
    financial_currency: str | None = None  # Berichtswaehrung der Abschluesse


class MarketDataV1(Contract):
    price: float | None = None
    market_cap: float | None = None
    enterprise_value: float | None = None
    shares_outstanding: float | None = None


class ValueMetricsV1(Contract):
    ev_ebit: float | None = None
    pe_ratio: float | None = None
    pb_ratio: float | None = None
    p_fcf: float | None = None
    dividend_yield: float | None = None  # Dezimal, 0.03 = 3 %
    buyback_yield: float | None = None
    shareholder_yield: float | None = None


class QualityMetricsV1(Contract):
    roic: float | None = None
    roa: float | None = None
    fcf_margin: float | None = None
    gross_margin: float | None = None
    operating_margin: float | None = None
    net_debt_ebitda: float | None = None
    debt_to_equity: float | None = None
    earnings_stability: float | None = None  # 0..1, hoeher = stabiler


class GrowthV1(Contract):
    revenue_growth_5y: float | None = None
    eps_growth_5y: float | None = None


class ProvenanceV1(Contract):
    fetched_at: AwareDatetime | None = None
    fiscal_period_end: date | None = None  # Geschaeftsjahr des juengsten Abschlusses
    statement_fx: float | None = None  # Faktor Berichts- -> Handelswaehrung


class FundamentalsV1(Contract):
    """Ein Titel. Fehlende Werte sind ``None``; Fehler des Abrufs stehen in ``errors``."""

    identity: IdentityV1
    market: MarketDataV1 = MarketDataV1()
    value: ValueMetricsV1 = ValueMetricsV1()
    quality: QualityMetricsV1 = QualityMetricsV1()
    growth: GrowthV1 = GrowthV1()
    provenance: ProvenanceV1 = ProvenanceV1()
    errors: list[str] = Field(default_factory=list)

    @property
    def symbol(self) -> str:
        return self.identity.symbol

    def to_flat(self) -> dict[str, Any]:
        """Eine Zeile wie in DataFrame und CSV: alle Gruppen nebeneinander, Fehler als Text."""
        flat: dict[str, Any] = {}
        for group in (
            self.identity,
            self.market,
            self.value,
            self.quality,
            self.growth,
            self.provenance,
        ):
            flat.update(group.model_dump())
        flat["errors"] = ERRORS_SEPARATOR.join(self.errors)
        return flat
