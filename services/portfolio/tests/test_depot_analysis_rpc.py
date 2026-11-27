"""Analyse ueber Request/Reply (D4.4): ``portfolio.depots.analysis``.

- Die Stammdaten (ganzes ``SecurityV1``) liefern ETF- und Anleihedaten, die Scores der Positionen
  der ETFs kommen aus ``score_view``.
- Ein fremdes Depot ist ``not_found``; ohne Marktdaten gibt es keine Analyse.
- Contract und Dataclasses der Domain haben dieselben Felder.
"""

from __future__ import annotations

import dataclasses
import types
import typing
from datetime import UTC, date, datetime
from decimal import Decimal

import pydantic

from va_contracts.portfolio import DepotAnalysisV1
from va_contracts.rpc.v1 import DEPOTS_ANALYSIS, DepotAnalysisReplyV1, DepotRefRequestV1
from va_contracts.securities import BondTermsV1, EtfHoldingV1, EtfV1, SecurityV1
from va_portfolio.adapters.memory import MemoryDepotStore, MemoryMarketStore
from va_portfolio.application.depots import DepotService
from va_portfolio.application.market import SecurityCopy
from va_portfolio.domain import analysis as domain
from va_portfolio.domain.depots import CashLine, HoldingLine
from va_portfolio.domain.valuation import Quote, Score, SecurityInfo
from va_portfolio.entrypoints.rpc import handlers

ANNA, BEN = 1, 2
SAP = "DE0007164600"
APPLE = "US0378331005"
WORLD = "IE00B4L5Y983"
BUND = "DE0001102580"
FRIDAY = date(2026, 11, 20)
T0 = datetime(2026, 11, 20, 23, tzinfo=UTC)


def _copy(security: SecurityV1) -> SecurityCopy:
    info = SecurityInfo(security.isin, security.name, security.asset_class, security.currency)
    return SecurityCopy(info, security.model_dump(mode="json"))


def _market() -> MemoryMarketStore:
    market = MemoryMarketStore()
    world = SecurityV1(
        isin=WORLD,
        name="iShares Core MSCI World",
        asset_class="etf",
        currency="USD",
        etf=EtfV1(
            source="ishares",
            as_of=date(2026, 11, 19),
            complete=True,
            ter=0.2,
            fund_currency="USD",
            holdings_count=2,
            top_holdings=[
                EtfHoldingV1(name="APPLE", weight=60.0, isin=APPLE),
                EtfHoldingV1(name="SAP", weight=40.0, isin=SAP),
            ],
            sectors={"IT": 100.0},
            countries={"Vereinigte Staaten": 60.0, "Deutschland": 40.0},
        ),
    )
    bund = SecurityV1(
        isin=BUND,
        name="Bund 2033",
        asset_class="bond",
        currency="EUR",
        cfi="DBFTFB",
        bond=BondTermsV1(coupon=2.6, maturity=date(2033, 8, 15)),
    )
    sap = SecurityV1(isin=SAP, name="SAP SE", asset_class="equity", currency="EUR")
    market.record_securities([_copy(world), _copy(bund), _copy(sap)], as_of=FRIDAY, at=T0)
    market.record_prices(
        [
            Quote(SAP, FRIDAY, Decimal(200), "EUR"),
            Quote(WORLD, FRIDAY, Decimal(100), "EUR"),
            Quote(BUND, FRIDAY, Decimal("97.5"), "EUR", percent_of_par=True),
        ],
        [],
        at=T0,
    )
    market.record_scores(
        [
            Score(SAP, 8, FRIDAY, "SAP.DE", "universe", composite_score=0.6),
            # Apple steht nicht im Depot, aber im ETF: zaehlt fuer dessen Look-through-Score
            Score(APPLE, 8, FRIDAY, "AAPL", "outside", composite_score=0.4),
        ],
        at=T0,
    )
    return market


def _service(market: MemoryMarketStore | None) -> tuple[DepotService, int]:
    service = DepotService(MemoryDepotStore(), market=market)
    depot = service.create(ANNA, "depot", "DKB", None).depot
    lines = [
        HoldingLine(SAP, Decimal(10)),
        HoldingLine(WORLD, Decimal(20)),
        HoldingLine(BUND, Decimal(1000), unit="nominal"),
    ]
    service.save(ANNA, depot.id, 0, lines, [CashLine(Decimal(25))])
    return service, depot.id


