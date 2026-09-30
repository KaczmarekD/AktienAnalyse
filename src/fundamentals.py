"""Datenmodell fuer Fundamentaldaten einer Aktie.

Aufgeteilt in semantische Sub-Klassen, damit Code-Leser sofort sehen:
"das ist Bewertung", "das ist Qualitaet", "das sind Stammdaten".
``to_flat_dict()`` macht aus dem geschachtelten Objekt einen flachen
Dictionary, der direkt in einen pandas DataFrame oder eine CSV passt.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import pandas as pd

# Mehrere Fehler eines Titels stehen in DataFrame und CSV als ein Text
ERRORS_SEPARATOR = "; "


def join_errors(errors: object) -> str:
    """Fehlerliste (Liste oder Tupel) -> ein Text; leer oder fehlend -> ``""``."""
    if isinstance(errors, list | tuple) and errors:
        return ERRORS_SEPARATOR.join(str(e) for e in errors)
    return ""


@dataclass
class Identity:
    symbol: str
    name: str
    index: str
    sector: str | None = None
    industry: str | None = None
    currency: str | None = None  # Handelswaehrung (Kurs, Marktkapitalisierung)
    financial_currency: str | None = None  # Berichtswaehrung der Abschluesse


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
class Provenance:
    """Woher und von wann die Werte stammen - Grundlage fuer Zeitreihen."""

    fetched_at: datetime | None = None
    fiscal_period_end: date | None = None  # Geschaeftsjahr des juengsten Abschlusses
    statement_fx: float | None = None  # Faktor Berichts- -> Handelswaehrung (1.0 = gleich)


@dataclass
class RawFetch:
    """Unveraenderte Rohdaten des Providers. Wird gespeichert, aber nie geflacht."""

    provider: str
    provider_version: str
    info: dict[str, Any]
    statements: dict[str, pd.DataFrame | None]  # "income" / "balance" / "cashflow"


@dataclass
class Fundamentals:
    """Vollstaendiger Datensatz pro Aktie."""

    identity: Identity
    market: MarketData = field(default_factory=MarketData)
    value: ValueMetrics = field(default_factory=ValueMetrics)
    quality: QualityMetrics = field(default_factory=QualityMetrics)
    growth: Growth = field(default_factory=Growth)
    provenance: Provenance = field(default_factory=Provenance)
    errors: list[str] = field(default_factory=list)
    raw: RawFetch | None = field(default=None, repr=False)

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
        flat.update(asdict(self.provenance))
        flat["errors"] = join_errors(self.errors)
        return flat
