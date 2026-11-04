"""Settings von market-data (P5.1a): nur was der Abruf braucht. Der Batch erbt sie."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field, FilePath

from va_platform.service import ServiceSettings


class MarketDataSettings(ServiceSettings):
    universe: Literal["DAX_MDAX", "DAX_ONLY"] = "DAX_MDAX"
    # Fallback, wenn eine Gesellschaft ihre effektive Steuerquote nicht hergibt (ROIC)
    default_tax_rate: float = Field(default=0.27, ge=0, le=0.6)
    # Pfad zu einer Replay-Fixture (tests/fixtures/replay/): Universum und Fundamentaldaten
    # kommen dann aus der Datei statt von iShares, Deka, OpenFIGI und Yahoo. Nur lokal (U5).
    replay_source: FilePath | None = None
    # Von Hand gepflegtes Sicherheitsnetz des Universums, im Image unter /app/data
    fallback_csv: Path = Path("data/dax_mdax_fallback.csv")
