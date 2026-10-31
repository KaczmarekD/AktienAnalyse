"""Ports von scoring."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from collections.abc import Mapping

    import pandas as pd

    from ..domain.profile import ActiveProfile, ProfileVersionRef
    from ..domain.scoring import ScoringConfig


class ScoringStore(Protocol):
    """Speichert einen Bewertungslauf und liefert seine ID (``scoring.scoring_run.id``).

    ``df_all``: alle Titel des Snapshots, ``scored``: die Ausgabe von ``score()``. Titel,
    die am Groessenfilter scheitern, werden mit ``passed_filter=False`` gespeichert.
    ``profile``: die Profil-Version, mit der gerechnet wurde (P2b.3); fehlt im Replay.
    """

    def record_scoring(
        self,
        fetch_run_id: int,
        df_all: pd.DataFrame,
        scored: pd.DataFrame,
        cfg: ScoringConfig,
        profile: ProfileVersionRef | None = None,
    ) -> int: ...


class ProfileStore(Protocol):
    """Die gespeicherten Scoring-Profile (ADR-0009)."""

    def ensure_default_profile(self, params: Mapping[str, Any]) -> ProfileVersionRef:
        """Legt das Profil "Standard" einmalig mit ``params`` an und liefert die aktive Version.

        Die Werte aus ENV dienen nur beim ersten Mal als Startwerte (ADR-0009, P2b.1).
        """
        ...


class ProfileSource(Protocol):
    """Woher ein Bewertungslauf seine Parameter nimmt (P2b.3)."""

    def active(self) -> ActiveProfile: ...
