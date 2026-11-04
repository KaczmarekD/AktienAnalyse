"""Request/Reply von scoring (P4.8, beim Besitzer seit P5.1a): Faktoren, Vorschau, Profile.

Die Antworten sind die Contracts aus ``va_contracts.rpc.v1``. Gelesen wird nur das Schema
``scoring``: Die Vorschau rechnet aus der eigenen Kopie der Eingangsdaten
(``scoring.input_snapshot``), nicht aus ``market_data``. Nach Speichern und Aktivieren meldet
``notify`` das Profil-Event an die offenen Tabs.

Bedient wird das ueber NATS (``python -m va_scoring``, Worker) und im web-api ohne NATS ueber
``va_platform.service.LocalCaller`` (``src.web``).
"""

from __future__ import annotations

import logging
import numbers
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy.exc import IntegrityError

from va_contracts import new_envelope
from va_contracts.base import missing_to_none
from va_contracts.events.v1 import (
    PROFILE_ACTIVATED,
    PROFILE_SAVED,
    ProfileActivatedV1,
    ProfileSavedV1,
)
from va_contracts.rpc.v1 import (
    PROFILE_ACTIVATE,
    PROFILE_GET,
    PROFILE_LIST,
    PROFILE_SAVE,
    SCORING_FACTORS,
    SCORING_PREVIEW,
    ActivateReplyV1,
    ActivateRequestV1,
    FactorsReplyV1,
    FactorsRequestV1,
    FactorV1,
    PreviewBasisV1,
    PreviewReplyV1,
    PreviewRequestV1,
    ProfileDetailV1,
    ProfileGetRequestV1,
    ProfileReplyV1,
    ProfilesReplyV1,
    ProfilesRequestV1,
    ProfileSummaryV1,
    RankedTitleV1,
    RpcErrorV1,
    SaveVersionReplyV1,
    SaveVersionRequestV1,
)
from va_platform.db import session_scope

from ..adapters.postgres import ScoringRepository
from ..domain.profile import FACTOR_INFO, ScoringProfileParams
from ..domain.scoring import DEFAULT_QUALITY_FACTORS, DEFAULT_VALUE_FACTORS, score

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import date

    import pandas as pd
    from sqlalchemy import Engine

    from va_contracts import Envelope
    from va_contracts.rpc.v1 import RpcReplyV1, RpcSpec

log = logging.getLogger(__name__)

SOURCE = "va/scoring"

type Handlers = dict[RpcSpec[Any, Any], Callable[[Any], RpcReplyV1]]


def factor_catalog() -> list[FactorV1]:
    """Alle Faktoren mit Richtung und Methodik-Hinweis, Value vor Quality."""
    factors: list[FactorV1] = []
    for group, catalog in (("value", DEFAULT_VALUE_FACTORS), ("quality", DEFAULT_QUALITY_FACTORS)):
        for key, (_column, direction) in catalog.items():
            label, hint = FACTOR_INFO[key]
            factors.append(
                FactorV1(key=key, group=group, label=label, better=direction, hint=hint)  # type: ignore[arg-type]
            )
    return factors


