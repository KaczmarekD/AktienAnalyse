"""Alle ORM-Modelle - der Import registriert sie in ``Base.metadata`` (fuer Alembic).

Die Modelle liegen bei ihrem Besitzer-Modul (P1.7); hier steht nur noch ``batch``.
"""

from va_market_data.adapters.postgres.models import (
    ConsensusSnapshot,
    FetchRun,
    FundamentalSnapshot,
    FxRate,
    Instrument,
    PriceBar,
    RawInfo,
    ShareCount,
    StatementValue,
    UniverseMember,
)
from va_notification.adapters.postgres.models import Delivery, Report
from va_platform.db import APP_SCHEMAS, Base
from va_scoring.adapters.postgres.models import FactorScore, ScoreResult, ScoringRun

from .batch import ImportFile, Run, RunLog

__all__ = [
    "APP_SCHEMAS",
    "Base",
    "ConsensusSnapshot",
    "Delivery",
    "FactorScore",
    "FetchRun",
    "FundamentalSnapshot",
    "FxRate",
    "ImportFile",
    "Instrument",
    "PriceBar",
    "RawInfo",
    "Report",
    "Run",
    "RunLog",
    "ScoreResult",
    "ScoringRun",
    "ShareCount",
    "StatementValue",
    "UniverseMember",
]
