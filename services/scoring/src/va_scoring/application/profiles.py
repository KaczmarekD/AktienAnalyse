"""Woher ein Bewertungslauf seine Parameter nimmt (P2b.3, ADR-0009)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..domain.profile import ActiveProfile, ScoringProfileParams

if TYPE_CHECKING:
    from collections.abc import Mapping

    from ..domain.scoring import ScoringConfig
    from .ports import ProfileStore


class StoredProfile:
    """Die aktive Profil-Version aus der Datenbank.

    Gibt es noch keine, entsteht "Standard" aus den Startwerten (ENV). Jeder Aufruf liest neu:
    Ein aktiviertes Profil gilt ab dem naechsten Bewertungslauf, ohne Neustart. Ungueltige
    gespeicherte Parameter scheitern laut, statt still mit anderen Werten zu rechnen.
    """

    def __init__(self, store: ProfileStore, start_params: Mapping[str, Any]) -> None:
        self._store = store
        self._start_params = dict(start_params)

    def active(self) -> ActiveProfile:
        ref = self._store.ensure_default_profile(self._start_params)
        params = ScoringProfileParams.model_validate(ref.params)
        return ActiveProfile(params.to_config(), ref)


class FixedProfile:
    """Eine feste Konfiguration ohne gespeichertes Profil, etwa fuer das Replay."""

    def __init__(self, config: ScoringConfig) -> None:
        self._config = config

    def active(self) -> ActiveProfile:
        return ActiveProfile(self._config)