def handlers(engine: Engine, *, notify: Callable[[Envelope[Any]], None] | None = None) -> Handlers:
    """Alle sechs Befehle; ``engine`` liest (Vorschau, Profile) und schreibt (Speichern)."""

    def announce(envelope: Envelope[Any]) -> None:
        if notify is None:
            return
        try:
            notify(envelope)
        except Exception:
            log.warning("%s nicht gemeldet", envelope.type, exc_info=True)

    def factors(request: FactorsRequestV1) -> FactorsReplyV1:  # noqa: ARG001 - ohne Felder
        return FactorsReplyV1(factors=factor_catalog())

    def preview(request: PreviewRequestV1) -> PreviewReplyV1:
        basis = preview_basis(engine, request.params.model_dump(mode="json"))
        if basis is None:
            error = RpcErrorV1(code="no_data", message="Noch kein Bewertungslauf")
            return PreviewReplyV1(error=error)
        return PreviewReplyV1(basis=basis)

    def save(request: SaveVersionRequestV1) -> SaveVersionReplyV1:
        stored = ScoringProfileParams.model_validate(request.params.model_dump(mode="json"))
        try:
            with session_scope(engine) as s:
                repo = ScoringRepository(s)
                if repo.get_profile_name(request.profile_id) is None:
                    return SaveVersionReplyV1(error=_unknown_profile(request.profile_id))
                newest = repo.get_newest_profile_version(request.profile_id) or 0
                if newest != request.based_on:
                    return SaveVersionReplyV1(error=_conflict(newest))
                version = repo.write_profile_version(
                    request.profile_id,
                    stored.model_dump(mode="json"),
                    parent_version=request.based_on,
                    comment=request.comment,
                )
        except IntegrityError:
            # Ein zweiter Tab hat im selben Moment dieselbe Nummer angelegt
            return SaveVersionReplyV1(error=_conflict(request.based_on + 1))
        log.info(
            "Profil #%d: Version %d gespeichert (auf v%d)",
            request.profile_id,
            version,
            request.based_on,
        )
        saved = ProfileSavedV1(profile_id=request.profile_id, version=version)
        announce(new_envelope(PROFILE_SAVED, saved, source=SOURCE))
        return SaveVersionReplyV1(version=version)

    def activate(request: ActivateRequestV1) -> ActivateReplyV1:
        with session_scope(engine) as s:
            repo = ScoringRepository(s)
            if repo.get_profile_name(request.profile_id) is None:
                return ActivateReplyV1(error=_unknown_profile(request.profile_id))
            if repo.get_profile_version(request.profile_id, request.version) is None:
                error = RpcErrorV1(code="unknown_version", message=f"Version {request.version}")
                return ActivateReplyV1(error=error)
            repo.write_profile_activation(request.profile_id, request.version)
        log.info("Profil #%d: Version %d aktiviert", request.profile_id, request.version)
        activated = ProfileActivatedV1(profile_id=request.profile_id, version=request.version)
        announce(new_envelope(PROFILE_ACTIVATED, activated, source=SOURCE))
        return ActivateReplyV1()

    def profiles(request: ProfilesRequestV1) -> ProfilesReplyV1:  # noqa: ARG001 - ohne Felder
        with session_scope(engine) as s:
            rows = ScoringRepository(s).list_profiles()
        return ProfilesReplyV1(profiles=[ProfileSummaryV1.model_validate(r) for r in rows])

    def profile(request: ProfileGetRequestV1) -> ProfileReplyV1:
        with session_scope(engine) as s:
            detail = ScoringRepository(s).get_profile_detail(request.profile_id)
        return ProfileReplyV1(
            profile=None if detail is None else ProfileDetailV1.model_validate(detail)
        )

    return {
        SCORING_FACTORS: factors,
        SCORING_PREVIEW: preview,
        PROFILE_SAVE: save,
        PROFILE_ACTIVATE: activate,
        PROFILE_LIST: profiles,
        PROFILE_GET: profile,
    }


def preview_basis(engine: Engine, params: dict[str, Any]) -> PreviewBasisV1 | None:
    """Der juengste Bewertungslauf zweimal bewertet: mit dem aktiven Profil und mit ``params``.

    ``None``, solange es keinen Lauf mit gespeicherten Eingangsdaten gibt.
    """
    wanted = ScoringProfileParams.model_validate(params)
    with session_scope(engine) as s:
        repo = ScoringRepository(s)
        run = repo.get_latest_scoring_run()
        if run is None or run.fetch_run_id is None:
            return None
        frame = repo.get_input_frame(run.fetch_run_id)
        active = repo.get_active_profile_version()
        run_id, fetch_run_id, created_at = run.id, run.fetch_run_id, run.created_at
    if frame.empty:
        return None
    # Ohne aktives Profil (vor P2b.3) zaehlen die Standardwerte
    current = (
        ScoringProfileParams()
        if active is None
        else ScoringProfileParams.model_validate(active.params)
    )
    return PreviewBasisV1(
        scoring_run_id=run_id,
        fetch_run_id=fetch_run_id,
        fetched_on=_fetched_on(frame) or created_at.astimezone().date(),
        active_profile_id=None if active is None else active.profile_id,
        active_name=None if active is None else active.name,
        active_version=None if active is None else active.version,
        current=_ranked(frame, score(frame, current.to_config())),
        preview=_ranked(frame, score(frame, wanted.to_config())),
    )


def _unknown_profile(profile_id: int) -> RpcErrorV1:
    return RpcErrorV1(code="unknown_profile", message=f"Profil {profile_id}")


def _conflict(newest: int) -> RpcErrorV1:
    return RpcErrorV1(code="conflict", message="nicht die neueste Version", newest=newest)


def _fetched_on(frame: pd.DataFrame) -> date | None:
    """Tag des Abrufs (lokal) aus den Zeitpunkten der Titel."""
    if "fetched_at" not in frame:
        return None
    moments = [datetime.fromisoformat(str(v)) for v in frame["fetched_at"].dropna()]
    return min(moments).astimezone().date() if moments else None


def _ranked(snapshots: pd.DataFrame, scored: pd.DataFrame) -> list[RankedTitleV1]:
    """Alle Titel: erst die bewerteten in Rangfolge, dann die am Groessenfilter gescheiterten."""
    titles = [
        RankedTitleV1(
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
        RankedTitleV1(
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
