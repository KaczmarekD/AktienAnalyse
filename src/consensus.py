"""Konsensschaetzungen der Analysten als Rohdaten (ADR-0010, Paket F1.1).

Nur speichern, nicht auswerten: Jede Art landet unveraendert als JSONB in
``market_data.consensus_snapshot``. Welche Kennzahlen daraus entstehen, entscheidet
ADR-0011. Dieses Modul kennt yfinance nicht - den Abruf macht ``data_fetcher``
(``CONSENSUS_FIELDS`` ordnet dort jeder Art ihr yfinance-Attribut zu).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Literal

import pandas as pd

from .db.serialization import json_safe, to_python

# Stabile Namen der Arten - zugleich die erlaubten Werte der Spalte ``kind``
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
    """Ergebnis je Art.

    - ``ok``: Payload vorhanden.
    - ``empty``: keine Daten erhalten, in der Regel keine Analystenabdeckung.
    - ``error``: Abruf gescheitert oder uebersprungen, der Grund steht in ``error``.
    """

    status: ConsensusStatus
    payload: Any  # JSON-Struktur, ``None`` ausser bei ``ok``
    error: str | None


def to_payload(value: Any) -> Any:
    """yfinance-Antwort -> JSON-taugliche Struktur, leere Antwort -> ``None``.

    DataFrames werden zu ``{Zeile: {Spalte: Wert}}``, z.B. ``payload["+1y"]["current"]``.
    So bleiben die Snapshots per SQL direkt abfragbar. Bei doppelten Zeilen- oder
    Spaltenbeschriftungen gingen dabei Werte verloren. Dann bleibt das Split-Format,
    erkennbar an ``"format": "split"``.
    """
    if value is None:
        return None
    if isinstance(value, pd.DataFrame):
        if value.empty:
            return None
        if value.index.is_unique and value.columns.is_unique:
            return json_safe(value.to_dict(orient="index"))
        return json_safe(
            {
                "format": "split",
                "index": list(value.index),
                "columns": list(value.columns),
                "data": value.to_numpy(dtype=object).tolist(),
            }
        )
    if isinstance(value, Mapping):
        return json_safe(dict(value)) if value else None
    return json_safe(value)


def collect_consensus(
    getters: Mapping[str, Callable[[], Any]],
    *,
    stop_after: Callable[[Exception], bool] | None = None,
) -> dict[str, ConsensusEntry]:
    """Ruft jede Art einzeln ab. Ein Fehler kostet nur diese Art, nie den Titel.

    Trifft ``stop_after`` auf einen Fehler zu (etwa ein Rate-Limit), werden die
    restlichen Arten nicht mehr abgefragt, sondern als uebersprungen vermerkt.
    """
    entries: dict[str, ConsensusEntry] = {}
    stopped_by: Exception | None = None
    for kind, get in getters.items():
        if stopped_by is not None:
            reason = f"uebersprungen nach {type(stopped_by).__name__}"
            entries[kind] = ConsensusEntry("error", None, reason)
            continue
        try:
            payload = to_payload(get())
        except Exception as e:
            entries[kind] = ConsensusEntry("error", None, _error_text(e))
            if stop_after is not None and stop_after(e):
                stopped_by = e
            continue
        if payload is None:
            entries[kind] = ConsensusEntry("empty", None, None)
        else:
            entries[kind] = ConsensusEntry("ok", payload, None)
    return entries


def _error_text(error: Exception) -> str:
    """Kurz und DB-tauglich: PostgreSQL lehnt NUL-Zeichen in TEXT ab."""
    return str(to_python(f"{type(error).__name__}: {error}"))[:MAX_ERROR_LENGTH]
