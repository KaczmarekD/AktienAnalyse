"""Ports von market-data: was die Anwendungsfaelle von der Aussenwelt brauchen."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Callable, Collection, Mapping, Sequence
    from datetime import date

    import pandas as pd

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


class SnapshotStore(Protocol):
    """Speicher von market-data: Abrufe, Universum, Fundamentaldaten, Zeitreihen-Stand."""

    def find_reusable_fetch(self, day: date, symbols: Collection[str]) -> int | None: ...

    def load_snapshots(self, fetch_run_id: int, symbols: Collection[str]) -> pd.DataFrame: ...

    def start_fetch(
        self, tickers: Sequence[Ticker], source: str, as_of: date | None = None
    ) -> int: ...

    def history_state(self, symbols: Collection[str]) -> Mapping[str, HistoryState]: ...

    def record_fundamentals(self, fetch_run_id: int, fund: Fundamentals) -> None: ...

    def finish_fetch(self, fetch_run_id: int, df: pd.DataFrame) -> None: ...


class Fetch(Protocol):
    """Die Abrufschleife mit fertig verdrahtetem Provider (``fetch_all`` ohne Provider)."""

    def __call__(
        self,
        tickers: list[Ticker],
        *,
        on_result: Callable[[Fundamentals], None],
        history: Mapping[str, HistoryState],
    ) -> pd.DataFrame: ...
