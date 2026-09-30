"""Import der Altdateien (Parquet-Cache + Ranking-CSV) in die Datenbank."""

from __future__ import annotations

import io
from datetime import date

import pandas as pd
from sqlalchemy import text

from src.db.engine import session_scope
from src.db.import_legacy import import_directory
from src.db.repositories.market_data import MarketDataRepository
from src.db.repositories.runs import RunRepository
from src.db.repositories.scoring import ScoringRepository
from src.reporting import build_report
from src.scoring import ScoringConfig, score


def _write_legacy_files(directory, universe_df: pd.DataFrame, day: date, *, parquet: bool = True):
    directory.mkdir(parents=True, exist_ok=True)
    if parquet:
        universe_df.to_parquet(directory / f"fundamentals_{day.isoformat()}.parquet", index=False)
    report = build_report(score(universe_df, ScoringConfig()), universe_size=len(universe_df))
    # Alt-CSVs hatten noch keine Spalte financial_currency
    csv = pd.read_csv(
        io.BytesIO(report.csv_bytes), sep=";", decimal=",", encoding="utf-8-sig"
    ).drop(columns=["financial_currency"], errors="ignore")
    csv.to_csv(
        directory / f"value_ranking_{day:%Y%m%d}.csv",
        sep=";",
        decimal=",",
        index=False,
        encoding="utf-8-sig",
    )


class TestImportLegacy:
    def test_imports_parquet_and_csv_as_import_runs(
        self, tmp_path, engine, db_url, mock_universe_df
    ):
        _write_legacy_files(tmp_path, mock_universe_df, date(2026, 8, 1))
        summary = import_directory(tmp_path, db_url)
        assert summary.imported == 2
        assert summary.skipped == 0

        with session_scope(engine) as s:
            runs = RunRepository(s).get_runs(kind="import")
            assert len(runs) == 1
            run = runs[0]
            assert run.status == "success"
            assert run.fetch_run_id is not None
            assert run.scoring_run_id is not None
            fetch_run = MarketDataRepository(s).get_fetch_run(run.fetch_run_id)
            assert fetch_run is not None
            assert fetch_run.origin == "import"
            assert fetch_run.note is not None
            assert "9265460" in fetch_run.note  # bekannter Dividenden-Fehler vor dem Fix
            snapshots = MarketDataRepository(s).get_snapshots_df(run.fetch_run_id)
            assert len(snapshots) == len(mock_universe_df)
            scores = ScoringRepository(s).get_scores_df(run.scoring_run_id)
            assert len(scores) == len(mock_universe_df) - 1  # CSV enthaelt nur gefilterte Titel

    def test_second_import_skips_known_files(self, tmp_path, engine, db_url, mock_universe_df):
        _write_legacy_files(tmp_path, mock_universe_df, date(2026, 8, 1))
        import_directory(tmp_path, db_url)
        summary = import_directory(tmp_path, db_url)
        assert summary.imported == 0
        assert summary.skipped == 2
        with engine.connect() as conn:
            assert conn.execute(text("SELECT count(*) FROM batch.run")).scalar() == 1

    def test_csv_without_parquet_creates_snapshots_from_csv(
        self, tmp_path, engine, db_url, mock_universe_df
    ):
        _write_legacy_files(tmp_path, mock_universe_df, date(2026, 8, 8), parquet=False)
        summary = import_directory(tmp_path, db_url)
        assert summary.imported == 1
        with session_scope(engine) as s:
            run = RunRepository(s).get_runs(kind="import")[0]
            assert run.fetch_run_id is not None
            snapshots = MarketDataRepository(s).get_snapshots_df(run.fetch_run_id)
            assert "VAL.DE" in set(snapshots["symbol"])
            assert "SMALL.DE" not in set(snapshots["symbol"])

    def test_late_csv_uses_universe_size_of_known_parquet(
        self, tmp_path, engine, db_url, mock_universe_df
    ):
        day = date(2026, 8, 15)
        _write_legacy_files(tmp_path, mock_universe_df, day)
        csv = tmp_path / f"value_ranking_{day:%Y%m%d}.csv"
        parked = tmp_path.parent / f"{tmp_path.name}_parked.csv"
        csv.rename(parked)
        import_directory(tmp_path, db_url)  # zuerst nur die Parquet-Datei
        parked.rename(csv)
        summary = import_directory(tmp_path, db_url)
        assert (summary.imported, summary.skipped) == (1, 1)
        with session_scope(engine) as s:
            first, second = RunRepository(s).get_runs(kind="import")
        assert second.fetch_run_id == first.fetch_run_id
        assert second.universe_size == len(mock_universe_df)

    def test_dry_run_preview_csv_is_not_imported(self, tmp_path, db_url):
        tmp_path.joinpath("preview_value_ranking_20261003.csv").write_text("x", encoding="utf-8")
        assert import_directory(tmp_path, db_url).imported == 0

    def test_unrelated_files_are_ignored(self, tmp_path, db_url):
        tmp_path.joinpath("dax_mdax_fallback.csv").write_text(
            "symbol,name,index\n", encoding="utf-8"
        )
        tmp_path.joinpath("preview_latest.html").write_text("<html>", encoding="utf-8")
        summary = import_directory(tmp_path, db_url)
        assert (summary.imported, summary.skipped) == (0, 0)
