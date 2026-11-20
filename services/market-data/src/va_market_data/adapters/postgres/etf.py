"""ETF-Zusammensetzungen im Schema ``market_data`` (D2.4, Port ``CompositionStore``).

Nur ``INSERT`` und ``SELECT``: je ISIN, Quelle und Stand eine Zeile (``ON CONFLICT DO NOTHING``).
Gueltig ist der juengste Stand, bei gleichem Stand die zuletzt gespeicherte Zeile. Die Positionen
liegen spaltenweise im JSONB: Ein Anleihe-ETF hat ueber 4.000, jede Woche ein neuer Stand.
"""

from __future__ import annotations

from dataclasses import asdict, fields
from typing import TYPE_CHECKING, Any

from sqlalchemy import text as sql
from sqlalchemy.dialects.postgresql import insert

from ...domain.etf import EtfComposition, FundFacts, Holding
from .models import EtfCompositionRow

if TYPE_CHECKING:
    from datetime import datetime

    from sqlalchemy import Engine

HOLDING_COLUMNS = tuple(f.name for f in fields(Holding))
FACT_FIELDS = tuple(f.name for f in fields(FundFacts))

_LATEST = """
SELECT isin, source, as_of, complete, facts, holdings, weights
FROM market_data.etf_composition
WHERE isin = :isin AND (complete OR NOT :complete_only)
ORDER BY as_of DESC, id DESC
LIMIT 1
"""


def holdings_columns(holdings: tuple[Holding, ...]) -> dict[str, list[Any]]:
    return {column: [getattr(h, column) for h in holdings] for column in HOLDING_COLUMNS}


def holdings_from_columns(payload: dict[str, Any]) -> tuple[Holding, ...]:
    size = len(payload.get("name") or [])
    columns = {c: payload.get(c) or [None] * size for c in HOLDING_COLUMNS}
    return tuple(
        Holding(**dict(zip(HOLDING_COLUMNS, row, strict=True)))
        for row in zip(*columns.values(), strict=True)
    )


class PostgresEtfStore:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def write_composition(self, composition: EtfComposition, *, at: datetime) -> bool:
        with self._engine.begin() as conn:
            inserted = conn.execute(
                insert(EtfCompositionRow)
                .values(
                    isin=composition.isin,
                    source=composition.source,
                    as_of=composition.as_of,
                    complete=composition.complete,
                    holdings_count=composition.holdings_count,
                    facts=asdict(composition.facts),
                    holdings=holdings_columns(composition.holdings),
                    weights={
                        "sector": composition.sectors,
                        "country": composition.countries,
                        "asset_class": composition.asset_classes,
                    },
                    fetched_at=at,
                )
                .on_conflict_do_nothing(constraint="uq_etf_composition_isin_source_as_of")
                .returning(EtfCompositionRow.id)
            ).scalar()
        return inserted is not None

    def latest_composition(
        self, isin: str, *, complete_only: bool = False
    ) -> EtfComposition | None:
        """Der juengste Stand; ``complete_only``: der juengste mit allen Positionen."""
        with self._engine.connect() as conn:
            row = conn.execute(sql(_LATEST), {"isin": isin, "complete_only": complete_only}).first()
        if row is None:
            return None
        weights = row.weights or {}
        facts = {k: v for k, v in (row.facts or {}).items() if k in FACT_FIELDS}
        return EtfComposition(
            isin=row.isin,
            source=row.source,
            as_of=row.as_of,
            complete=row.complete,
            facts=FundFacts(**facts),
            holdings=holdings_from_columns(row.holdings or {}),
            sectors=dict(weights.get("sector") or {}),
            countries=dict(weights.get("country") or {}),
            asset_classes=dict(weights.get("asset_class") or {}),
        )
