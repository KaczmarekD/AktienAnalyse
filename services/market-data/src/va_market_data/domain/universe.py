"""DAX/MDAX-Universum: Titel, Validierungsregeln und Abgleich mit der Fallback-CSV.

Die Quellen (iShares, Deka, OpenFIGI, CSV) liegen in ``adapters``, die Kette in
``application.universe``. Hintergrund: docs/research/dax-mdax-datenquellen/bericht.md
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

FALLBACK_SOURCE = "Fallback-CSV"
# Symbole im ganzen System sind Yahoo-Symbole fuer Xetra
YAHOO_SUFFIX = ".DE"


class SourceError(Exception):
    """Eine Live-Quelle ist nicht erreichbar oder liefert ungueltige Daten."""


@dataclass(frozen=True)
class Ticker:
    symbol: str
    name: str
    index: str  # "DAX" oder "MDAX"
    isin: str | None = None


@dataclass
class UniverseConfig:
    expected_counts: dict[str, int] = field(default_factory=lambda: {"DAX": 40, "MDAX": 50})
    max_age_days: int = 10
    timeout: float = 30.0


@dataclass
class Universe:
    tickers: list[Ticker]
    source: str  # "iShares" | "Deka" | FALLBACK_SOURCE
    as_of: date | None = None
    added: list[Ticker] = field(default_factory=list)  # in Quelle, nicht in CSV
    removed: list[Ticker] = field(default_factory=list)  # in CSV, nicht in Quelle


def check_count(count: int, index: str, source: str, cfg: UniverseConfig) -> None:
    """Eine Live-Quelle muss genau die erwartete Anzahl Aktien je Index liefern."""
    expected = cfg.expected_counts[index]
    if count != expected:
        msg = f"{source} {index}: {count} statt {expected} Aktien"
        raise SourceError(msg)


def dedupe(tickers: list[Ticker]) -> list[Ticker]:
    """Je Symbol der erste Eintrag."""
    seen: set[str] = set()
    result: list[Ticker] = []
    for t in tickers:
        if t.symbol in seen:
            continue
        seen.add(t.symbol)
        result.append(t)
    return result


def _diff_key(t: Ticker) -> tuple[str, str, str | None]:
    # Symbol + Index + ISIN: erkennt auch Auf-/Abstiege und ISIN-Wechsel
    return (t.symbol, t.index, t.isin)


def diff(live: list[Ticker], fallback: list[Ticker]) -> tuple[list[Ticker], list[Ticker]]:
    """(neu in der Quelle, nur noch in der CSV)."""
    live_keys = {_diff_key(t) for t in live}
    fallback_keys = {_diff_key(t) for t in fallback}
    added = [t for t in live if _diff_key(t) not in fallback_keys]
    removed = [t for t in fallback if _diff_key(t) not in live_keys]
    return added, removed
