"""Composition Root des web-api-Prozesses (P3.3): ``uvicorn --factory src.web:create_app``.

Verdrahtet die Ports des web-api mit dem Code von scoring, im selben Prozess: die Vorschau mit
der lesenden Verbindung (``va_read``), die Profil-Befehle mit ``va_profiles``. Das web-api darf
``va_scoring`` nicht importieren, ``src`` schon. Ab Phase 4 kommen beide per Request/Reply vom
Service scoring (P4.8); dann startet das web-api wieder ohne ``src``.
"""

from __future__ import annotations

import logging
import numbers
from typing import TYPE_CHECKING

from sqlalchemy.exc import IntegrityError

from va_contracts.base import missing_to_none
from va_market_data.adapters.postgres import MarketDataRepository
from va_platform.db import session_scope
from va_scoring.adapters.postgres import ScoringRepository
from va_scoring.domain.profile import FACTOR_INFO, ScoringProfileParams
from va_scoring.domain.scoring import DEFAULT_QUALITY_FACTORS, DEFAULT_VALUE_FACTORS, score
from va_web_api import main as web_api
from va_web_api.models import Factor
from va_web_api.ports import (
    NoPreviewData,
    PreviewBasis,
    ProfileConflict,
    RankedTitle,
    UnknownProfile,
    UnknownVersion,
)

from . import __version__

if TYPE_CHECKING:
    import pandas as pd
    from fastapi import FastAPI
    from sqlalchemy import Engine

    from va_contracts.profile import ProfileParamsV1
    from va_web_api.settings import WebApiSettings

log = logging.getLogger(__name__)


def create_app(settings: WebApiSettings | None = None) -> FastAPI:
    return web_api.create_app(
        settings, preview=InProcessPreview, commands=InProcessCommands, app_version=__version__
    )


class InProcessPreview:
    """``ScoringPreview``: rechnet mit ``score()`` auf den gespeicherten Snapshots."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine  # lesend: va_read, schreibgeschuetzte Transaktionen

    def factors(self) -> list[Factor]:
        factors: list[Factor] = []
        for group, catalog in (
            ("value", DEFAULT_VALUE_FACTORS),
            ("quality", DEFAULT_QUALITY_FACTORS),
        ):
            for key, (_column, direction) in catalog.items():
                label, hint = FACTOR_INFO[key]
                factors.append(
                    Factor(key=key, group=group, label=label, better=direction, hint=hint)  # type: ignore[arg-type]
                )
        return factors

    def preview(self, params: ProfileParamsV1) -> PreviewBasis:
        wanted = ScoringProfileParams.model_validate(params.model_dump(mode="json"))
        with session_scope(self._engine) as s:
            scoring = ScoringRepository(s)
            run = scoring.get_latest_scoring_run()
            if run is None or run.fetch_run_id is None:
                raise NoPreviewData
            market = MarketDataRepository(s)
            symbols = [str(sym) for sym in scoring.get_scores_df(run.id)["symbol"]]
            snapshots = market.get_snapshots_df(run.fetch_run_id, symbols)
            fetch_run = market.get_fetch_run(run.fetch_run_id)
            active = scoring.get_active_profile_version()
        # Ohne aktives Profil (vor P2b.3) zaehlen die Standardwerte
        current = (
            ScoringProfileParams()
            if active is None
            else ScoringProfileParams.model_validate(active.params)
        )
        return PreviewBasis(
            scoring_run_id=run.id,
            fetch_run_id=run.fetch_run_id,
            fetched_on=None if fetch_run is None else fetch_run.started_at.astimezone().date(),
            active_profile_id=None if active is None else active.profile_id,
            active_name=None if active is None else active.name,
            active_version=None if active is None else active.version,
            current=_ranked(snapshots, score(snapshots, current.to_config())),
            preview=_ranked(snapshots, score(snapshots, wanted.to_config())),
        )


class InProcessCommands:
    """``ProfileCommands``: neue Version und Aktivierung mit der Rolle ``va_profiles``."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def save_version(
        self, profile_id: int, params: ProfileParamsV1, *, based_on: int, comment: str | None
    ) -> int:
        stored = ScoringProfileParams.model_validate(params.model_dump(mode="json"))
        try:
            with session_scope(self._engine) as s:
                repo = ScoringRepository(s)
                if repo.get_profile_name(profile_id) is None:
                    raise UnknownProfile(profile_id)
                newest = repo.get_newest_profile_version(profile_id) or 0
                if newest != based_on:
                    raise ProfileConflict(newest)
                version = repo.write_profile_version(
                    profile_id,
                    stored.model_dump(mode="json"),
                    parent_version=based_on,
                    comment=comment,
                )
        except IntegrityError as e:
            # Ein zweiter Tab hat im selben Moment dieselbe Nummer angelegt
            raise ProfileConflict(based_on + 1) from e
        log.info("Profil #%d: Version %d gespeichert (auf v%d)", profile_id, version, based_on)
        return version

    def activate(self, profile_id: int, version: int) -> None:
        with session_scope(self._engine) as s:
            repo = ScoringRepository(s)
            if repo.get_profile_name(profile_id) is None:
                raise UnknownProfile(profile_id)
            if repo.get_profile_version(profile_id, version) is None:
                raise UnknownVersion(version)
            repo.write_profile_activation(profile_id, version)
        log.info("Profil #%d: Version %d aktiviert", profile_id, version)


def _ranked(snapshots: pd.DataFrame, scored: pd.DataFrame) -> list[RankedTitle]:
    """Alle Titel: erst die bewerteten in Rangfolge, dann die am Groessenfilter gescheiterten."""
    titles = [
        RankedTitle(
            symbol=str(row["symbol"]),
            name=_text(row.get("name")),
            index=_text(row.get("index")),
            passed_filter=True,
            rank=_int(row.get("rank_overall")),  # wie im gespeicherten Ranking
            composite_score=_number(row.get("composite_score")),
            value_score=_number(row.get("value_score")),
            quality_score=_number(row.get("quality_score")),
            value_trap_flag=bool(row["value_trap_flag"]),
        )
        for row in scored.to_dict("records")
    ]
    passed = {t.symbol for t in titles}
    filtered = snapshots[~snapshots["symbol"].isin(passed)].sort_values("symbol")
    titles += [
        RankedTitle(
            symbol=str(row["symbol"]),
            name=_text(row.get("name")),
            index=_text(row.get("index")),
            passed_filter=False,
            rank=None,
            composite_score=None,
            value_score=None,
            quality_score=None,
            value_trap_flag=None,
        )
        for row in filtered.to_dict("records")
    ]
    return titles


def _number(value: object) -> float | None:
    # missing_to_none: NaN, inf und pd.NA; numbers.Real erfasst auch die Zahlen von numpy
    value = missing_to_none(value)
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        return None
    return float(value)


def _int(value: object) -> int | None:
    number = _number(value)
    return None if number is None else int(number)


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None
