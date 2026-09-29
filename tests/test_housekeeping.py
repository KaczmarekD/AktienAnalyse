"""Tests fuer das Aufraeumen alter Laufartefakte."""

from __future__ import annotations

from datetime import date

from src.housekeeping import cleanup_old_artifacts

TODAY = date(2026, 9, 29)


def _touch(path):
    path.write_text("x", encoding="utf-8")
    return path


class TestCleanupOldArtifacts:
    def test_removes_old_parquet_and_csv(self, tmp_path):
        old_pq = _touch(tmp_path / "fundamentals_2026-05-01.parquet")
        old_csv = _touch(tmp_path / "value_ranking_20260501.csv")

        removed = cleanup_old_artifacts(tmp_path, retention_days=90, today=TODAY)

        assert set(removed) == {old_pq, old_csv}
        assert not old_pq.exists()
        assert not old_csv.exists()

    def test_keeps_recent_files(self, tmp_path):
        recent_pq = _touch(tmp_path / "fundamentals_2026-09-20.parquet")
        recent_csv = _touch(tmp_path / "value_ranking_20260920.csv")

        assert cleanup_old_artifacts(tmp_path, retention_days=90, today=TODAY) == []
        assert recent_pq.exists()
        assert recent_csv.exists()

    def test_cutoff_day_is_kept(self, tmp_path):
        # 2026-07-01 ist genau 90 Tage vor TODAY
        boundary = _touch(tmp_path / "value_ranking_20260701.csv")
        assert cleanup_old_artifacts(tmp_path, retention_days=90, today=TODAY) == []
        assert boundary.exists()

    def test_never_touches_unrelated_files(self, tmp_path):
        fallback = _touch(tmp_path / "dax_mdax_fallback.csv")
        preview = _touch(tmp_path / "preview_latest.html")
        bogus_date = _touch(tmp_path / "value_ranking_20261399.csv")

        assert cleanup_old_artifacts(tmp_path, retention_days=1, today=TODAY) == []
        assert fallback.exists()
        assert preview.exists()
        assert bogus_date.exists()

    def test_zero_retention_disables_cleanup(self, tmp_path):
        old = _touch(tmp_path / "fundamentals_2020-01-01.parquet")
        assert cleanup_old_artifacts(tmp_path, retention_days=0, today=TODAY) == []
        assert old.exists()

    def test_missing_dir_is_noop(self, tmp_path):
        assert cleanup_old_artifacts(tmp_path / "gibts-nicht", retention_days=90) == []
