"""get/write-Zugriffe auf das Schema scoring."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from va_market_data.adapters.postgres import MarketDataRepository
from va_platform.db import session_scope
from va_scoring.adapters.postgres import FactorScoreRow, ScoreRow, ScoringRepository

T0 = datetime(2026, 10, 3, 5, 30, tzinfo=UTC)


class TestScoring:
    def test_scores_and_factor_ranks_roundtrip(self, session):
        ids = MarketDataRepository(session).get_or_create_instruments(["SAP.DE", "TINY.DE"])
        repo = ScoringRepository(session)
        sid = repo.write_scoring_run(
            fetch_run_id=7, config={"value_weight": 0.6}, app_version="0.3.0", origin="live"
        )
        repo.write_score_results(
            sid,
            [
                ScoreRow(ids["SAP.DE"], True, 0.8, 0.6, 0.72, False, 1),
                ScoreRow(ids["TINY.DE"], False, None, None, None, None, None),
            ],
        )
        repo.write_factor_scores(
            sid, [FactorScoreRow(ids["SAP.DE"], "ev_ebit", "value", "ev_ebit", "low", 22.0, 0.8)]
        )
        session.commit()

        run = repo.get_scoring_run(sid)
        assert run is not None
        assert run.config == {"value_weight": 0.6}
        assert run.config_hash  # deterministischer Hash der Konfiguration
        scores = repo.get_scores_df(sid).set_index("symbol")
        assert scores.loc["SAP.DE", "composite_score"] == 0.72
        assert not scores.loc["TINY.DE", "passed_filter"]
        factors = repo.get_factor_scores_df(sid)
        assert factors[["symbol", "factor_key", "raw_value", "percentile_rank"]].to_dict(
            "records"
        ) == [
            {"symbol": "SAP.DE", "factor_key": "ev_ebit", "raw_value": 22.0, "percentile_rank": 0.8}
        ]

    def test_same_config_same_hash(self, session):
        repo = ScoringRepository(session)
        a = repo.write_scoring_run(fetch_run_id=1, config={"b": 1, "a": 2}, app_version="x")
        b = repo.write_scoring_run(fetch_run_id=2, config={"a": 2, "b": 1}, app_version="x")
        assert repo.get_scoring_run(a).config_hash == repo.get_scoring_run(b).config_hash  # type: ignore[union-attr]

    def test_score_history_orders_by_time(self, engine):
        with session_scope(engine) as s:
            iid = MarketDataRepository(s).get_or_create_instruments(["SAP.DE"])["SAP.DE"]
            repo = ScoringRepository(s)
            for week, composite in enumerate((0.6, 0.7)):
                sid = repo.write_scoring_run(
                    fetch_run_id=week,
                    config={},
                    app_version="x",
                    created_at=T0 + timedelta(days=7 * week),
                )
                repo.write_score_results(sid, [ScoreRow(iid, True, 0.5, 0.5, composite, False, 1)])
        with session_scope(engine) as s:
            history = ScoringRepository(s).get_score_history("SAP.DE")
        assert list(history["composite_score"]) == [0.6, 0.7]
