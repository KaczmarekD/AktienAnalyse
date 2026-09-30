"""Konsensschaetzungen der Analysten als Rohdaten (ADR-0010, Paket F1.1).

Nur speichern, nicht auswerten: Jede Art landet unveraendert als JSONB in
``market_data.consensus_snapshot``. Welche Kennzahlen daraus entstehen, entscheidet
ADR-0011. Dieses Modul kennt yfinance nicht - den Abruf macht ``data_fetcher``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Literal

import pandas as pd

from .db.serialization import json_safe

# Attribute von ``yfinance.Ticker`` - zugleich die erlaubten Werte der Spalte ``kind``
CONSENSUS_KINDS: tuple[str, ...] = (
    "eps_trend",
    "eps_revisions",
    "earnings_estimate",
    "revenue_estimate",
    "growth_estimates",
    "analyst_price_targets",
)
CONSENSUS_STATUSES: tuple[str, ...] = ("ok", "empty", "error")
MAX_ERROR_LENGTH = 500

ConsensusStatus = Literal["ok", "empty", "error"]


@dataclass(frozen=True)
class ConsensusEntry:
    """Ergebnis je Art: ``ok`` mit Payload, ``empty`` ohne Daten, ``error`` mit Fehlertext."""

    status: ConsensusStatus
    payload: Any  # JSON-Struktur, ``None`` ausser bei ``ok``
    error: str | None


def to_payload(value: Any) -> Any:
    """yfinance-Antwort -> JSON-taugliche Struktur, leere Antwort -> ``None``.

    DataFrames werden zu ``{Zeile: {Spalte: Wert}}``, z.B. ``payload["+1y"]["current"]``.
    So bleiben die Snapshots per SQL direkt abfragbar. Nur bei doppelten
    Zeilenbeschriftungen bleibt das Split-Format (``index``/``columns``/``data``), weil
    sonst Zeilen verloren gingen.
    """
    if value is None:
        return None
    if isinstance(value, pd.DataFrame):
        if value.empty:
            return None
        if value.index.is_unique:
            return json_safe(value.to_dict(orient="index"))
        split = value.to_dict(orient="split")
        return json_safe(
            {
                "index": list(split["index"]),
                "columns": list(split["columns"]),
                "data": split["data"],
            }
        )
    if isinstance(value, Mapping):
        return json_safe(dict(value)) if value else None
    return json_safe(value)


def collect_consensus(getters: Mapping[str, Callable[[], Any]]) -> dict[str, ConsensusEntry]:
    """Ruft jede Art einzeln ab. Ein Fehler kostet nur diese Art, nie den Titel."""
    entries: dict[str, ConsensusEntry] = {}
    for kind, get in getters.items():
        try:
            payload = to_payload(get())
        except Exception as e:
            error = f"{type(e).__name__}: {e}"[:MAX_ERROR_LENGTH]
            entries[kind] = ConsensusEntry("error", None, error)
            continue
        if payload is None:
            entries[kind] = ConsensusEntry("empty", None, None)
        else:
            entries[kind] = ConsensusEntry("ok", payload, None)
    return entries
