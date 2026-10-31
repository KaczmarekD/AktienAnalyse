"""Scoring-Profile in der Datenbank (P2b.1, ADR-0009).

Jedes Speichern erzeugt eine neue, unveraenderliche Version. Aktiv ist die juengste Zeile der
Aktivierungen, ueber alle Profile. Das Profil "Standard" entsteht einmal aus den ENV-Werten.
"""

from __future__ import annotations

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from va_platform.db import session_scope
from va_scoring.adapters.postgres import ScoringRepository
from va_scoring.adapters.postgres.store import PostgresScoringStore
from va_scoring.domain.profile import DEFAULT_PROFILE_NAME, ProfileVersionRef

PARAMS = {"value_weight": 0.6, "min_market_cap": 3e8}


def _exec(engine: Engine, sql: str) -> None:
    with engine.begin() as conn:
        conn.execute(text(sql))


def _count(engine: Engine, table: str) -> int:
    with engine.connect() as conn:
        return conn.execute(text(f"SELECT count(*) FROM scoring.{table}")).scalar_one()


class TestVersions:
    def test_versions_count_per_profile_from_one(self, session):
        repo = ScoringRepository(session)
        a, b = repo.write_profile("A"), repo.write_profile("B")
        assert repo.write_profile_version(a, PARAMS) == 1
        assert repo.write_profile_version(a, {**PARAMS, "value_weight": 0.5}, parent_version=1) == 2
        assert repo.write_profile_version(b, PARAMS) == 1
        session.commit()

        second = repo.get_profile_version(a, 2)
        assert second == ProfileVersionRef(
            profile_id=a, name="A", version=2, params={**PARAMS, "value_weight": 0.5}
        )
        assert repo.get_profile_version(a, 3) is None

    def test_comment_and_parent_are_kept(self, session):
        repo = ScoringRepository(session)
        pid = repo.write_profile("A")
        repo.write_profile_version(pid, PARAMS, comment="Start")
        repo.write_profile_version(pid, PARAMS, parent_version=1, comment="nur Kommentar")
        session.commit()
        rows = session.execute(
            text(
                "SELECT version, parent_version, comment FROM scoring.profile_version "
                "ORDER BY version"
            )
        ).all()
        assert [tuple(r) for r in rows] == [(1, None, "Start"), (2, 1, "nur Kommentar")]

    def test_profile_names_are_unique(self, session):
        repo = ScoringRepository(session)
        repo.write_profile("A")
        with pytest.raises(IntegrityError):
            repo.write_profile("A")

    def test_parent_must_be_an_older_version_of_the_same_profile(self, session):
        repo = ScoringRepository(session)
        pid = repo.write_profile("A")
        with pytest.raises(IntegrityError):
            repo.write_profile_version(pid, PARAMS, parent_version=5)

    def test_get_profile_id_by_name(self, session):
        repo = ScoringRepository(session)
        pid = repo.write_profile("A")
        assert repo.get_profile_id("A") == pid
        assert repo.get_profile_id("fehlt") is None


class TestActivation:
    def test_nothing_is_active_without_an_activation(self, session):
        repo = ScoringRepository(session)
        repo.write_profile_version(repo.write_profile("A"), PARAMS)
        assert repo.get_active_profile_version() is None

    def test_newest_activation_wins_across_profiles(self, session):
        repo = ScoringRepository(session)
        a, b = repo.write_profile("A"), repo.write_profile("B")
        repo.write_profile_version(a, PARAMS)
        repo.write_profile_version(a, {**PARAMS, "value_weight": 0.5}, parent_version=1)
        repo.write_profile_version(b, PARAMS)

        repo.write_profile_activation(a, 1)
        repo.write_profile_activation(a, 2)
        assert repo.get_active_profile_version() == ProfileVersionRef(
            a, "A", 2, {**PARAMS, "value_weight": 0.5}
        )
        repo.write_profile_activation(b, 1)
        active = repo.get_active_profile_version()
        assert active is not None
        assert (active.name, active.version) == ("B", 1)

    def test_rollback_activates_an_older_version_again(self, session):
        repo = ScoringRepository(session)
        pid = repo.write_profile("A")
        repo.write_profile_version(pid, PARAMS)
        repo.write_profile_version(pid, {**PARAMS, "value_weight": 0.5}, parent_version=1)
        repo.write_profile_activation(pid, 2)
        repo.write_profile_activation(pid, 1)
        active = repo.get_active_profile_version()
        assert active is not None
        assert active.version == 1

    def test_only_existing_versions_can_be_activated(self, session):
        repo = ScoringRepository(session)
        pid = repo.write_profile("A")
        with pytest.raises(IntegrityError):
            repo.write_profile_activation(pid, 1)


