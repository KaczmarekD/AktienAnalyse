"""Replay eines gespeicherten Abrufs durch die Handler von scoring und notification (P2b.0).

Ohne Datenbank: Der Fall entsteht aus dem Golden-Datensatz.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import date, datetime

import pandas as pd
import pytest

from src.regression.case import FACTOR_COLUMNS, SCORE_COLUMNS, ReplayCase
from src.regression.compare import compare_csv, compare_scores
from src.regression.replay import check, replay
from tests.conftest import GOLDEN_DIR
from va_contracts.events.v1 import FundamentalsV1, IdentityV1
from va_notification.domain.report import build_report
from va_scoring.domain.scoring import ScoringConfig, score

GOLDEN_INPUT = GOLDEN_DIR / "input_fundamentals.json"


def _snapshots() -> pd.DataFrame:
    return pd.DataFrame(json.loads(GOLDEN_INPUT.read_text(encoding="utf-8")))


def _expected_scores(snapshots: pd.DataFrame, cfg: ScoringConfig) -> pd.DataFrame:
    """So, wie der Speicher von scoring die Ergebnisse ablegt (auch gefilterte Titel)."""
    scored = score(snapshots, cfg)
    rows = [
        {
            "symbol": r["symbol"],
            "passed_filter": True,
            "value_score": r["value_score"],
            "quality_score": r["quality_score"],
            "composite_score": r["composite_score"],
            "value_trap_flag": bool(r["value_trap_flag"]),
            "rank_overall": int(r["rank_overall"]),
        }
        for r in scored.to_dict("records")
    ]
    rows += [
        {"symbol": s, "passed_filter": False}
        for s in snapshots["symbol"]
        if s not in set(scored["symbol"])
    ]
    return pd.DataFrame(rows, columns=list(SCORE_COLUMNS))


def _case(snapshots: pd.DataFrame | None = None) -> ReplayCase:
    snaps = _snapshots() if snapshots is None else snapshots
    return ReplayCase(
        scoring_run_id=7,
        fetch_run_id=3,
        origin="live",
        fetched_on=date(2026, 10, 3),
        universe_source="iShares",
        universe_as_of=date(2026, 10, 2),
        universe_size=len(snaps),
        config=None,
        generated_at=datetime(2026, 10, 3, 7, 30),
        snapshots=snaps,
        scores=_expected_scores(snaps, ScoringConfig()),
        factor_scores=pd.DataFrame(columns=list(FACTOR_COLUMNS)),
        csv=None,
    )


class TestReplay:
    def test_scores_are_those_of_score(self):
        result = replay(_case(), ScoringConfig())
        assert result.failure is None
        assert compare_scores(_case().scores, result.scores) == []

    def test_filtered_titles_are_kept_with_passed_filter_false(self):
        result = replay(_case(), ScoringConfig(min_market_cap=10e9))
        scores = result.scores.set_index("symbol")
        assert set(scores.index) == set(_snapshots()["symbol"])
        assert (~scores["passed_filter"]).any()

    def test_factor_ranks_match_the_rank_columns_of_score(self):
        cfg = ScoringConfig()
        result = replay(_case(), cfg)
        assert list(result.factor_scores.columns) == list(FACTOR_COLUMNS)
        scored = score(_snapshots(), cfg).set_index("symbol")
        assert set(result.factor_scores["factor_key"]) <= {
            *cfg.value_factors,
            *cfg.quality_factors,
        }
        for row in result.factor_scores.to_dict("records"):
            expected = scored.loc[row["symbol"], f"rank_{row['factor_key']}"]
            assert row["percentile_rank"] == pytest.approx(expected, nan_ok=True)

    def test_report_csv_is_the_one_of_the_batch(self):
        # Ueber den Bus hat jeder Titel alle Felder des Contracts, wie ein DB-Snapshot
        flat = list(FundamentalsV1(identity=IdentityV1(symbol="", name="", index="")).to_flat())
        snapshots = _snapshots().reindex(columns=flat)
        result = replay(_case(snapshots), ScoringConfig())
        assert result.csv is not None
        direct = build_report(score(snapshots, ScoringConfig()), now=datetime(2026, 10, 3))
        assert compare_csv(direct.csv_bytes, result.csv) == []

    def test_without_scoreable_titles_the_run_fails_with_no_data(self):
        snaps = _snapshots().assign(market_cap=1.0)
        result = replay(_case(snaps), ScoringConfig())
        assert result.failure == "no_data"
        assert result.csv is None
        assert not result.scores["passed_filter"].any()


class TestCheck:
    def test_stored_scores_only_are_compared_when_nothing_else_was_stored(self):
        outcome = check(_case(), ScoringConfig())
        assert outcome.equal
        assert outcome.checked == ("scores",)

    def test_factor_ranks_and_csv_are_compared_when_stored(self):
        case = _case()
        result = replay(case, ScoringConfig())
        stored = replace(case, factor_scores=result.factor_scores, csv=result.csv)
        outcome = check(stored, ScoringConfig())
        assert outcome.equal
        assert outcome.checked == ("scores", "factors", "csv")

    def test_other_weights_change_the_composite(self):
        outcome = check(_case(), ScoringConfig(value_weight=0.5, quality_weight=0.5))
        assert not outcome.equal
        assert {d.field for d in outcome.differences} >= {"composite_score"}

    def test_a_failed_replay_is_a_difference(self):
        case = _case()
        stored = replace(case, snapshots=case.snapshots.assign(market_cap=1.0))
        outcome = check(stored, ScoringConfig())
        assert not outcome.equal
        assert outcome.failure == "no_data"


class TestJson:
    def test_round_trip_keeps_the_case(self):
        case = _case()
        result = replay(case, ScoringConfig())
        case = replace(case, factor_scores=result.factor_scores, csv=result.csv)
        back = ReplayCase.from_json(case.to_json())
        assert (back.scoring_run_id, back.fetch_run_id, back.origin) == (7, 3, "live")
        assert (back.fetched_on, back.universe_as_of) == (date(2026, 10, 3), date(2026, 10, 2))
        assert back.generated_at == datetime(2026, 10, 3, 7, 30)
        assert back.csv == case.csv
        # Die Datei ordnet nach Symbol, die Reihenfolge gehoert nicht zum Fall
        pd.testing.assert_frame_equal(
            back.snapshots,
            case.snapshots.sort_values("symbol", ignore_index=True),
            check_dtype=False,
        )
        assert check(back, ScoringConfig()).equal

    def test_file_name_names_day_and_scoring_run(self):
        assert _case().file_name == "2026-10-03_scoring-run-7.json"

    def test_expected_values_can_be_renewed_from_a_replay(self):
        case = _case()
        result = replay(case, ScoringConfig(value_weight=0.5, quality_weight=0.5))
        renewed = case.with_expected(result)
        assert check(renewed, ScoringConfig(value_weight=0.5, quality_weight=0.5)).equal
        pd.testing.assert_frame_equal(renewed.snapshots, case.snapshots)


class TestCli:
    def test_unreachable_database_is_an_error(self, settings, capsys):
        from pydantic import SecretStr

        from src.regression.cli import EXIT_ERROR, main

        offline = settings.model_copy(
            update={
                "database_url": SecretStr(
                    "postgresql+psycopg://va:x@127.0.0.1:1/none?connect_timeout=2"
                )
            }
        )
        assert main([], settings=offline) == EXIT_ERROR
        assert "Datenbank" in capsys.readouterr().out

    def test_scoring_run_and_fetch_run_must_be_numbers(self, settings):
        from src.regression.cli import main

        with pytest.raises(SystemExit):
            main(["--scoring-run", "abc"], settings=settings)

    def test_a_broken_run_does_not_stop_the_others(self, settings, monkeypatch, capsys):
        from src.regression import cli

        broken = replace(_case(), scoring_run_id=8)
        broken = replace(broken, snapshots=broken.snapshots.assign(market_cap="kaputt"))
        monkeypatch.setattr(cli, "load_cases", lambda *a, **k: [broken, _case()])
        assert cli.main([], settings=settings) == cli.EXIT_ERROR
        out = capsys.readouterr().out
        assert "Bewertungslauf #8 (Abruf #3 vom 03.10.2026, live): Replay gescheitert" in out
        assert "Bewertungslauf #7 (Abruf #3 vom 03.10.2026, live): gleich (Scores)" in out
        assert "Ergebnis: 1 von 2 Bewertungslaeufen gleich" in out
