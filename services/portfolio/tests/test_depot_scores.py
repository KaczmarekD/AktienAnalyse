"""Scores im Depot (D4.2, ANA-01; docs/architecture/depot/analyse.md).

- ``scoring.run.completed`` landet in der Kopie ``score_view``: Ranking-Zeilen mit Rang und
  Einordnungen (unter dem Größenfilter, von außerhalb), nur mit ISIN.
- Je ISIN gilt der jüngste Bewertungslauf, der sie kennt.
- ``depots.get`` trägt je Aktie ihre Scores, eine Aktie aus DAX/MDAX dieselben wie im Ranking.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from va_contracts import new_envelope
from va_contracts.events.v1 import (
    PLACEMENTS_UPDATED,
    SCORING_RUN_COMPLETED,
    FundamentalsV1,
    IdentityV1,
    PlacementsUpdatedV1,
    PlacementV1,
    RankingRowV1,
    RunOptionsV1,
    ScoringRunCompletedV1,
    UniverseInfoV1,
)
from va_contracts.rpc.v1 import DEPOTS_GET, DepotRefRequestV1, DepotReplyV1
from va_platform.bus import InProcessBus
from va_portfolio.adapters.memory import MemoryDepotStore, MemoryMarketStore
from va_portfolio.application.depots import DepotService
from va_portfolio.domain.depots import HoldingLine
from va_portfolio.entrypoints import handlers as market_handlers
from va_portfolio.entrypoints.rpc import handlers

ANNA = 1
SAP = "DE0007164600"
APPLE = "US0378331005"
TINY = "DE000A0TINY0"
FRIDAY = date(2026, 11, 20)
NEXT_FRIDAY = date(2026, 11, 27)


def _row(symbol: str, isin: str | None, rank: int, **values: object) -> RankingRowV1:
    return RankingRowV1(
        fundamentals=FundamentalsV1(identity=IdentityV1(symbol=symbol, name=symbol, index="DAX")),
        rank_overall=rank,
        isin=isin,
        **values,  # type: ignore[arg-type]
    )


def _completed(
    scoring_run_id: int,
    as_of: date,
    ranking: list[RankingRowV1],
    placements: list[PlacementV1] | None = None,
):
    return new_envelope(
        SCORING_RUN_COMPLETED,
        ScoringRunCompletedV1(
            run_id=4,
            trigger="scheduled",
            options=RunOptionsV1(),
            scoring_run_id=scoring_run_id,
            fetch_run_id=3,
            as_of=as_of,
            universe=UniverseInfoV1(source="iShares", as_of=as_of, size=90),
            value_weight=0.6,
            quality_weight=0.4,
            ranking=ranking,
            placements=placements or [],
        ),
        source="va/scoring",
    )


SAP_ROW = _row(
    "SAP.DE",
    SAP,
    12,
    value_score=0.41,
    quality_score=0.83,
    composite_score=0.578,
    composite_percentile=0.71,
)
APPLE_PLACED = PlacementV1(
    symbol="AAPL",
    isin=APPLE,
    value_score=0.12,
    quality_score=0.97,
    composite_score=0.46,
    composite_percentile=0.38,
)
TINY_PLACED = PlacementV1(
    symbol="TINY.DE", isin=TINY, value_score=0.8, below_size_filter=True, reason="no_quality"
)


def _setup():
    bus = InProcessBus(max_deliver=1)
    market = MemoryMarketStore()
    market_handlers.wire(bus, market)
    service = DepotService(MemoryDepotStore(), market=market)
    return bus, market, service


def _depot_with(service: DepotService, *lines: HoldingLine) -> int:
    depot = service.create(ANNA, "depot", "DKB", None).depot
    service.save(ANNA, depot.id, 0, list(lines), [])
    return depot.id


def _positions(service: DepotService, depot_id: int):
    reply = handlers(service)[DEPOTS_GET](DepotRefRequestV1(user_id=ANNA, depot_id=depot_id))
    assert isinstance(reply, DepotReplyV1)
    assert reply.depot is not None
    assert reply.depot.valuation is not None
    return {p.isin: p for p in reply.depot.valuation.positions}


class TestScoreCopy:
    def test_ranking_and_placements_with_isin(self):
        bus, market, _ = _setup()
        no_isin = _row("NOISIN.DE", None, 13, value_score=0.5, quality_score=0.5)
        bus.publish(_completed(8, FRIDAY, [SAP_ROW, no_isin], [APPLE_PLACED, TINY_PLACED]))
        assert set(market.scores) == {SAP, APPLE, TINY}
        sap, apple, tiny = market.scores[SAP], market.scores[APPLE], market.scores[TINY]
        assert (sap.reference, sap.rank, sap.symbol) == ("universe", 12, "SAP.DE")
        assert (sap.scoring_run_id, sap.as_of) == (8, FRIDAY)
        assert (sap.composite_score, sap.composite_percentile, sap.reason) == (0.578, 0.71, None)
        assert (apple.reference, apple.rank) == ("outside", None)
        assert (tiny.reference, tiny.reason) == ("below_size_filter", "no_quality")

    def test_the_sector_comes_along(self):
        """D4.4: Sektor aus den Kennzahlen der Ranking-Zeile bzw. der Einordnung."""
        bus, market, _ = _setup()
        row = RankingRowV1(
            fundamentals=FundamentalsV1(
                identity=IdentityV1(symbol="SAP.DE", name="SAP", index="DAX", sector="Technology")
            ),
            rank_overall=1,
            isin=SAP,
        )
        placed = PlacementV1(symbol="AAPL", isin=APPLE, sector="Technology")
        bus.publish(_completed(8, FRIDAY, [row], [placed]))
        assert (market.scores[SAP].sector, market.scores[APPLE].sector) == ("Technology",) * 2

    def test_a_ranking_row_without_composite_says_why(self):
        bus, market, _ = _setup()
        bank = _row("CBK.DE", "DE000CBK1001", 40, value_score=0.9)
        bus.publish(_completed(8, FRIDAY, [bank]))
        assert market.scores["DE000CBK1001"].reason == "no_quality"

    def test_the_newest_scoring_run_wins(self):
        bus, market, _ = _setup()
        newer = _row("SAP.DE", SAP, 3, value_score=0.9, quality_score=0.9, composite_score=0.9)
        bus.publish(_completed(9, NEXT_FRIDAY, [newer]))
        bus.publish(_completed(8, FRIDAY, [SAP_ROW]))  # spaet zugestellt
        assert market.scores[SAP].scoring_run_id == 9
        assert market.scores[SAP].rank == 3

    def test_an_older_run_keeps_isins_the_newer_one_lacks(self):
        bus, market, _ = _setup()
        bus.publish(_completed(8, FRIDAY, [SAP_ROW], [APPLE_PLACED]))
        bus.publish(_completed(9, NEXT_FRIDAY, [SAP_ROW]))
        assert market.scores[APPLE].scoring_run_id == 8


class TestDepotWithScores:
    def test_each_stock_carries_its_scores(self):
        bus, _, service = _setup()
        bus.publish(_completed(8, FRIDAY, [SAP_ROW], [APPLE_PLACED]))
        depot_id = _depot_with(
            service, HoldingLine(SAP, Decimal(10)), HoldingLine(APPLE, Decimal(3))
        )
        positions = _positions(service, depot_id)
        sap = positions[SAP].score
        assert sap is not None
        # Abnahme D4: eine Aktie aus DAX/MDAX zeigt im Depot dieselben Scores wie im Ranking
        assert (sap.value_score, sap.quality_score, sap.composite_score, sap.rank) == (
            SAP_ROW.value_score,
            SAP_ROW.quality_score,
            SAP_ROW.composite_score,
            SAP_ROW.rank_overall,
        )
        assert (sap.reference, sap.scoring_run_id, sap.as_of) == ("universe", 8, FRIDAY)
        apple = positions[APPLE].score
        assert apple is not None
        assert (apple.reference, apple.composite_percentile) == ("outside", 0.38)

    def test_without_scores_none(self):
        _, _, service = _setup()
        depot_id = _depot_with(service, HoldingLine(SAP, Decimal(1)))
        assert _positions(service, depot_id)[SAP].score is None


class TestRightAway:
    """D4.6: eine neue Aktie, sofort gegen den letzten Bewertungslauf eingeordnet."""

    def _updated(self, bus: InProcessBus, scoring_run_id: int, *placements: PlacementV1) -> None:
        bus.publish(
            new_envelope(
                PLACEMENTS_UPDATED,
                PlacementsUpdatedV1(
                    scoring_run_id=scoring_run_id, as_of=NEXT_FRIDAY, placements=list(placements)
                ),
                source="va/scoring",
            )
        )

    def test_the_new_stock_has_scores_at_once(self):
        bus, market, service = _setup()
        bus.publish(_completed(8, FRIDAY, [SAP_ROW]))
        self._updated(bus, 8, APPLE_PLACED)
        apple = market.scores[APPLE]
        assert (apple.scoring_run_id, apple.as_of, apple.reference) == (8, NEXT_FRIDAY, "outside")
        depot_id = _depot_with(service, HoldingLine(APPLE, Decimal(3)))
        score = _positions(service, depot_id)[APPLE].score
        assert score is not None
        assert score.composite_percentile == APPLE_PLACED.composite_percentile

    def test_the_next_weekly_run_replaces_it(self):
        bus, market, _ = _setup()
        self._updated(bus, 8, APPLE_PLACED)
        weekly = APPLE_PLACED.model_copy(update={"composite_score": 0.5})
        bus.publish(_completed(9, NEXT_FRIDAY, [SAP_ROW], [weekly]))
        assert (market.scores[APPLE].scoring_run_id, market.scores[APPLE].composite_score) == (
            9,
            0.5,
        )
