"""Schema ``market_data``: Stammdaten, Rohdaten und berechnete Kennzahlen je Abruf."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    ARRAY,
    CheckConstraint,
    ForeignKey,
    Identity,
    Index,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ...consensus import CONSENSUS_KINDS, CONSENSUS_STATUSES
from .base import Base, in_values

FETCH_ORIGINS = ("live", "import")
STATEMENTS = ("income", "balance", "cashflow")


class Instrument(Base):
    """Stammsatz je Wertpapier. Symbol unveraenderlich, ISIN nur nachtragbar."""

    __tablename__ = "instrument"
    __table_args__ = {"schema": "market_data"}  # noqa: RUF012

    id: Mapped[int] = mapped_column(Identity(always=True), primary_key=True)
    symbol: Mapped[str] = mapped_column(unique=True)
    isin: Mapped[str | None] = mapped_column(unique=True)
    first_seen_at: Mapped[datetime] = mapped_column(server_default=func.now())


class FetchRun(Base):
    """Ein Abruf des Universums beim Provider (oder ein Import von Altdateien)."""

    __tablename__ = "fetch_run"
    __table_args__ = (
        CheckConstraint(in_values("origin", FETCH_ORIGINS), name="origin"),
        {"schema": "market_data"},
    )

    id: Mapped[int] = mapped_column(Identity(always=True), primary_key=True)
    origin: Mapped[str]
    started_at: Mapped[datetime] = mapped_column(server_default=func.now())
    finished_at: Mapped[datetime | None]
    provider: Mapped[str]
    provider_version: Mapped[str | None]
    universe_source: Mapped[str | None]  # iShares / Deka / Fallback-CSV
    universe_as_of: Mapped[date | None]  # Stichtag der Indexquelle (Deka: keiner)
    universe_size: Mapped[int | None]
    ok_count: Mapped[int | None]
    success_share: Mapped[float | None]
    note: Mapped[str | None]


class UniverseMember(Base):
    """Index-Zugehoerigkeit je Abruf - Grundlage gegen Survivorship-Bias."""

    __tablename__ = "universe_member"
    __table_args__ = {"schema": "market_data"}  # noqa: RUF012

    fetch_run_id: Mapped[int] = mapped_column(
        ForeignKey("market_data.fetch_run.id"), primary_key=True
    )
    instrument_id: Mapped[int] = mapped_column(
        ForeignKey("market_data.instrument.id"), primary_key=True
    )
    index_name: Mapped[str]
    name: Mapped[str | None]
    source: Mapped[str | None]


class RawInfo(Base):
    """Unveraenderte Provider-Antwort (yfinance ``info``) als JSONB."""

    __tablename__ = "raw_info"
    __table_args__ = {"schema": "market_data"}  # noqa: RUF012

    fetch_run_id: Mapped[int] = mapped_column(
        ForeignKey("market_data.fetch_run.id"), primary_key=True
    )
    instrument_id: Mapped[int] = mapped_column(
        ForeignKey("market_data.instrument.id"), primary_key=True
    )
    fetched_at: Mapped[datetime]
    payload: Mapped[dict[str, Any]]


class ConsensusSnapshot(Base):
    """Konsensschaetzungen je Abruf, Titel und Art (ADR-0010) - unveraenderte Rohdaten.

    ``status``: ``ok`` (Payload vorhanden), ``empty`` (Yahoo liefert nichts) oder ``error``
    (Abruf gescheitert, Text in ``error``). So bleibt auch sichtbar, wann Daten fehlten.
    """

    __tablename__ = "consensus_snapshot"
    __table_args__ = (
        CheckConstraint(in_values("kind", CONSENSUS_KINDS), name="kind"),
        CheckConstraint(in_values("status", CONSENSUS_STATUSES), name="status"),
        CheckConstraint("(status = 'ok') = (payload IS NOT NULL)", name="payload_only_if_ok"),
        CheckConstraint("(status = 'error') = (error IS NOT NULL)", name="error_only_if_error"),
        {"schema": "market_data"},
    )

    fetch_run_id: Mapped[int] = mapped_column(
        ForeignKey("market_data.fetch_run.id"), primary_key=True
    )
    instrument_id: Mapped[int] = mapped_column(
        ForeignKey("market_data.instrument.id"), primary_key=True
    )
    kind: Mapped[str] = mapped_column(primary_key=True)
    fetched_at: Mapped[datetime]
    status: Mapped[str]
    # none_as_null: Python-None wird SQL-NULL statt JSON-null - sonst greift der CHECK nicht
    payload: Mapped[Any | None] = mapped_column(JSONB(none_as_null=True))
    error: Mapped[str | None]


class StatementValue(Base):
    """Versionierter Abschlusswert.

    Eine Zeile entsteht nur, wenn sich der Wert eines Postens gegenueber seiner
    letzten Version aendert. So bleiben Restatements sichtbar, ohne jede Woche
    alle ~700 Werte je Titel zu duplizieren.
    """

    __tablename__ = "statement_value"
    __table_args__ = (
        CheckConstraint(in_values("statement", STATEMENTS), name="statement"),
        Index(
            "ix_statement_value_key",
            "instrument_id",
            "statement",
            "frequency",
            "line_item",
            "period_end",
            "first_seen_at",
        ),
        {"schema": "market_data"},
    )

    id: Mapped[int] = mapped_column(Identity(always=True), primary_key=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("market_data.instrument.id"))
    statement: Mapped[str]
    frequency: Mapped[str]  # annual (quarterly spaeter moeglich)
    line_item: Mapped[str]  # Originalname des Providers
    period_end: Mapped[date]
    value: Mapped[float]
    currency: Mapped[str | None]  # Berichtswaehrung
    first_seen_fetch_run_id: Mapped[int] = mapped_column(ForeignKey("market_data.fetch_run.id"))
    first_seen_at: Mapped[datetime]


class FxRate(Base):
    __tablename__ = "fx_rate"
    __table_args__ = (
        UniqueConstraint("fetch_run_id", "from_ccy", "to_ccy"),
        {"schema": "market_data"},
    )

    id: Mapped[int] = mapped_column(Identity(always=True), primary_key=True)
    fetch_run_id: Mapped[int] = mapped_column(ForeignKey("market_data.fetch_run.id"))
    from_ccy: Mapped[str]
    to_ccy: Mapped[str]
    rate: Mapped[float]
    fetched_at: Mapped[datetime]


class FundamentalSnapshot(Base):
    """``Fundamentals.to_flat_dict()`` je Abruf und Titel.

    Neue Kennzahl in ``fundamentals.py`` -> neue Spalte hier + Alembic-Migration.
    """

    __tablename__ = "fundamental_snapshot"
    __table_args__ = {"schema": "market_data"}  # noqa: RUF012

    fetch_run_id: Mapped[int] = mapped_column(
        ForeignKey("market_data.fetch_run.id"), primary_key=True
    )
    instrument_id: Mapped[int] = mapped_column(
        ForeignKey("market_data.instrument.id"), primary_key=True
    )
    # Identity (wie beobachtet)
    name: Mapped[str | None]
    index_name: Mapped[str | None]
    sector: Mapped[str | None]
    industry: Mapped[str | None]
    currency: Mapped[str | None]
    financial_currency: Mapped[str | None]
    # MarketData
    price: Mapped[float | None]
    market_cap: Mapped[float | None]
    enterprise_value: Mapped[float | None]
    shares_outstanding: Mapped[float | None]
    # ValueMetrics
    ev_ebit: Mapped[float | None]
    pe_ratio: Mapped[float | None]
    pb_ratio: Mapped[float | None]
    p_fcf: Mapped[float | None]
    dividend_yield: Mapped[float | None]
    buyback_yield: Mapped[float | None]
    shareholder_yield: Mapped[float | None]
    # QualityMetrics
    roic: Mapped[float | None]
    roa: Mapped[float | None]
    fcf_margin: Mapped[float | None]
    gross_margin: Mapped[float | None]
    operating_margin: Mapped[float | None]
    net_debt_ebitda: Mapped[float | None]
    debt_to_equity: Mapped[float | None]
    earnings_stability: Mapped[float | None]
    # Growth
    revenue_growth_5y: Mapped[float | None]
    eps_growth_5y: Mapped[float | None]
    # Provenance
    fetched_at: Mapped[datetime | None]
    fiscal_period_end: Mapped[date | None]
    statement_fx: Mapped[float | None]
    # Status
    fetch_ok: Mapped[bool]
    errors: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'"))
