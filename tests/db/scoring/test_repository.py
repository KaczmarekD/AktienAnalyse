"""get/write-Zugriffe auf das Schema scoring."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.exc import IntegrityError

from va_contracts.events.v1 import PlacementV1
from va_market_data.adapters.postgres import MarketDataRepository
from va_platform.db import session_scope
from va_scoring.adapters.postgres import FactorScoreRow, ScoreRow, ScoringRepository
from va_scoring.adapters.postgres.store import PostgresScoringStore

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

    def test_value_trap_reason_is_stored(self, session):
        """F2.3: Das Ergebnis hält fest, welche Regel das Flag gesetzt hat."""
        from sqlalchemy import text

        ids = MarketDataRepository(session).get_or_create_instruments(["BAD.DE", "OK.DE"])
        repo = ScoringRepository(session)
        sid = repo.write_scoring_run(fetch_run_id=7, config={}, app_version="x", origin="live")
        repo.write_score_results(
            sid,
            [
                ScoreRow(ids["BAD.DE"], True, 0.9, 0.6, 0.78, True, 1, "momentum"),
                ScoreRow(ids["OK.DE"], True, 0.5, 0.5, 0.5, False, 2),
            ],
        )
        session.commit()
        rows = session.execute(
            text(
                "SELECT instrument_id, value_trap_reason FROM scoring.score_result "
                "WHERE scoring_run_id = :sid"
            ),
            {"sid": sid},
        ).all()
        assert dict(rows) == {ids["BAD.DE"]: "momentum", ids["OK.DE"]: None}

    def test_anchor_values_roundtrip(self, session):
        """F3.1: Anker im Long-Format, nur Werte, die es gibt."""
        from va_scoring.adapters.postgres import AnchorRow

        ids = MarketDataRepository(session).get_or_create_instruments(["SAP.DE"])
        repo = ScoringRepository(session)
        sid = repo.write_scoring_run(fetch_run_id=7, config={}, app_version="x", origin="live")
        repo.write_anchor_values(
            sid,
            [
                AnchorRow(ids["SAP.DE"], "price_to_epv", 1.25),
                AnchorRow(ids["SAP.DE"], "implied_fcf_growth", 0.07),
            ],
        )
        session.commit()
        assert repo.get_anchor_values_df(sid).to_dict("records") == [
            {"symbol": "SAP.DE", "anchor": "implied_fcf_growth", "value": 0.07},
            {"symbol": "SAP.DE", "anchor": "price_to_epv", "value": 1.25},
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


def _placement(**values: object) -> dict[str, object]:
    row: dict[str, object] = {
        "symbol": "AAPL",
        "isin": None,
        "instrument_id": None,
        "value_score": None,
        "quality_score": None,
        "composite_score": None,
        "composite_percentile": None,
        "factor_ranks": {},
        "value_trap_flag": False,
        "value_trap_reason": None,
        "industry_rule": False,
        "below_size_filter": False,
        "reason": None,
    }
    return {**row, **values}


class TestPlacement:
    """D4.1: Einordnungen der Depot-Aktien je Bewertungslauf, nur zum Anfügen."""

    def test_placements_roundtrip(self, session):
        repo = ScoringRepository(session)
        sid = repo.write_scoring_run(fetch_run_id=7, config={}, app_version="x", origin="live")
        repo.write_placements(
            sid,
            [
                _placement(
                    isin="US0378331005",
                    instrument_id=91,
                    value_score=0.31,
                    quality_score=0.94,
                    composite_score=0.562,
                    composite_percentile=0.68,
                    factor_ranks={"ev_ebit": 0.22, "roic": None},
                ),
                _placement(
                    symbol="TINY.DE",
                    value_score=0.7,
                    industry_rule=True,
                    below_size_filter=True,
                    reason="no_quality",
                ),
            ],
        )
        repo.write_placements(sid, [])
        session.commit()
        placements = repo.get_placements(sid)
        assert [p["symbol"] for p in placements] == ["AAPL", "TINY.DE"]
        assert placements[0]["factor_ranks"] == {"ev_ebit": 0.22, "roic": None}
        assert placements[0]["composite_percentile"] == 0.68
        assert (placements[1]["reason"], placements[1]["below_size_filter"]) == ("no_quality", True)
        assert repo.get_placements(sid + 1) == []

    def test_unknown_reason_is_rejected(self, session):
        repo = ScoringRepository(session)
        sid = repo.write_scoring_run(fetch_run_id=7, config={}, app_version="x", origin="live")
        with pytest.raises(IntegrityError):
            repo.write_placements(sid, [_placement(reason="too_small")])

    def test_the_store_writes_the_event_rows(self, engine):
        with session_scope(engine) as s:
            sid = ScoringRepository(s).write_scoring_run(
                fetch_run_id=7, config={}, app_version="x", origin="live"
            )
        placement = PlacementV1(symbol="AAPL", isin="US0378331005", factor_ranks={"pb": 0.4})
        PostgresScoringStore(engine, app_version="x").record_placements(sid, [placement])
        with session_scope(engine) as s:
            [row] = ScoringRepository(s).get_placements(sid)
        assert PlacementV1.model_validate(row) == placement
