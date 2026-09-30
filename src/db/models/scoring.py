"""Schema ``scoring``: jede Bewertung eines Abrufs ist ein eigener, unveraenderlicher Lauf.

Ein Neu-Scoring alter Daten (andere Gewichte, neuer Faktor) erzeugt einen neuen
``scoring_run`` - bestehende Ergebnisse werden nie ueberschrieben.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Identity, func
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, in_values

SCORING_ORIGINS = ("live", "rescore", "import")


class ScoringRun(Base):
    __tablename__ = "scoring_run"
    __table_args__ = (
        CheckConstraint(in_values("origin", SCORING_ORIGINS), name="origin"),
        {"schema": "scoring"},
    )

    id: Mapped[int] = mapped_column(Identity(always=True), primary_key=True)
    fetch_run_id: Mapped[int | None]  # -> market_data.fetch_run (logisch)
    origin: Mapped[str]
    config: Mapped[dict[str, Any] | None]
    config_hash: Mapped[str | None] = mapped_column(index=True)
    app_version: Mapped[str]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    note: Mapped[str | None]


class ScoreResult(Base):
    """Ergebnis je Titel - auch fuer Titel, die am Groessenfilter scheitern."""

    __tablename__ = "score_result"
    __table_args__ = {"schema": "scoring"}  # noqa: RUF012

    scoring_run_id: Mapped[int] = mapped_column(
        ForeignKey("scoring.scoring_run.id"), primary_key=True
    )
    instrument_id: Mapped[int] = mapped_column(primary_key=True)  # -> market_data.instrument
    passed_filter: Mapped[bool]
    value_score: Mapped[float | None]
    quality_score: Mapped[float | None]
    composite_score: Mapped[float | None]
    value_trap_flag: Mapped[bool | None]
    rank_overall: Mapped[int | None]


class FactorScore(Base):
    """Perzentilrang je Faktor (frueher ``rank_*``, nie gespeichert)."""

    __tablename__ = "factor_score"
    __table_args__ = (
        CheckConstraint(in_values("category", ("value", "quality")), name="category"),
        CheckConstraint(in_values("direction", ("low", "high")), name="direction"),
        {"schema": "scoring"},
    )

    scoring_run_id: Mapped[int] = mapped_column(
        ForeignKey("scoring.scoring_run.id"), primary_key=True
    )
    instrument_id: Mapped[int] = mapped_column(primary_key=True)
    factor_key: Mapped[str] = mapped_column(primary_key=True)
    category: Mapped[str]
    source_column: Mapped[str]
    direction: Mapped[str]
    raw_value: Mapped[float | None]
    percentile_rank: Mapped[float | None]
