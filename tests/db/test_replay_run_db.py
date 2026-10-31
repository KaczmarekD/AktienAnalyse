"""U5.1: Ein ganzer Lauf mit ``REPLAY_SOURCE`` gegen die echte Datenbank.

Er reproduziert die Fixture: dieselben Scores, Faktor-Raenge und dieselbe CSV. Der Abruf ist
als Replay gekennzeichnet.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

from sqlalchemy import text

from src.composition import build_adapters
from src.main import _run
from src.regression.case import ReplayCase, load_cases
from src.regression.compare import compare_csv, compare_factor_scores, compare_scores

FIXTURE = Path(__file__).parents[1] / "fixtures" / "replay" / "2026-10-30_scoring-run-1.json"


def _replay_run(settings):
    send = Mock()
    adapters = replace(
        build_adapters(settings),
        sender=Mock(send=send),
        heartbeat=Mock(ping=Mock(return_value=None)),
    )
    rc = _run(settings, force_refresh=False, dry_run=False, adapters=adapters)
    return rc, send


def test_replay_run_reproduces_the_fixture(db_settings, engine):
    settings = db_settings.model_copy(update={"replay_source": FIXTURE, "smtp_plain": True})
    rc, send = _replay_run(settings)

    assert rc == 0
    send.assert_called_once()
    expected = ReplayCase.from_json(FIXTURE.read_text(encoding="utf-8"))
    [stored] = load_cases(engine)
    assert isinstance(stored, ReplayCase)
    assert compare_scores(expected.scores, stored.scores) == []
    assert compare_factor_scores(expected.factor_scores, stored.factor_scores) == []
    assert expected.csv is not None
    assert stored.csv is not None
    assert compare_csv(expected.csv, stored.csv) == []


def test_replayed_fetch_is_marked(db_settings, engine):
    settings = db_settings.model_copy(update={"replay_source": FIXTURE, "smtp_plain": True})
    _replay_run(settings)

    with engine.connect() as conn:
        fetch = conn.execute(
            text("SELECT provider, provider_version, universe_source FROM market_data.fetch_run")
        ).one()
        replay_source = conn.execute(
            text("SELECT settings->>'replay_source' FROM batch.run")
        ).scalar_one()
    assert fetch == ("replay", FIXTURE.name, "Replay")
    assert replay_source is not None
    assert replay_source.endswith(FIXTURE.name)
