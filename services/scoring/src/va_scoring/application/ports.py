"""Ports von scoring."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from collections.abc import Mapping

    import pandas as pd

    from ..domain.profile import ProfileVersionRef
    from ..domain.scoring import ScoringConfig


class ScoringStore(Protocol):
    """Speichert einen Bewertungslauf und liefert seine ID (``scoring.scoring_run.id``).

    ``df_all``: alle Titel des Snapshots, ``scored``: die Ausgabe von ``score()``. Titel,
    die am Groessenfilter scheitern, werden mit ``passed_filter=False`` gespeichert.
    """

    def record_scoring(
        self, fetch_run_id: int, df_all: pd.DataFrame, scored: pd.DataFrame, cfg: ScoringConfig
    ) -> int: ...

    def ensure_default_profile(self, params: Mapping[str, Any]) -> ProfileVersionRef:
        """Legt das Profil "Standard" einmalig mit ``params`` an und liefert die aktive Version.

        Die Werte aus ENV dienen nur beim ersten Mal als Startwerte (ADR-0009, P2b.1).
        """
        ...
