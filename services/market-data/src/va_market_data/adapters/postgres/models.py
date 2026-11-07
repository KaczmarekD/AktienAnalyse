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

from va_market_data.domain.consensus import CONSENSUS_KINDS, CONSENSUS_STATUSES
from va_market_data.domain.securities import ASSET_CLASSES
from va_platform.db import Base, in_values
from va_platform.messaging import InboxMixin, OutboxMixin, outbox_table_args

FETCH_ORIGINS = ("live", "import")
STATEMENTS = ("income", "balance", "cashflow")
FREQUENCIES = ("annual", "quarterly")  # geprueft im Repository, die Spalte ist freier Text
SNAPSHOT_ROLES = ("universe", "coverage")  # D2.2
PRICE_RUN_STATUSES = ("ok", "failed")  # D2.3


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

    ``status``: ``ok`` (Payload vorhanden), ``empty`` (keine Daten, meist keine
    Analystenabdeckung) oder ``error`` (Abruf gescheitert oder nach einem Rate-Limit
    uebersprungen, Grund in ``error``). So bleibt auch sichtbar, wann Daten fehlten.
    ``fetched_at`` ist wie bei ``raw_info`` der Beginn des Abrufs dieses Titels.
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
    frequency: Mapped[str]  # annual oder quarterly (seit F1.2), siehe FREQUENCIES
    line_item: Mapped[str]  # Originalname des Providers
    period_end: Mapped[date]
    value: Mapped[float]
    currency: Mapped[str | None]  # Berichtswaehrung
    first_seen_fetch_run_id: Mapped[int] = mapped_column(ForeignKey("market_data.fetch_run.id"))
    first_seen_at: Mapped[datetime]


class ShareCount(Base):
    """Versionierte Aktienanzahl je Tag (ADR-0010, F1.3), Quelle ``get_shares_full``.

    Wie ``statement_value``: Eine Zeile entsteht nur fuer einen neuen Tag oder einen
    geaenderten Wert, korrigierte Tage bleiben so als eigene Version sichtbar.
    """

    __tablename__ = "share_count"
    __table_args__ = (
        CheckConstraint("shares > 0", name="shares"),
        Index("ix_share_count_key", "instrument_id", "as_of", "first_seen_at"),
        {"schema": "market_data"},
    )

    id: Mapped[int] = mapped_column(Identity(always=True), primary_key=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("market_data.instrument.id"))
    as_of: Mapped[date]  # Tag der Angabe, Zeitzone der Boerse
    shares: Mapped[int]
    first_seen_fetch_run_id: Mapped[int] = mapped_column(ForeignKey("market_data.fetch_run.id"))
    first_seen_at: Mapped[datetime]


class PriceBar(Base):
    """Versionierter Tageskurs (ADR-0010, F1.4) aus ``history(auto_adjust=False, actions=True)``.

    Wie ``statement_value``: Eine Zeile entsteht nur fuer einen neuen Tag oder einen
    geaenderten Wert. Ein Split passt bei Yahoo alle frueheren Kurse an, die alten
    Versionen bleiben stehen. ``dividend``/``split`` sind 0 an Tagen ohne Ereignis.
    """

    __tablename__ = "price_bar"
    __table_args__ = (
        CheckConstraint("close > 0", name="close"),
        CheckConstraint("dividend >= 0", name="dividend"),
        CheckConstraint("split >= 0", name="split"),
        Index("ix_price_bar_key", "instrument_id", "trade_date", "first_seen_at"),
        {"schema": "market_data"},
    )

    id: Mapped[int] = mapped_column(Identity(always=True), primary_key=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("market_data.instrument.id"))
    trade_date: Mapped[date]  # Handelstag, Zeitzone der Boerse
    close: Mapped[float]  # split-, nicht dividendenbereinigt
    adj_close: Mapped[float | None]  # zusaetzlich dividendenbereinigt, Stand des Abrufs
    dividend: Mapped[float]
    split: Mapped[float]
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
    __table_args__ = (
        CheckConstraint(in_values("role", SNAPSHOT_ROLES), name="role"),
        {"schema": "market_data"},
    )

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
    # D2.2: universe (Referenzuniversum, im Ranking) oder coverage (Abdeckung, nicht im Ranking)
    role: Mapped[str] = mapped_column(Text, server_default=text("'universe'"))


class CoverageVersion(Base):
    """D2.2 (WP-05): eine Fassung der Abdeckung; gueltig ist die juengste."""

    __tablename__ = "coverage_version"
    __table_args__ = {"schema": "market_data"}  # noqa: RUF012

    id: Mapped[int] = mapped_column(Identity(always=True), primary_key=True)
    source: Mapped[str]  # command (Kommando, bis D3), spaeter portfolio
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class CoverageItem(Base):
    """D2.2 (WP-09): ein Wertpapier der Abdeckung, ohne Nutzer und Mengen."""

    __tablename__ = "coverage_item"
    __table_args__ = (
        CheckConstraint(in_values("asset_class", ASSET_CLASSES), name="asset_class"),
        UniqueConstraint("version_id", "isin", name="uq_coverage_item_version_id_isin"),
        {"schema": "market_data"},
    )

    id: Mapped[int] = mapped_column(Identity(always=True), primary_key=True)
    version_id: Mapped[int] = mapped_column(ForeignKey("market_data.coverage_version.id"))
    isin: Mapped[str]
    asset_class: Mapped[str]
    fundamentals_symbol: Mapped[str | None]
    price_symbol: Mapped[str | None]
    name: Mapped[str | None]


