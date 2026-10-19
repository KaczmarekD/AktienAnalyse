"""Gemeinsame Basis aller Contracts."""

from __future__ import annotations

import math
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field

# IDs aus Postgres (bigint, Identity ab 1)
PositiveId = Annotated[int, Field(ge=1)]


class Contract(BaseModel):
    """Basis fuer Events und ihre Bestandteile.

    - unveraenderlich: ein Event wird nach dem Erzeugen nicht mehr angepasst. Das gilt
      flach: Listen und Dicts im Event bitte ebenfalls nicht veraendern.
    - unbekannte Felder werden ignoriert: Ein aelterer Empfaenger versteht ein Event, das
      additiv um Felder erweitert wurde (Regeln in docs/architecture/events.md). Erzeugt
      werden Events deshalb per Konstruktor - dort faengt Pyright Tippfehler ab, die
      ``model_validate`` still ignorieren wuerde.
    - NaN und inf sind kein gueltiges JSON. Fehlt ein Wert, steht dort ``None``.
    """

    model_config = ConfigDict(frozen=True, extra="ignore", allow_inf_nan=False)


def missing_to_none(value: Any) -> Any:
    """NaN (wie es pandas fuer fehlende Werte liefert) und +-inf -> ``None``, alles andere bleibt.

    inf kommt z. B. aus einer Division durch 0 in Altdaten. Es ist kein gueltiges JSON und
    soll nur dieses eine Feld kosten, nicht den ganzen Titel oder Lauf.
    """
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value
