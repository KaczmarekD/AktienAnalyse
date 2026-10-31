"""Zugriffe auf ``scoring``: Bewertungslaeufe, Ergebnisse und Faktor-Raenge."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

import pandas as pd
from sqlalchemy import BigInteger, Text, column, func, insert, or_, select, table
from sqlalchemy.dialects.postgresql import insert as pg_insert

from va_platform.serialization import json_safe, to_python

from ...domain.profile import ProfileVersionRef
from .models import (
    FactorScore,
    Profile,
    ProfileActivation,
    ProfileVersion,
    ScoreResult,
    ScoringRun,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


# Das Symbol steht in market_data.instrument. Gelesen wird es ueber eine schlanke
# Tabellenreferenz statt ueber das Modell von market-data: kein Import ueber die
# Service-Grenze, kein Fremdschluessel. Uebergang, bis scoring die Symbole mit den
# Events bekommt (P1.8/Phase 2).
_instrument = table(
    "instrument",
    column("id", BigInteger),
    column("symbol", Text),
    schema="market_data",
)


@dataclass(frozen=True)
class ScoreRow:
    instrument_id: int
    passed_filter: bool
    value_score: float | None
    quality_score: float | None
    composite_score: float | None
    value_trap_flag: bool | None
    rank_overall: int | None


@dataclass(frozen=True)
class FactorScoreRow:
    instrument_id: int
    factor_key: str
    category: str
    source_column: str
    direction: str
    raw_value: float | None
    percentile_rank: float | None


def config_hash(config: dict[str, Any] | None) -> str | None:
    if config is None:
        return None
    canonical = json.dumps(json_safe(config), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class ScoringRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    # --- Instrumente (nur lesend, gehoeren market-data) ------------------------

    def get_instrument_ids(self, symbols: Iterable[str]) -> dict[str, int]:
        """IDs aus ``market_data.instrument``. market-data legt sie beim Abruf an; fehlt
        ein Symbol, ist das ein Fehler im Ablauf und kein Fall zum Anlegen."""
        wanted = sorted(set(symbols))
        if not wanted:
            return {}
        rows = self.session.execute(
            select(_instrument.c.symbol, _instrument.c.id).where(_instrument.c.symbol.in_(wanted))
        ).all()
        ids = {str(symbol): int(iid) for symbol, iid in rows}
        missing = [s for s in wanted if s not in ids]
        if missing:
            msg = f"Instrumente fehlen in market_data.instrument: {', '.join(missing)}"
            raise LookupError(msg)
        return ids

    # --- write -------------------------------------------------------------

    def write_scoring_run(
        self,
        *,
        fetch_run_id: int | None,
        config: dict[str, Any] | None,
        app_version: str,
        origin: str = "live",
        note: str | None = None,
        created_at: datetime | None = None,
    ) -> int:
        safe_config = json_safe(config) if config is not None else None
        values: dict[str, Any] = {
            "fetch_run_id": fetch_run_id,
            "origin": origin,
            "config": safe_config,
            "config_hash": config_hash(safe_config),
            "app_version": app_version,
            "note": note,
        }
        if created_at is not None:
            values["created_at"] = created_at
        stmt = insert(ScoringRun).values(**values).returning(ScoringRun.id)
        return self.session.execute(stmt).scalar_one()

    def write_score_results(self, scoring_run_id: int, rows: Sequence[ScoreRow]) -> None:
        if rows:
            self.session.execute(
                insert(ScoreResult),
                [{"scoring_run_id": scoring_run_id, **_clean(asdict(r))} for r in rows],
            )

    def write_factor_scores(self, scoring_run_id: int, rows: Sequence[FactorScoreRow]) -> None:
        if rows:
            self.session.execute(
                insert(FactorScore),
                [{"scoring_run_id": scoring_run_id, **_clean(asdict(r))} for r in rows],
            )

    # --- Profile (P2b.1, ADR-0009): nur anfuegen ----------------------------

    def write_profile(self, name: str) -> int:
        stmt = insert(Profile).values(name=name).returning(Profile.id)
        return self.session.execute(stmt).scalar_one()

    def write_profile_version(
        self,
        profile_id: int,
        params: Mapping[str, Any],
        *,
        parent_version: int | None = None,
        comment: str | None = None,
    ) -> int:
        """Legt die naechste Version des Profils an (1, 2, ...) und liefert ihre Nummer.

        Speichern zwei gleichzeitig, scheitert der zweite am Schluessel, statt zu ueberschreiben.
        """
        version = self._newest_version(profile_id) + 1
        self.session.execute(
            insert(ProfileVersion).values(
                profile_id=profile_id,
                version=version,
                params=json_safe(dict(params)),
                parent_version=parent_version,
                comment=comment,
            )
        )
        return version

    def write_profile_activation(self, profile_id: int, version: int) -> None:
        """Macht die Version aktiv, auch eine aeltere (Zurueckrollen)."""
        self.session.execute(
            insert(ProfileActivation).values(profile_id=profile_id, version=version)
        )

    def ensure_profile(
        self, name: str, params: Mapping[str, Any], *, comment: str
    ) -> tuple[ProfileVersionRef, bool]:
        """Legt das Profil mit Version 1 an, falls es den Namen noch nicht gibt.

        Aktiviert wird nur, wenn noch keine Version aktiv ist: Ein anderes aktives Profil
        bleibt aktiv. Liefert die aktive Version und ob das Profil neu ist. Gleichzeitige
        Aufrufe legen es nur einmal an (``ON CONFLICT DO NOTHING`` auf den Namen).
        """
        stmt = (
            pg_insert(Profile)
            .values(name=name)
            .on_conflict_do_nothing(index_elements=[Profile.name])
            .returning(Profile.id)
        )
        new_id = self.session.execute(stmt).scalar()
        if new_id is not None:
            self.write_profile_version(new_id, params, comment=comment)
        if self.get_active_profile_version() is None:
            profile_id = new_id if new_id is not None else self.get_profile_id(name)
            newest = 0 if profile_id is None else self._newest_version(profile_id)
            if profile_id is not None and newest > 0:
                self.write_profile_activation(profile_id, newest)
        active = self.get_active_profile_version()
        if active is None:
            msg = f"Profil {name} hat keine Version, nichts ist aktiv"
            raise LookupError(msg)
        return active, new_id is not None

    def get_profile_id(self, name: str) -> int | None:
        return self.session.execute(select(Profile.id).where(Profile.name == name)).scalar()

    def get_profile_version(self, profile_id: int, version: int) -> ProfileVersionRef | None:
        row = self.session.execute(
            _profile_versions().where(
                ProfileVersion.profile_id == profile_id, ProfileVersion.version == version
            )
        ).one_or_none()
        return None if row is None else _version_ref(row)

    def get_active_profile_version(self) -> ProfileVersionRef | None:
        """Die Version der juengsten Aktivierung, ueber alle Profile."""
        newest = (
            select(ProfileActivation.profile_id, ProfileActivation.version)
            .order_by(ProfileActivation.activated_at.desc(), ProfileActivation.id.desc())
            .limit(1)
            .subquery()
        )
        row = self.session.execute(
            _profile_versions().join(
                newest,
                (newest.c.profile_id == ProfileVersion.profile_id)
                & (newest.c.version == ProfileVersion.version),
            )
        ).one_or_none()
        return None if row is None else _version_ref(row)

    def _newest_version(self, profile_id: int) -> int:
        newest = self.session.execute(
            select(func.max(ProfileVersion.version)).where(ProfileVersion.profile_id == profile_id)
        ).scalar()
        return int(newest or 0)

    # --- get ---------------------------------------------------------------

    def get_scoring_run(self, scoring_run_id: int) -> ScoringRun | None:
        return self.session.get(ScoringRun, scoring_run_id)

    def get_scoring_runs(
        self,
        *,
        scoring_run_ids: Collection[int] = (),
        fetch_run_ids: Collection[int] = (),
        origins: Collection[str] | None = None,
    ) -> list[ScoringRun]:
        """Bewertungslaeufe nach ID oder bewertetem Abruf (beides: Vereinigung), sonst alle.

        ``origins`` beschraenkt auf bestimmte Herkuenfte, z. B. ohne Rescores.
        """
        stmt = select(ScoringRun).order_by(ScoringRun.id)
        if scoring_run_ids or fetch_run_ids:
            stmt = stmt.where(
                or_(
                    ScoringRun.id.in_(list(scoring_run_ids)),
                    ScoringRun.fetch_run_id.in_(list(fetch_run_ids)),
                )
            )
        if origins is not None:
            stmt = stmt.where(ScoringRun.origin.in_(list(origins)))
        return list(self.session.scalars(stmt))

    def get_scores_df(self, scoring_run_id: int) -> pd.DataFrame:
        columns = [
            "passed_filter",
            "value_score",
            "quality_score",
            "composite_score",
            "value_trap_flag",
            "rank_overall",
        ]
        stmt = (
            select(_instrument.c.symbol, *(getattr(ScoreResult, c) for c in columns))
            .join(_instrument, _instrument.c.id == ScoreResult.instrument_id)
            .where(ScoreResult.scoring_run_id == scoring_run_id)
            .order_by(ScoreResult.rank_overall.asc().nulls_last(), _instrument.c.symbol)
        )
        return _frame(self.session, stmt, ["symbol", *columns])

    def get_factor_scores_df(self, scoring_run_id: int) -> pd.DataFrame:
        columns = [
            "factor_key",
            "category",
            "source_column",
            "direction",
            "raw_value",
            "percentile_rank",
        ]
        stmt = (
            select(_instrument.c.symbol, *(getattr(FactorScore, c) for c in columns))
            .join(_instrument, _instrument.c.id == FactorScore.instrument_id)
            .where(FactorScore.scoring_run_id == scoring_run_id)
            .order_by(_instrument.c.symbol, FactorScore.factor_key)
        )
        return _frame(self.session, stmt, ["symbol", *columns])

    def get_score_history(self, symbol: str) -> pd.DataFrame:
        columns = [
            "passed_filter",
            "value_score",
            "quality_score",
            "composite_score",
            "value_trap_flag",
            "rank_overall",
        ]
        stmt = (
            select(
                ScoringRun.id,
                ScoringRun.created_at,
                ScoringRun.origin,
                *(getattr(ScoreResult, c) for c in columns),
            )
            .join(ScoreResult, ScoreResult.scoring_run_id == ScoringRun.id)
            .join(_instrument, _instrument.c.id == ScoreResult.instrument_id)
            .where(_instrument.c.symbol == symbol)
            .order_by(ScoringRun.created_at, ScoringRun.id)
        )
        return _frame(self.session, stmt, ["scoring_run_id", "created_at", "origin", *columns])


def _profile_versions() -> Any:
    return select(
        ProfileVersion.profile_id, Profile.name, ProfileVersion.version, ProfileVersion.params
    ).join(Profile, Profile.id == ProfileVersion.profile_id)


def _version_ref(row: Any) -> ProfileVersionRef:
    return ProfileVersionRef(
        profile_id=int(row.profile_id),
        name=str(row.name),
        version=int(row.version),
        params=dict(row.params),
    )


def _clean(row: dict[str, Any]) -> dict[str, Any]:
    return {k: to_python(v) for k, v in row.items()}


def _frame(session: Session, stmt: Any, columns: list[str]) -> pd.DataFrame:
    return pd.DataFrame([tuple(r) for r in session.execute(stmt).all()], columns=columns)
