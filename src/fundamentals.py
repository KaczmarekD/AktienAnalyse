"""Datenmodell fuer Fundamentaldaten einer Aktie.

Aufgeteilt in semantische Sub-Klassen, damit Code-Leser sofort sehen:
"das ist Bewertung", "das ist Qualitaet", "das sind Stammdaten".
``to_flat_dict()`` macht aus dem geschachtelten Objekt einen flachen
Dictionary, der direkt in einen pandas DataFrame oder eine CSV passt.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class Identity:
    symbol: str
    name: str
    index: str
    sector: str | None = None
    industry: str | None = None
    currency: str | None = None


@dataclass
class MarketData:
    price: float | None = None
    market_cap: float | None = None
    enterprise_value: float | None = None
    shares_outstanding: float | None = None


@dataclass
class ValueMetrics:
    """Bewertungsmultiplikatoren - 'niedrig = guenstig' (ausser Yields)."""

    ev_ebit: float | None = None
    pe_ratio: float | None = None
    pb_ratio: float | None = None
    p_fcf: float | None = None
    dividend_yield: float | None = None  # Dezimal, 0.03 = 3 %
    buyback_yield: float | None = None
    shareholder_yield: float | None = None  # dividend + buyback


@dataclass
class QualityMetrics:
    """Profitabilitaet, Margen, Verschuldung, Stabilitaet."""

    roic: float | None = None
    roa: float | None = None
    fcf_margin: float | None = None
    gross_margin: float | None = None
    operating_margin: float | None = None
    net_debt_ebitda: float | None = None
    debt_to_equity: float | None = None
    earnings_stability: float | None = None  # 0..1, hoeher = stabiler


@dataclass
class Growth:
    revenue_growth_5y: float | None = None
    eps_growth_5y: float | None = None


@dataclass
class Fundamentals:
    """Vollstaendiger Datensatz pro Aktie."""

    identity: Identity
    market: MarketData = field(default_factory=MarketData)
    value: ValueMetrics = field(default_factory=ValueMetrics)
    quality: QualityMetrics = field(default_factory=QualityMetrics)
    growth: Growth = field(default_factory=Growth)
    errors: list[str] = field(default_factory=list)

    @property
    def symbol(self) -> str:
        return self.identity.symbol

    def to_flat_dict(self) -> dict[str, Any]:
        """Flacht alle Sub-Dataclasses fuer DataFrame/CSV-Export."""
        flat: dict[str, Any] = {}
        flat.update(asdict(self.identity))
        flat.update(asdict(self.market))
        flat.update(asdict(self.value))
        flat.update(asdict(self.quality))
        flat.update(asdict(self.growth))
        flat["errors"] = "; ".join(self.errors) if self.errors else ""
        return flat
