"""Uebergang bis P1.8: verdrahtet die Universum-Quellen fuer den Batch.

Kette iShares -> Deka -> Fallback-CSV (``va_market_data.application.universe``), Quellen
in ``va_market_data.adapters``. Hier steht nur, wo die Fallback-CSV im Repo liegt.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from va_market_data.adapters.csv_universe import load_fallback
from va_market_data.adapters.deka import DekaSource
from va_market_data.adapters.ishares import IsharesSource
from va_market_data.adapters.openfigi import resolve_isins_openfigi
from va_market_data.application.universe import load_universe as _load_universe
from va_market_data.domain.universe import Universe, UniverseConfig

DEFAULT_FALLBACK_CSV = Path(__file__).resolve().parent.parent / "data" / "dax_mdax_fallback.csv"


def load_universe(
    cfg: UniverseConfig | None = None,
    fallback_csv: Path | None = None,
    force_fallback: bool = False,
    today: date | None = None,
) -> Universe:
    """DAX + MDAX aus der ersten gueltigen Quelle, dedupliziert; Schnittstelle wie vor P1.4."""
    return _load_universe(
        [IsharesSource(), DekaSource(resolver=resolve_isins_openfigi)],
        load_fallback(fallback_csv or DEFAULT_FALLBACK_CSV),
        cfg or UniverseConfig(),
        today or date.today(),
        force_fallback=force_fallback,
    )