class TestImmutable:
    """Versionen und Aktivierungen bleiben, wie sie sind (ADR-0003, ADR-0009)."""

    @pytest.fixture
    def stored(self, engine):
        with session_scope(engine) as s:
            repo = ScoringRepository(s)
            pid = repo.write_profile("A")
            repo.write_profile_version(pid, PARAMS)
            repo.write_profile_activation(pid, 1)

    @pytest.mark.usefixtures("stored")
    @pytest.mark.parametrize(
        "sql",
        [
            "UPDATE scoring.profile SET name = 'B'",
            "UPDATE scoring.profile_version SET params = '{}'",
            "UPDATE scoring.profile_activation SET version = 1",
            "DELETE FROM scoring.profile_activation",
            "DELETE FROM scoring.profile_version",
            "DELETE FROM scoring.profile",
        ],
    )
    def test_rejected(self, engine, sql):
        with pytest.raises(DBAPIError, match="verboten"):
            _exec(engine, sql)

    def test_app_role_can_create_and_activate(self, app_engine, read_engine):
        with session_scope(app_engine) as s:
            repo = ScoringRepository(s)
            pid = repo.write_profile("A")
            repo.write_profile_version(pid, PARAMS)
            repo.write_profile_activation(pid, 1)
        with session_scope(read_engine) as s:
            active = ScoringRepository(s).get_active_profile_version()
        assert active is not None
        assert active.name == "A"


class TestEnsureProfile:
    """Das Profil "Standard" entsteht einmal; danach gilt, was in der Datenbank steht."""

    def test_created_with_version_1_and_activated(self, session):
        repo = ScoringRepository(session)
        active, created = repo.ensure_profile("Standard", PARAMS, comment="aus ENV")
        assert created
        assert active == ProfileVersionRef(active.profile_id, "Standard", 1, PARAMS)
        assert repo.get_active_profile_version() == active

    def test_second_call_keeps_the_first_values(self, session):
        repo = ScoringRepository(session)
        first, _ = repo.ensure_profile("Standard", PARAMS, comment="aus ENV")
        again, created = repo.ensure_profile(
            "Standard", {**PARAMS, "value_weight": 0.9}, comment="aus ENV"
        )
        assert not created
        assert again == first

    def test_does_not_replace_another_active_profile(self, session):
        repo = ScoringRepository(session)
        own = repo.write_profile("Eigenes")
        repo.write_profile_version(own, PARAMS)
        repo.write_profile_activation(own, 1)

        active, created = repo.ensure_profile("Standard", PARAMS, comment="aus ENV")
        assert created  # angelegt ...
        assert active.name == "Eigenes"  # ... aber nicht aktiviert
        assert repo.get_profile_id("Standard") is not None


class TestDefaultProfileInTheStore:
    def test_standard_from_env_only_once(self, engine):
        store = PostgresScoringStore(engine, app_version="0.0.0")
        first = store.ensure_default_profile(PARAMS)
        second = store.ensure_default_profile({**PARAMS, "value_weight": 0.9})
        assert first == second
        assert (first.name, first.version, first.params) == (DEFAULT_PROFILE_NAME, 1, PARAMS)
        counts = {
            t: _count(engine, t) for t in ("profile", "profile_version", "profile_activation")
        }
        assert counts == {"profile": 1, "profile_version": 1, "profile_activation": 1}
