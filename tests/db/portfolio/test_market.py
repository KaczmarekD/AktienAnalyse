"""Kopien der Marktdaten im Schema portfolio (D3.4, ADR-0013).

Mit der Rolle des Dienstes (``va_portfolio``):
- je ISIN gelten die juengsten Stammdaten (``as_of``) und der juengste Kurs (Handelstag), je
  Waehrung der juengste Kurs; bei Gleichstand die zuletzt empfangene Zeile,
- Kurse als ``numeric``, zurueck als ``Decimal`` wie geschrieben,
- nur anfuegen; ``market`` ohne ISINs liest nur die Waehrungen,
- die Bewertung des Anwendungsfalls auf PostgreSQL.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError

from va_portfolio.adapters.postgres.market import PostgresMarketStore
from va_portfolio.adapters.postgres.store import PostgresDepotStore
from va_portfolio.application.depots import DepotService
from va_portfolio.application.market import FxRate, SecurityCopy
from va_portfolio.domain.depots import HoldingLine
from va_portfolio.domain.valuation import Quote, Score, SecurityInfo

T0 = datetime(2026, 11, 20, 22, 45, tzinfo=UTC)
SAP = "DE0007164600"
APPLE = "US0378331005"
FRIDAY, THURSDAY = date(2026, 11, 20), date(2026, 11, 19)


@pytest.fixture
def market(portfolio_engine: Engine) -> PostgresMarketStore:
    return PostgresMarketStore(portfolio_engine)


def _copy(isin: str, name: str) -> SecurityCopy:
    return SecurityCopy(SecurityInfo(isin, name, "equity", "EUR"), {"isin": isin, "name": name})


def _quote(isin: str, day: date, close: str, currency: str = "EUR") -> Quote:
    return Quote(isin, day, Decimal(close), currency, source="yahoo", symbol="SAP.DE")


def test_newest_master_data_per_isin(market):
    market.record_securities([_copy(SAP, "SAP SE")], as_of=FRIDAY, at=T0)
    market.record_securities([_copy(SAP, "SAP alt")], as_of=THURSDAY, at=T0)  # spaet zugestellt
    market.record_securities([_copy(APPLE, "Apple")], as_of=THURSDAY, at=T0)
    copy = market.market([SAP, APPLE])
    assert (copy.securities[SAP].name, copy.securities[APPLE].name) == ("SAP SE", "Apple")


def test_newest_price_and_rate(market):
    market.record_prices([_quote(SAP, FRIDAY, "231.5")], [], at=T0)
    market.record_prices([_quote(SAP, THURSDAY, "220.1")], [], at=T0)
    market.record_prices([_quote(SAP, FRIDAY, "231.75")], [], at=T0)  # korrigiert, gleicher Tag
    rates = [FxRate("USD", THURSDAY, Decimal("0.9")), FxRate("USD", FRIDAY, Decimal("0.92"))]
    market.record_prices([], rates, at=T0)
    copy = market.market([SAP])
    assert copy.quotes[SAP] == _quote(SAP, FRIDAY, "231.75")
    assert copy.fx == {"USD": Decimal("0.92")}


def test_only_the_asked_isins(market):
    market.record_prices([_quote(SAP, FRIDAY, "1"), _quote(APPLE, FRIDAY, "2", "USD")], [], at=T0)
    assert set(market.market([APPLE]).quotes) == {APPLE}
    assert market.market([]).quotes == {}


def test_the_whole_security_is_stored(market, engine):
    market.record_securities([_copy(SAP, "SAP SE")], as_of=FRIDAY, at=T0)
    with engine.connect() as conn:
        payload = conn.execute(text("SELECT payload FROM portfolio.security_view")).scalar_one()
    assert payload == {"isin": SAP, "name": "SAP SE"}


def test_the_service_role_never_changes_or_deletes(market, portfolio_engine):
    market.record_prices([_quote(SAP, FRIDAY, "1")], [FxRate("USD", FRIDAY, Decimal(1))], at=T0)
    for statement in (
        "UPDATE portfolio.price_view SET close = 0",
        "DELETE FROM portfolio.fx_view",
        "TRUNCATE portfolio.security_view",
    ):
        with pytest.raises(DBAPIError), portfolio_engine.begin() as conn:
            conn.execute(text(statement))


def test_the_depot_is_valued_on_postgres(market, portfolio_engine):
    market.record_securities([_copy(SAP, "SAP SE")], as_of=FRIDAY, at=T0)
    market.record_prices([_quote(SAP, FRIDAY, "231.5")], [], at=T0)
    service = DepotService(PostgresDepotStore(portfolio_engine), clock=lambda: T0, market=market)
    depot = service.create(1, "depot", "DKB", None).depot
    service.save(1, depot.id, 0, [HoldingLine(SAP, Decimal("10"))], [])
    [summary] = service.list(1)
    assert summary.valuation is not None
    assert summary.valuation.value_eur == Decimal("2315.00")
    assert summary.valuation.pending == 0


def _score(isin: str, scoring_run_id: int, **values: object) -> Score:
    return Score(
        isin=isin,
        scoring_run_id=scoring_run_id,
        as_of=FRIDAY,
        symbol="SAP.DE",
        **{"reference": "universe", **values},  # type: ignore[arg-type]
    )


def test_newest_score_per_isin(market):
    """D4.2: je ISIN der juengste Bewertungslauf, auch wenn er spaet zugestellt wird."""
    market.record_scores([_score(SAP, 9, rank=3, composite_score=0.9)], at=T0)
    market.record_scores([_score(SAP, 8, rank=12), _score(APPLE, 8, reference="outside")], at=T0)
    scores = market.market([SAP, APPLE]).scores
    assert scores[SAP] == _score(SAP, 9, rank=3, composite_score=0.9)
    assert (scores[APPLE].scoring_run_id, scores[APPLE].reference) == (8, "outside")
    assert market.market([]).scores == {}


def test_the_ranking_of_a_scoring_run(market):
    """D5.5: die Titel des Rankings eines Laufs, mit Namen; Einordnungen und andere Laeufe nicht."""
    market.record_scores(
        [
            _score(SAP, 8, rank=12, name="SAP SE", sector="Technology"),
            _score(APPLE, 8, reference="outside"),
        ],
        at=T0,
    )
    market.record_scores([_score(SAP, 9, rank=3)], at=T0)
    [sap] = market.universe(8)
    assert (sap.isin, sap.rank, sap.name, sap.sector) == (SAP, 12, "SAP SE", "Technology")
    assert [s.rank for s in market.universe(9)] == [3]
    assert market.universe(7) == []


def test_the_score_role_never_changes_or_deletes(market, portfolio_engine):
    market.record_scores([_score(SAP, 8)], at=T0)
    for statement in (
        "UPDATE portfolio.score_view SET scoring_run_id = 1",
        "DELETE FROM portfolio.score_view",
    ):
        with pytest.raises(DBAPIError), portfolio_engine.begin() as conn:
            conn.execute(text(statement))


def test_unknown_payload_fields_are_ignored(market, engine):
    """Ein Feld, das ``Score`` spaeter nicht mehr kennt, bricht das Lesen nicht."""
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO portfolio.score_view (isin, scoring_run_id, as_of, payload, received_at) "
                "VALUES (:isin, 8, :day, CAST(:payload AS jsonb), :at)"
            ),
            {
                "isin": SAP,
                "day": FRIDAY,
                "payload": '{"symbol": "SAP.DE", "reference": "universe", "gone": 1}',
                "at": T0,
            },
        )
    assert market.market([SAP]).scores[SAP] == _score(SAP, 8)


def test_the_newest_whole_security_per_isin(market):
    """D4.4: die ganzen Stammdaten fuer die Analyse, je ISIN die juengsten."""
    market.record_securities([_copy(SAP, "SAP alt")], as_of=THURSDAY, at=T0)
    market.record_securities([_copy(SAP, "SAP SE")], as_of=FRIDAY, at=T0)
    market.record_securities([_copy(APPLE, "Apple")], as_of=FRIDAY, at=T0)
    assert market.security_payloads([SAP]) == {SAP: {"isin": SAP, "name": "SAP SE"}}
    assert market.security_payloads([]) == {}


def test_the_previous_scoring_run_per_isin(market):
    """D5.2, HIN-Q03: je ISIN der zweitjuengste Bewertungslauf, darin die juengste Zeile."""
    market.record_scores([_score(SAP, 7, rank=20), _score(APPLE, 7)], at=T0)
    market.record_scores([_score(SAP, 7, rank=21)], at=T0)  # sofort eingeordnet, gleicher Lauf
    market.record_scores([_score(SAP, 8, rank=5)], at=T0)
    previous = market.previous_scores([SAP, APPLE])
    assert set(previous) == {SAP}  # Apple kennt nur einen Lauf
    assert (previous[SAP].scoring_run_id, previous[SAP].rank) == (7, 21)
    assert market.previous_scores([]) == {}