def _ask(service: DepotService, user_id: int, depot_id: int) -> DepotAnalysisReplyV1:
    reply = handlers(service)[DEPOTS_ANALYSIS](
        DepotRefRequestV1(user_id=user_id, depot_id=depot_id)
    )
    assert isinstance(reply, DepotAnalysisReplyV1)
    return reply


class TestOverRpc:
    def test_the_analysis_of_the_own_depot(self):
        service, depot_id = _service(_market())
        analysis = _ask(service, ANNA, depot_id).analysis
        assert analysis is not None
        assert analysis.value_eur == Decimal("5000.00")  # 2000 + 2000 + 975 + 25
        assert analysis.costs.running_costs_eur == Decimal("4.00")
        assert analysis.bonds.ytm is not None
        [fund] = analysis.quality.funds
        assert fund.score == 0.6 * 0.4 + 0.4 * 0.6  # Apple 60 % x 0,4, SAP 40 % x 0,6
        sap = next(t for t in analysis.concentration.top if t.isin == SAP)
        assert sap.weight == 2000 / 5000 + 2000 / 5000 * 0.4  # direkt und im ETF

    def test_a_foreign_depot_is_not_found(self):
        service, depot_id = _service(_market())
        reply = _ask(service, BEN, depot_id)
        assert reply.analysis is None
        assert reply.error is not None
        assert reply.error.code == "not_found"

    def test_without_market_data_no_analysis(self):
        service, depot_id = _service(None)
        reply = _ask(service, ANNA, depot_id)
        assert (reply.analysis, reply.error) == (None, None)

    def test_a_holding_without_isin_form_counts_without_isin(self):
        """Die Quelle nennt Futures oder Kasse mit eigener Kennung: kein Fehler, keine ISIN."""
        market = _market()
        holdings = market.payloads[WORLD]["etf"]["top_holdings"]
        holdings.append({"name": "S&P500 EMINI DEC 26", "weight": 0.5, "isin": "ESZ6 Index"})
        service, depot_id = _service(market)
        analysis = _ask(service, ANNA, depot_id).analysis
        assert analysis is not None
        assert all(t.isin != "ESZ6 Index" for t in analysis.concentration.top)

    def test_unreadable_master_data_only_miss_in_the_analysis(self):
        market = _market()
        market.payloads[WORLD] = {"isin": WORLD, "kaputt": True}
        service, depot_id = _service(market)
        analysis = _ask(service, ANNA, depot_id).analysis
        assert analysis is not None
        assert analysis.quality.funds == []
        assert analysis.costs.ter is None


def _model_fields(model: type[pydantic.BaseModel]) -> dict[str, typing.Any]:
    return {name: field.annotation for name, field in model.model_fields.items()}


def _nested(annotation: typing.Any) -> list[type]:
    """Die Klassen in einer Annotation (``X | None``, ``list[X]``)."""
    args = typing.get_args(annotation)
    if isinstance(annotation, types.UnionType) or args:
        return [c for arg in args for c in _nested(arg)]
    return [annotation] if isinstance(annotation, type) else []


def test_contract_and_domain_have_the_same_fields():
    """``DepotAnalysisV1.model_validate(asdict(...))`` uebersaehe ein Feld, das nur einer kennt."""
    pairs: list[tuple[type, type[pydantic.BaseModel]]] = [(domain.DepotAnalysis, DepotAnalysisV1)]
    seen = set()
    while pairs:
        dataclass, contract = pairs.pop()
        if dataclass in seen:
            continue
        seen.add(dataclass)
        names = [f.name for f in dataclasses.fields(dataclass)]
        assert names == list(contract.model_fields), dataclass.__name__
        hints = typing.get_type_hints(dataclass, dict(vars(domain)))
        for name, annotation in _model_fields(contract).items():
            models = [c for c in _nested(annotation) if issubclass(c, pydantic.BaseModel)]
            classes = [c for c in _nested(hints[name]) if dataclasses.is_dataclass(c)]
            pairs.extend(zip(classes, models, strict=True))
    assert len(seen) == 13  # DepotAnalysis und alle Teile
