"""Alle ORM-Modelle - der Import registriert sie in ``Base.metadata`` (fuer Alembic).

Die Modelle liegen bei ihrem Besitzer-Modul (P1.7); hier steht nur noch ``batch``.
"""

from va_market_data.adapters.postgres.models import (
    ConsensusSnapshot,
    FetchRun,
    FundamentalSnapshot,
    FxRate,
    Instrument,
    MarketDataInbox,
    MarketDataOutbox,
    PriceBar,
    RawInfo,
    ShareCount,
    StatementValue,
    UniverseMember,
)
from va_notification.adapters.postgres.models import (
    Delivery,
    Report,
    ReportingInbox,
    ReportingOutbox,
)
from va_platform.db import APP_SCHEMAS, Base
from va_scoring.adapters.postgres.models import (
    FactorScore,
    Profile,
    ProfileActivation,
    ProfileVersion,
    ScoreResult,
    ScoringInbox,
    ScoringOutbox,
    ScoringRun,
)

from .batch import BatchInbox, BatchOutbox, ImportFile, Run, RunLog

__all__ = [
    "APP_SCHEMAS",
    "Base",
    "BatchInbox",
    "BatchOutbox",
    "ConsensusSnapshot",
    "Delivery",
    "FactorScore",
    "FetchRun",
    "FundamentalSnapshot",
    "FxRate",
    "ImportFile",
    "Instrument",
    "MarketDataInbox",
    "MarketDataOutbox",
    "PriceBar",
    "Profile",
    "ProfileActivation",
    "ProfileVersion",
    "RawInfo",
    "Report",
    "ReportingInbox",
    "ReportingOutbox",
    "Run",
    "RunLog",
    "ScoreResult",
    "ScoringInbox",
    "ScoringOutbox",
    "ScoringRun",
    "ShareCount",
    "StatementValue",
    "UniverseMember",
]
