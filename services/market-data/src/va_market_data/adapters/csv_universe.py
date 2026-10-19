"""Die Fallback-CSV (symbol,name,index[,isin]) - von Hand gepflegt, immer verfuegbar.

Der Pfad kommt vom Aufrufer: Installiert liegt dieses Modul in site-packages, nicht im Repo.
"""

from __future__ import annotations

import csv
import logging
from typing import TYPE_CHECKING

from ..domain.universe import Ticker

if TYPE_CHECKING:
    from pathlib import Path

log = logging.getLogger(__name__)


def load_fallback(path: Path) -> list[Ticker]:
    """Liest die Fallback-Liste. Fehlt die Datei, ist sie leer (und das wird geloggt)."""
    if not path.exists():
        log.error("Fallback-CSV nicht gefunden: %s", path)
        return []
    with path.open(encoding="utf-8") as f:
        return [
            Ticker(
                symbol=row["symbol"].strip(),
                name=row["name"].strip(),
                index=row["index"].strip(),
                isin=(row.get("isin") or "").strip() or None,
            )
            for row in csv.DictReader(f)
            if row.get("symbol")
        ]
