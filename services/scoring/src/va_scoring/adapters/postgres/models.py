"""Schema ``scoring``: jede Bewertung eines Abrufs ist ein eigener, unveraenderlicher Lauf.

Ein Neu-Scoring alter Daten (andere Gewichte, neuer Faktor) erzeugt einen neuen
``scoring_run`` - bestehende Ergebnisse werden nie ueberschrieben. Die Scoring-Profile
(P2b.1, ADR-0009) sind ebenso nur zum Anfuegen da: neue Version statt Aenderung, neue
Aktivierung statt Umschalten.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, ForeignKeyConstraint, Identity, func
from sqlalchemy.orm import Mapped, mapped_column

from va_platform.db import Base, in_values
from va_platform.messaging import InboxMixin, OutboxMixin, outbox_table_args

SCORING_ORIGINS = ("live", "rescore", "import")


class ScoringRun(Base):
    __tablename__ = "scoring_run"
    __table_args__ = (
        CheckConstraint(in_values("origin", SCORING_ORIGINS), name="origin"),
        # Profil und Version nur zusammen (P2b.3); leer vor P2b.3, beim Import und im Replay
        CheckConstraint("(profile_id IS NULL) = (profile_version IS NULL)", name="profile"),
        ForeignKeyConstraint(
            ["profile_id", "profile_version"],
            ["scoring.profile_version.profile_id", "scoring.profile_version.version"],
        ),
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
    profile_id: Mapped[int | None]
    profile_version: Mapped[int | None]


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


class Profile(Base):
    """Ein Scoring-Profil. Sein Inhalt steht in den Versionen."""

    __tablename__ = "profile"
    __table_args__ = {"schema": "scoring"}  # noqa: RUF012

    id: Mapped[int] = mapped_column(Identity(always=True), primary_key=True)
    name: Mapped[str] = mapped_column(unique=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class ProfileVersion(Base):
    """Eine unveraenderliche Version: Speichern legt immer die naechste Nummer an."""

    __tablename__ = "profile_version"
    __table_args__ = (
        CheckConstraint("version >= 1", name="version"),
        CheckConstraint("parent_version < version", name="parent_version"),
        # Die Vorlage ist eine aeltere Version desselben Profils
        ForeignKeyConstraint(
            ["profile_id", "parent_version"],
            ["scoring.profile_version.profile_id", "scoring.profile_version.version"],
        ),
        {"schema": "scoring"},
    )

    profile_id: Mapped[int] = mapped_column(ForeignKey("scoring.profile.id"), primary_key=True)
    version: Mapped[int] = mapped_column(primary_key=True)
    params: Mapped[dict[str, Any]]
    parent_version: Mapped[int | None]
    comment: Mapped[str | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class ProfileActivation(Base):
    """Aktiv ist die juengste Zeile ueber alle Profile. Zurueckrollen: aeltere Version aktivieren."""

    __tablename__ = "profile_activation"
    __table_args__ = (
        ForeignKeyConstraint(
            ["profile_id", "version"],
            ["scoring.profile_version.profile_id", "scoring.profile_version.version"],
        ),
        {"schema": "scoring"},
    )

    id: Mapped[int] = mapped_column(Identity(always=True), primary_key=True)
    profile_id: Mapped[int]
    version: Mapped[int]
    activated_at: Mapped[datetime] = mapped_column(server_default=func.now())


class ScoringOutbox(OutboxMixin, Base):
    """Events von scoring, bis das Relay sie veroeffentlicht hat (P4.2)."""

    __table_args__ = outbox_table_args("scoring")


class ScoringInbox(InboxMixin, Base):
    """Events, die scoring verarbeitet hat, je Consumer einmal (P4.2)."""

    __table_args__ = {"schema": "scoring"}  # noqa: RUF012


class InputSnapshot(Base):
    """Eingangsdaten der Bewertung (P5.1a): je Abruf und Titel die flache Zeile fuer ``score()``.

    Daraus rechnet die Vorschau, ohne ``market_data`` zu lesen. Nur zum Anfuegen; ein Rescore
    desselben Abrufs fuegt nichts hinzu. Aeltere Laeufe fuellt ``src.db.backfill`` nach.
    """

    __tablename__ = "input_snapshot"
    __table_args__ = {"schema": "scoring"}  # noqa: RUF012

    fetch_run_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)
    symbol: Mapped[str] = mapped_column(primary_key=True)
    row: Mapped[dict[str, Any]]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
