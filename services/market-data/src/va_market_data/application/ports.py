"""Ports von market-data: was die Anwendungsfaelle von der Aussenwelt brauchen."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from datetime import date

    from ..domain.fundamentals import Fundamentals
    from ..domain.history import HistoryState
    from ..domain.universe import Ticker, UniverseConfig


@dataclass(frozen=True)
class LiveUniverse:
    """Was eine Live-Quelle liefert: Titel und den Stichtag (Deka kennt keinen)."""

    tickers: list[Ticker]
    as_of: date | None


class UniverseSource(Protocol):
    """Eine Live-Quelle fuer das Universum (iShares, Deka).

    Wirft bei jedem Fehler; die Kette faellt dann zur naechsten Quelle durch.
    """

    name: str

    def load(self, fallback: list[Ticker], cfg: UniverseConfig, today: date) -> LiveUniverse: ...


class FundamentalsProvider(Protocol):
    """Fundamentaldaten eines Titels (heute Yahoo). Wirft nie: Fehler stehen in ``errors``."""

    def fetch(self, ticker: Ticker, history: HistoryState | None = None) -> Fundamentals: ...