class PriceRun(Base):
    """D2.3: ein Abruf der Tageskurse. Nur angefuegt, mit Ende und Ergebnis in einem Schritt (kein
    spaeteres Abschliessen wie bei ``fetch_run``)."""

    __tablename__ = "price_run"
    __table_args__ = (
        CheckConstraint(in_values("status", PRICE_RUN_STATUSES), name="status"),
        {"schema": "market_data"},
    )

    id: Mapped[int] = mapped_column(Identity(always=True), primary_key=True)
    source: Mapped[str]  # yahoo, spaeter bundesbank (D2.4)
    started_at: Mapped[datetime]
    finished_at: Mapped[datetime]
    status: Mapped[str]


class DailyClose(Base):
    """D2.3 (WP-06): Schlusskurs je ISIN, Quelle und Handelstag, in Hauptwaehrung; auch ohne
    Yahoo-Symbol. Je Tag nur einmal."""

    __tablename__ = "daily_close"
    __table_args__ = (
        UniqueConstraint(
            "isin", "source", "trade_date", name="uq_daily_close_isin_source_trade_date"
        ),
        {"schema": "market_data"},
    )

    id: Mapped[int] = mapped_column(Identity(always=True), primary_key=True)
    isin: Mapped[str]
    symbol: Mapped[str | None]
    source: Mapped[str]
    trade_date: Mapped[date]
    close: Mapped[float]
    currency: Mapped[str]
    quote_currency: Mapped[str | None]  # Notierung an der Boerse (GBp), fuer den naechsten Tag
    price_run_id: Mapped[int] = mapped_column(ForeignKey("market_data.price_run.id"))
    first_seen_at: Mapped[datetime] = mapped_column(server_default=func.now())


class FxDaily(Base):
    """D2.3 (WP-11): 1 Einheit der Waehrung in EUR je Tag und Quelle, nur einmal."""

    __tablename__ = "fx_daily"
    __table_args__ = (
        UniqueConstraint(
            "currency", "trade_date", "source", name="uq_fx_daily_currency_trade_date_source"
        ),
        {"schema": "market_data"},
    )

    id: Mapped[int] = mapped_column(Identity(always=True), primary_key=True)
    currency: Mapped[str]
    trade_date: Mapped[date]
    rate_to_eur: Mapped[float]
    source: Mapped[str]
    price_run_id: Mapped[int] = mapped_column(ForeignKey("market_data.price_run.id"))


class Security(Base):
    """D2.1 (WP-01): ein Wertpapier, ueber die ISIN eindeutig."""

    __tablename__ = "security"
    __table_args__ = (
        CheckConstraint(in_values("asset_class", ASSET_CLASSES), name="asset_class"),
        {"schema": "market_data"},
    )

    id: Mapped[int] = mapped_column(Identity(always=True), primary_key=True)
    isin: Mapped[str] = mapped_column(Text, unique=True)
    asset_class: Mapped[str]
    first_seen_at: Mapped[datetime] = mapped_column(server_default=func.now())


class SecurityMasterVersion(Base):
    """D2.1 (WP-04): Stammdaten je Quelle als JSONB, neue Zeile nur bei geaendertem Inhalt."""

    __tablename__ = "security_master"
    __table_args__ = (
        Index("ix_security_master_isin_source", "isin", "source"),
        {"schema": "market_data"},
    )

    id: Mapped[int] = mapped_column(Identity(always=True), primary_key=True)
    isin: Mapped[str] = mapped_column(ForeignKey("market_data.security.isin"))
    source: Mapped[str]
    payload: Mapped[dict[str, Any]]
    fetched_at: Mapped[datetime]


class Listing(Base):
    """D2.1 (WP-03): Handel eines Wertpapiers an einem Boersenplatz; ``instrument`` bleibt das
    Listing fuer die Fundamentaldaten. ``symbol`` ist das Yahoo-Symbol, falls es eines gibt."""

    __tablename__ = "listing"
    __table_args__ = (
        UniqueConstraint("isin", "ticker", "exchange", name="uq_listing_isin_ticker_exchange"),
        {"schema": "market_data"},
    )

    id: Mapped[int] = mapped_column(Identity(always=True), primary_key=True)
    isin: Mapped[str] = mapped_column(ForeignKey("market_data.security.isin"), index=True)
    symbol: Mapped[str | None] = mapped_column(Text, unique=True)
    ticker: Mapped[str | None]
    exchange: Mapped[str | None]
    currency: Mapped[str | None]
    first_seen_at: Mapped[datetime] = mapped_column(server_default=func.now())


class MarketDataOutbox(OutboxMixin, Base):
    """Events von market-data, bis das Relay sie veroeffentlicht hat (P4.2)."""

    __table_args__ = outbox_table_args("market_data")


class MarketDataInbox(InboxMixin, Base):
    """Events, die market-data verarbeitet hat, je Consumer einmal (P4.2)."""

    __table_args__ = {"schema": "market_data"}  # noqa: RUF012
