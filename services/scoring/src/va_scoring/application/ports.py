"""Ports von scoring."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    import pandas as pd

    from ..domain.scoring import ScoringConfig


class ScoringStore(Protocol):
    """Speichert einen Bewertungslauf und liefert seine ID (``scoring.scoring_run.id``).

    ``df_all``: alle Titel des Snapshots, ``scored``: die Ausgabe von ``score()``. Titel,
    die am Groessenfilter scheitern, werden mit ``passed_filter=False`` gespeichert.
    """

    def record_scoring(
        self, fetch_run_id: int, df_all: pd.DataFrame, scored: pd.DataFrame, cfg: ScoringConfig
    ) -> int: ...
