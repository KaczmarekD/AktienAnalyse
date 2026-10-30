"""Replay-Regression gegen ein echtes PostgreSQL (P2b.0).

Ein kompletter Lauf (Yahoo gepatcht wie in ``test_pipeline_db``) oder ein Altdaten-Import
legt die Woche an, das Werkzeug spielt sie nur lesend nach.
"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from src.composition import scoring_config
from src.db.import_legacy import import_directory
from src.db.repositories.runs import RunRepository
from src.regression.case import ReplayCase, Skipped, load_cases
from src.regression.cli import EXIT_DIFFERENT, EXIT_EQUAL, EXIT_ERROR, format_outcome, main
from src.regression.replay import check
from tests.db.test_import_legacy import _write_legacy_files
from tests.db.test_pipeline_db import _patched_run
from va_platform.db import create_db_engine, session_scope
from va_scoring.adapters.postgres import ScoringRepository
from va_scoring.domain.scoring import ScoringConfig

SYMBOLS = {"AAA.DE", "BBB.DE", "CCC.DE", "TINY.DE"}


def _cases(db_url: str) -> list[ReplayCase | Skipped]:
    engine = create_db_engine(db_url, read_only=True)
    try:
        return load_cases(engine)
    finally:
        engine.dispose()


def _latest_run(engine):
    with session_scope(engine) as s:
        run = RunRepository(s).get_latest_run()
        assert run is not None
        return run


class TestLiveRun:
    def test_stored_run_is_loaded_completely(self, db_settings, db_url):
        rc, _, _ = _patched_run(db_settings)
        assert rc == 0
        [case] = _cases(db_url)
        assert isinstance(case, ReplayCase)
        assert case.origin == "live"
        assert set(case.snapshots["symbol"]) == SYMBOLS
        assert set(case.scores["symbol"]) == SYMBOLS
        assert not case.factor_scores.empty
        assert case.csv is not None
        assert case.csv.startswith(b"\xef\xbb\xbf")
        assert (case.universe_source, case.universe_as_of) == ("iShares", date(2026, 9, 29))
        assert case.config is not None
        assert case.generated_at is not None

    def test_replay_of_the_run_is_equal(self, db_settings, capsys):
        _patched_run(db_settings)
        assert main([], settings=db_settings) == EXIT_EQUAL
        out = capsys.readouterr().out
        assert "gleich" in out
        assert "Scores, Faktor-Raenge, CSV" in out

    def test_other_weights_are_reported_as_differences(self, db_settings, capsys):
        _patched_run(db_settings)
        changed = db_settings.model_copy(update={"value_weight": 0.5, "quality_weight": 0.5})
        assert main([], settings=changed) == EXIT_DIFFERENT
        out = capsys.readouterr().out
        assert "composite_score" in out
        assert "Konfiguration weicht" in out

    def test_selection_by_fetch_run_and_scoring_run(self, db_settings, engine, capsys):
        _patched_run(db_settings)
        _patched_run(db_settings)  # zweiter Lauf am selben Tag nutzt den Abruf wieder
        run = _latest_run(engine)
        assert main(["--fetch-run", str(run.fetch_run_id)], settings=db_settings) == EXIT_EQUAL
        assert capsys.readouterr().out.count("Bewertungslauf #") == 2
        assert main(["--scoring-run", str(run.scoring_run_id)], settings=db_settings) == EXIT_EQUAL
        assert capsys.readouterr().out.count("Bewertungslauf #") == 1

    def test_unknown_run_is_nothing_to_compare(self, db_settings, capsys):
        _patched_run(db_settings)
        assert main(["--scoring-run", "999"], settings=db_settings) == EXIT_ERROR
        assert "nichts zu vergleichen" in capsys.readouterr().out

    def test_export_writes_a_fixture_that_replays_equal(self, db_settings, tmp_path):
        _patched_run(db_settings)
        target = tmp_path / "replay"
        assert main(["--export", str(target)], settings=db_settings) == EXIT_EQUAL
        [path] = target.glob("*.json")
        case = ReplayCase.from_json(path.read_text(encoding="utf-8"))
        assert set(case.snapshots["symbol"]) == SYMBOLS
        assert check(case, scoring_config(db_settings)).equal


class TestImportedRun:
    def test_imported_week_is_compared_by_scores_only(self, tmp_path, db_url, mock_universe_df):
        _write_legacy_files(tmp_path, mock_universe_df, date(2026, 8, 1))
        import_directory(tmp_path, db_url)
        [case] = _cases(db_url)
        assert isinstance(case, ReplayCase)
        assert case.origin == "import"
        assert case.factor_scores.empty
        assert case.csv is None
        assert case.config is None
        outcome = check(case, ScoringConfig())
        assert outcome.checked == ("scores",)
        assert outcome.equal, format_outcome(outcome)

    def test_scoring_run_without_fetch_run_is_skipped(self, engine, db_url, db_settings, capsys):
        with session_scope(engine) as s:
            scoring_run_id = ScoringRepository(s).write_scoring_run(
                fetch_run_id=None, config=None, app_version="legacy", origin="import"
            )
        [skipped] = _cases(db_url)
        assert skipped == Skipped(scoring_run_id, "ohne Abruf")
        assert main([], settings=db_settings) == EXIT_ERROR
        assert "uebersprungen" in capsys.readouterr().out


class TestReadOnly:
    def test_read_only_engine_cannot_write(self, db_url):
        engine = create_db_engine(db_url, read_only=True)
        try:
            with pytest.raises(DBAPIError, match="read-only"), engine.begin() as conn:
                conn.execute(text("CREATE TABLE public.probe (id int)"))
        finally:
            engine.dispose()
