"""Replay-Quelle (U5): Universum und Fundamentaldaten aus gespeicherten Snapshot-Zeilen.

Fuer den lokalen End-to-End-Test (docs/architecture/umgebungen.md). Kein Aufruf von iShares,
Deka, OpenFIGI oder Yahoo, das Ergebnis steht fest. Die Zeilen haben die Spalten von
``Fundamentals.to_flat_dict`` wie die Snapshots einer Replay-Fixture. Rohdaten gibt es keine:
Abschluesse, Konsens, Quartale, Aktienanzahl und Kurse bleiben leer.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from va_contracts.events.v1 import FundamentalsV1

from ..domain.fundamentals import (
    Fundamentals,
    Growth,
    Identity,
    MarketData,
    Provenance,
    QualityMetrics,
    ValueMetrics,
)
from ..domain.universe import Ticker, Universe, dedupe

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping
    from pathlib import Path

    from ..domain.history import HistoryState

# Kennzeichnung in market_data.fetch_run: nie mit einem echten Abruf zu verwechseln
PROVIDER = "replay"
SOURCE = "Replay"


def fundamentals_from_flat(row: Mapping[Any, Any]) -> Fundamentals:
    """Zurueck aus einer flachen Zeile. Typen, NaN und Fehlertext wie im Contract."""
    contract = FundamentalsV1.from_flat(row)
    return Fundamentals(
        identity=Identity(**contract.identity.model_dump()),
        market=MarketData(**contract.market.model_dump()),
        value=ValueMetrics(**contract.value.model_dump()),
        quality=QualityMetrics(**contract.quality.model_dump()),
        growth=Growth(**contract.growth.model_dump()),
        provenance=Provenance(**contract.provenance.model_dump()),
        errors=list(contract.errors),
    )


class ReplayFundamentals:
    """``FundamentalsProvider`` aus gespeicherten Zeilen, je Symbol die erste."""

    def __init__(self, rows: Iterable[Mapping[str, Any]]) -> None:
        self._rows: dict[str, Mapping[str, Any]] = {}
        for row in rows:
            self._rows.setdefault(str(row["symbol"]), row)

    def fetch(self, ticker: Ticker, history: HistoryState | None = None) -> Fundamentals:  # noqa: ARG002 - Signatur des Ports
        row = self._rows.get(ticker.symbol)
        if row is None:
            # Wie ein gescheiterter Abruf: Der Titel faellt aus dem Ranking, der Lauf geht weiter
            return Fundamentals(
                identity=Identity(ticker.symbol, ticker.name, ticker.index),
                errors=[f"replay: kein Snapshot fuer {ticker.symbol}"],
            )
        return fundamentals_from_flat(row)


def load_replay_rows(path: Path) -> list[dict[str, Any]]:
    """Die Snapshot-Zeilen einer Replay-Fixture (``tests/fixtures/replay/*.json``, P5.1a).

    Die Fixture haelt sie als Tabelle (``columns`` und ``rows``). Gelesen wird nur dieser Teil,
    ohne das Werkzeug der Replay-Regression (``src.regression``).
    """
    table = json.loads(path.read_text(encoding="utf-8"))["snapshots"]
    columns = [str(c) for c in table["columns"]]
    return [dict(zip(columns, row, strict=True)) for row in table["rows"]]


def replay_universe(rows: Iterable[Mapping[str, Any]], fallback: list[Ticker]) -> Universe:
    """Die Titel der Zeilen in ihrer Reihenfolge; die ISIN aus der Fallback-CSV.

    Kein Abgleich mit der CSV: Replay ist keine Live-Quelle, ein Hinweis „Fallback-CSV pflegen“
    waere hier falsch.
    """
    isins = {t.symbol: t.isin for t in fallback}
    tickers = [
        Ticker(
            str(row["symbol"]), str(row["name"]), str(row["index"]), isins.get(str(row["symbol"]))
        )
        for row in rows
    ]
    return Universe(tickers=dedupe(tickers), source=SOURCE)
