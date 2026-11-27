"""Pruefkandidaten (D5.5, HIN-06).

- Bis zu drei Titel aus dem Ranking desselben Bewertungslaufs, aus demselben Sektor, mit hoeherem
  Composite, ohne Value-Trap-Flag und nicht schon im Depot; bester Composite zuerst.
- Standardmaessig aus; erst die Schwellen schalten sie ein. Ein Wertpapier, das nicht im Depot
  steht, ist unbekannt wie ein fremdes Depot.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from va_contracts.portfolio import HintParamsV1
from va_contracts.rpc.v1 import (
    DEPOTS_COMPARISON,
    DEPOTS_HINTS,
    ComparisonRequestV1,
    DepotComparisonReplyV1,
    DepotHintsReplyV1,
    DepotRefRequestV1,
)
from va_portfolio.adapters.memory import MemoryDepotStore, MemoryMarketStore
from va_portfolio.application.depots import DepotNotFound, DepotService
from va_portfolio.domain.candidates import candidates
from va_portfolio.domain.depots import CashLine, HoldingLine
from va_portfolio.domain.valuation import Quote, Score
from va_portfolio.entrypoints.rpc import handlers

ANNA, BEN = 1, 2
DAY = date(2026, 11, 20)
T0 = datetime(2026, 11, 27, 20, tzinfo=UTC)
RUN = 8
# Eine schwache Versicherung und ihre Branche im Ranking
WEAK = "DE0008402215"  # Hannover Rueck als Platzhalter


def _score(isin: str, composite: float | None, **values: object) -> Score:
    fields: dict[str, object] = {
        "isin": isin,
        "scoring_run_id": RUN,
        "as_of": DAY,
        "symbol": f"{isin[-4:]}.DE",
        "reference": "universe",
        "composite_score": composite,
        "composite_percentile": composite,
        "sector": "Financial Services",
        "name": f"Titel {isin[-4:]}",
        **values,
    }
    return Score(**fields)  # type: ignore[arg-type]


ALV = "DE0008404005"
MUV = "DE0008430026"
TLX = "DE000TLX1005"
CBK = "DE000CBK1001"
DBK = "DE0005140008"
SAP = "DE0007164600"

UNIVERSE = [
    _score(WEAK, 0.15, rank=80),
    _score(ALV, 0.72, rank=5),
    _score(MUV, 0.64, rank=9),
    _score(TLX, 0.40, rank=30),
    _score(CBK, 0.90, rank=1, value_trap_flag=True),  # Value-Trap: kein Vergleich
    _score(DBK, 0.55, rank=14),
    _score(SAP, 0.95, rank=2, sector="Technology"),  # anderer Sektor
]


class TestCandidates:
    def test_same_sector_higher_composite_without_value_trap(self):
        stock = UNIVERSE[0]
        found = candidates(stock, UNIVERSE, held={WEAK})
        assert [s.isin for s in found] == [ALV, MUV, DBK]

    def test_not_what_the_depot_already_holds(self):
        found = candidates(UNIVERSE[0], UNIVERSE, held={WEAK, ALV})
        assert [s.isin for s in found] == [MUV, DBK, TLX]

    def test_only_the_same_scoring_run_and_the_ranking(self):
        other_run = _score(ALV, 0.99, scoring_run_id=RUN - 1)
        placed = _score(MUV, 0.99, reference="outside")
        found = candidates(UNIVERSE[0], [other_run, placed], held={WEAK})
        assert found == []

    def test_without_sector_or_composite_no_comparison(self):
        assert candidates(_score(WEAK, 0.15, sector=None), UNIVERSE, held=set()) == []
        assert candidates(_score(WEAK, None), UNIVERSE, held=set()) == []

    def test_ties_by_symbol(self):
        a = _score("DE000AAAA001", 0.5, symbol="BBB.DE")
        b = _score("DE000AAAA002", 0.5, symbol="AAA.DE")
        assert [s.symbol for s in candidates(UNIVERSE[0], [a, b], held=set())] == [
            "AAA.DE",
            "BBB.DE",
        ]


def _setup(*, enabled: bool):
    market = MemoryMarketStore()
    market.record_prices([Quote(WEAK, DAY, Decimal(200), "EUR")], [], at=T0)
    market.record_scores(UNIVERSE, at=T0)
    store = MemoryDepotStore()
    service = DepotService(store, market=market, clock=lambda: T0)
    depot = service.create(ANNA, "depot", "DKB", None).depot
    lines = [HoldingLine(WEAK, Decimal(5)), HoldingLine(ALV, Decimal(1))]
    service.save(ANNA, depot.id, 0, lines, [CashLine(Decimal(100))])
    if enabled:
        service.save_hint_params(ANNA, depot.id, 0, HintParamsV1(candidates=True))
    return service, depot.id


class TestService:
    def test_off_by_default(self):
        service, depot_id = _setup(enabled=False)
        comparison = service.comparison(ANNA, depot_id, WEAK)
        assert comparison is not None
        assert (comparison.enabled, comparison.candidates) == (False, [])

    def test_on_with_the_ranking_of_the_same_run(self):
        service, depot_id = _setup(enabled=True)
        comparison = service.comparison(ANNA, depot_id, WEAK)
        assert comparison is not None
        assert comparison.enabled is True
        assert (comparison.sector, comparison.scoring_run_id) == ("Financial Services", RUN)
        # Allianz steht schon im Depot
        assert [s.isin for s in comparison.candidates] == [MUV, DBK, TLX]

    def test_a_security_outside_the_depot_is_not_found(self):
        service, depot_id = _setup(enabled=True)
        with pytest.raises(DepotNotFound):
            service.comparison(ANNA, depot_id, MUV)

    def test_a_foreign_depot_is_not_found(self):
        service, depot_id = _setup(enabled=True)
        with pytest.raises(DepotNotFound):
            service.comparison(BEN, depot_id, WEAK)

    def test_without_market_data_none(self):
        store = MemoryDepotStore()
        service = DepotService(store, market=None, clock=lambda: T0)
        depot = service.create(ANNA, "depot", "DKB", None).depot
        service.save(ANNA, depot.id, 0, [HoldingLine(WEAK, Decimal(5))], [])
        service.save_hint_params(ANNA, depot.id, 0, HintParamsV1(candidates=True))
        assert service.comparison(ANNA, depot.id, WEAK) is None


class TestOverRpc:
    def test_the_comparison_and_the_switch_in_the_hints(self):
        service, depot_id = _setup(enabled=True)
        rpc = handlers(service)
        request = ComparisonRequestV1(user_id=ANNA, depot_id=depot_id, isin=WEAK)
        reply = rpc[DEPOTS_COMPARISON](request)
        assert isinstance(reply, DepotComparisonReplyV1)
        assert reply.comparison is not None
        [first, *_] = reply.comparison.candidates
        assert (first.isin, first.name, first.rank, first.composite_score) == (
            MUV,
            "Titel 0026",
            9,
            0.64,
        )
        hints = rpc[DEPOTS_HINTS](DepotRefRequestV1(user_id=ANNA, depot_id=depot_id))
        assert isinstance(hints, DepotHintsReplyV1)
        assert hints.hints is not None
        assert hints.hints.candidates is True

    def test_a_security_outside_the_depot_is_not_found(self):
        service, depot_id = _setup(enabled=True)
        reply = handlers(service)[DEPOTS_COMPARISON](
            ComparisonRequestV1(user_id=ANNA, depot_id=depot_id, isin=MUV)
        )
        assert reply.error is not None
        assert reply.error.code == "not_found"
