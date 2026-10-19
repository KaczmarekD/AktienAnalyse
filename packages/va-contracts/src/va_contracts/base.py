"""Gemeinsame Basis aller Contracts."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class Contract(BaseModel):
    """Basis fuer Events und ihre Bestandteile.

    - unveraenderlich: ein Event wird nach dem Erzeugen nicht mehr angepasst
    - unbekannte Felder werden ignoriert: Ein aelterer Empfaenger versteht ein Event, das
      additiv um Felder erweitert wurde (Regeln in docs/architecture/events.md)
    - NaN und inf sind kein gueltiges JSON. Fehlt ein Wert, steht dort ``None``.
    """

    model_config = ConfigDict(frozen=True, extra="ignore", allow_inf_nan=False)
