"""Schema ``web``: Read-Models des web-api, gebaut aus den Events (P4.4).

Projektionen sind die bewusst gekennzeichnete Ausnahme vom Schreibschutz
(docs/architecture/datenhaltung.md): ``run_status`` wird mit jedem Event eines Runs
aktualisiert. Geloescht wird auch hier nie. ``ranking_row`` ist nur zum Anfuegen, je
Bewertungslauf und Titel eine Zeile; daraus ergeben sich aktuelles Ranking und Score-Verlauf.
``run_request`` (P4.7) haelt die Runs fest, die das web-api selbst angelegt hat.
Geschrieben wird mit der Rolle ``va_web``, gelesen auch mit ``va_read``.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import CheckConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from va_platform.db import Base, in_values
from va_platform.messaging import InboxMixin, OutboxMixin, outbox_table_args

RUN_STATES = ("requested", "fetched", "scored", "reported", "failed", "no_data")


class RunStatus(Base):
    """Stand eines Runs aus Sicht der Events. Ein Fehlschlag gewinnt, wie im RunTracker."""

    __tablename__ = "run_status"
    __table_args__ = (
        CheckConstraint(in_values("status", RUN_STATES), name="status"),
        {"schema": "web"},
    )

    run_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)  # batch.run.id
    status: Mapped[str]
    trigger: Mapped[str | None]
    fetch_run_id: Mapped[int | None]
    scoring_run_id: Mapped[int | None]
    report_id: Mapped[int | None]
    universe_size: Mapped[int | None]
    scored_count: Mapped[int | None]
    error: Mapped[str | None]
    last_event_type: Mapped[str]
    last_event_at: Mapped[datetime]
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now())


class RankingRow(Base):
    """Ein Titel in einem Bewertungslauf, wie ``scoring.run.completed`` ihn meldet."""

    __tablename__ = "ranking_row"
    __table_args__ = {"schema": "web"}  # noqa: RUF012

    scoring_run_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)
    symbol: Mapped[str] = mapped_column(primary_key=True)
    run_id: Mapped[int | None]  # leer bei einem Rescore
    as_of: Mapped[date]
    name: Mapped[str]
    index: Mapped[str]
    rank_overall: Mapped[int]
    composite_score: Mapped[float | None]
    value_score: Mapped[float | None]
    quality_score: Mapped[float | None]
    value_trap: Mapped[bool]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


RUN_TRIGGERS = ("scheduled", "manual")


class RunRequest(Base):
    """Ein Run, den das web-api angelegt hat (P4.7). Nur zum Anfuegen.

    Die Zeile kennzeichnet die Runs, die das web-api ueberwacht und abschliesst; Runs des Batches
    stehen nur in ``batch.run``. ``slot`` ist der Cron-Termin eines geplanten Runs und eindeutig:
    Derselbe Termin ergibt nur einen Run.
    """

    __tablename__ = "run_request"
    __table_args__ = (
        CheckConstraint(in_values("trigger", RUN_TRIGGERS), name="trigger"),
        {"schema": "web"},
    )

    run_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)  # batch.run.id
    trigger: Mapped[str]
    slot: Mapped[datetime | None] = mapped_column(unique=True)
    force_refresh: Mapped[bool]
    dry_run: Mapped[bool]
    notify: Mapped[bool]
    requested_at: Mapped[datetime]


class WebInbox(InboxMixin, Base):
    """Events, die der Eventmanager verarbeitet hat (Consumer ``web-api``)."""

    __table_args__ = {"schema": "web"}  # noqa: RUF012


class WebOutbox(OutboxMixin, Base):
    """Events des web-api, etwa ein Run-Start aus dem UI (ab P4.7)."""

    __table_args__ = outbox_table_args("web")
