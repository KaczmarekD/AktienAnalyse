"""Hinweise am Depot (D5.1, HIN-01, 02, 04): je Regel knapp unter und knapp über der Schwelle.

Depotwert meist 10 000 EUR, damit sich Anteile leicht nachrechnen lassen. Die Kasse füllt auf.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, get_args

import pytest
from pydantic import ValidationError

from va_contracts.portfolio import HintParamsV1, HintRuleId
from va_portfolio.domain.analysis import AnalysisInput, BondData, EtfData, analyze
from va_portfolio.domain.bonds import BondTerms
from va_portfolio.domain.depots import CashLine, HoldingLine
from va_portfolio.domain.funds import Fund, FundHolding
from va_portfolio.domain.hints import (
    HINT_CATALOG,
    Hint,
    HintInput,
    TrackedHint,
    evaluate,
    track,
)
from va_portfolio.domain.valuation import Market, Quote, Score, SecurityInfo, value_depot

SAP = "DE0007164600"
SIE = "DE0007236101"
APPLE = "US0378331005"
WORLD = "IE00B4L5Y983"
EUROPE = "IE00B4K48X80"
BUND = "DE0001102580"
BUND_OLD = "DE0001102333"
TODAY = date(2026, 11, 27)  # Freitag
DEFAULT = HintParamsV1()


def _score(isin: str, **values: Any) -> Score:
    base: dict[str, Any] = {
        "scoring_run_id": 8,
        "as_of": TODAY,
        "symbol": isin,
        "reference": "universe",
        "value_score": 0.5,
        "quality_score": 0.6,
        "composite_score": 0.54,
        "composite_percentile": 0.5,
        "sector": "Technology",
    }
    return Score(isin=isin, **{**base, **values})


def _security(isin: str) -> SecurityInfo:
    kind = {WORLD: "etf", EUROPE: "etf", BUND: "bond", BUND_OLD: "bond"}.get(isin, "equity")
    currency = "USD" if isin == APPLE else "EUR"
    return SecurityInfo(isin, isin, kind, currency)


def _hints(
    values: dict[str, float],
    *,
    cash: float | None = None,
    scores: dict[str, Score] | None = None,
    etfs: dict[str, EtfData] | None = None,
    bonds: dict[str, BondData] | None = None,
    quotes: Mapping[str, Quote | None] | None = None,
    pending: set[str] = frozenset(),  # type: ignore[assignment]
    leis: dict[str, str] | None = None,
    fund_sizes: dict[str, float] | None = None,
    previous: dict[str, Score] | None = None,
    params: HintParamsV1 = DEFAULT,
) -> list[Hint]:
    """``values``: Wert je ISIN in EUR (Kurs 1 bzw. 100 % bei Anleihen); Kasse bis 10 000."""
    bond_isins = {BUND, BUND_OLD}
    lines = [
        HoldingLine(
            isin,
            Decimal(str(v * 100 if isin in bond_isins else v)),
            unit="nominal" if isin in bond_isins else "pieces",
        )
        for isin, v in values.items()
    ]
    all_quotes = {
        isin: Quote(isin, TODAY, Decimal(1), "EUR", percent_of_par=isin in bond_isins)
        for isin in values
    }
    all_quotes.update({i: q for i, q in (quotes or {}).items() if q is not None})
    for isin in [i for i, q in (quotes or {}).items() if q is None]:  # None: ohne Kurs
        del all_quotes[isin]
    market = Market(
        securities={i: _security(i) for i in values if i not in pending},
        quotes=all_quotes,
        fx={"USD": Decimal(1)},
        scores={i: _score(i) for i in values if _security(i).asset_class == "equity"}
        if scores is None
        else scores,
    )
    rest = 10_000 - sum(values.values()) if cash is None else cash
    value = value_depot("depot", lines, [CashLine(Decimal(str(rest)))], market)
    data = AnalysisInput(value=value, etfs=etfs or {}, bonds=bonds or {})
    source = HintInput(
        data,
        analyze(data),
        TODAY,
        leis=leis or {},
        fund_sizes=fund_sizes or {},
        previous_scores=previous or {},
    )
    return evaluate(source, params)


def _rule(hints: list[Hint], rule: str) -> list[Hint]:
    return [h for h in hints if h.rule == rule]


def _etf(*holdings: tuple[str, float], **values: Any) -> EtfData:
    fund = Fund(tuple(FundHolding(i, w) for i, w in holdings), complete=True)
    return EtfData(as_of=date(2026, 11, 20), holdings=fund, **values)


class TestConcentration:
    def test_k01_warning_and_critical(self):
        assert _rule(_hints({SAP: 900}), "HIN-K01") == []
        [warning] = _rule(_hints({SAP: 1100}), "HIN-K01")
        assert (warning.key, warning.severity, warning.threshold) == (
            f"HIN-K01:{SAP}",
            "warning",
            0.10,
        )
        assert warning.measured == pytest.approx(0.11)
        [critical] = _rule(_hints({SAP: 2100}), "HIN-K01")
        assert (critical.severity, critical.threshold) == ("critical", 0.20)

    def test_k01_counts_the_share_inside_etfs(self):
        etfs = {WORLD: _etf((SAP, 12.0), (APPLE, 88.0))}
        # 500 direkt + 12 % von 5000 im ETF = 1100 von 10 000
        # Apple steht im ETF mit 88 % und löst ebenfalls aus
        hints = _rule(_hints({SAP: 500, WORLD: 5000}, etfs=etfs), "HIN-K01")
        [hint] = [h for h in hints if h.subject == SAP]
        assert hint.measured == pytest.approx(0.11)

    def test_k01_not_for_bonds(self):
        assert _rule(_hints({BUND: 3000}), "HIN-K01") == []

    def test_k02_top_five(self):
        assert _rule(_hints({SAP: 400, SIE: 400}), "HIN-K02") == []
        [hint] = _rule(_hints({SAP: 2600, SIE: 2600}), "HIN-K02")
        assert (hint.key, hint.severity) == ("HIN-K02:depot", "info")

    def test_k03_sector(self):
        assert _rule(_hints({SAP: 2900}), "HIN-K03") == []
        [hint] = _rule(_hints({SAP: 3100}), "HIN-K03")
        assert (hint.subject, hint.severity) == ("Technology", "warning")

    def test_k04_country(self):
        assert _rule(_hints({SAP: 2500, SIE: 2400}), "HIN-K04") == []
        [hint] = _rule(_hints({SAP: 2600, SIE: 2500}), "HIN-K04")
        assert (hint.subject, hint.severity) == ("DE", "info")

    def test_k02_counts_stocks_not_bonds(self):
        assert _rule(_hints({BUND: 3000, BUND_OLD: 3000}), "HIN-K02") == []

    def test_k04_xs_is_no_country(self):
        xs = "XS2000000009"
        assert _rule(_hints({xs: 6000}, scores={}), "HIN-K04") == []

    def test_k05_foreign_currency(self):
        assert _rule(_hints({APPLE: 4900}), "HIN-K05") == []
        [hint] = _rule(_hints({APPLE: 5100}), "HIN-K05")
        assert hint.measured == pytest.approx(0.51)

    def test_k06_issuer_with_stock_and_bond(self):
        leis = {SAP: "LEI-SAP", BUND: "LEI-SAP"}
        assert _rule(_hints({SAP: 500, BUND: 400}, leis=leis), "HIN-K06") == []
        [hint] = _rule(_hints({SAP: 600, BUND: 500}, leis=leis), "HIN-K06")
        assert (hint.subject, hint.severity) == ("LEI-SAP", "warning")
        # Ein einzelnes Wertpapier deckt HIN-K01 ab
        assert _rule(_hints({SAP: 1500}, leis={SAP: "LEI-SAP"}), "HIN-K06") == []


class TestAllocation:
    def test_a02_cash(self):
        assert _rule(_hints({SAP: 950, SIE: 950, APPLE: 950}, cash=290), "HIN-A02") == []
        hints = _hints({SAP: 950, SIE: 950, APPLE: 950}, cash=350)
        [hint] = _rule(hints, "HIN-A02")
        assert hint.measured == pytest.approx(350 / 3200)


class TestQuality:
    def test_q01_value_trap(self):
        hints = _hints({SAP: 500}, scores={SAP: _score(SAP, value_trap_flag=True)})
        assert [h.severity for h in _rule(hints, "HIN-Q01")] == ["warning"]

    def test_q02_lower_fifth(self):
        assert (
            _rule(
                _hints({SAP: 500}, scores={SAP: _score(SAP, composite_percentile=0.21)}), "HIN-Q02"
            )
            == []
        )
        [hint] = _rule(
            _hints({SAP: 500}, scores={SAP: _score(SAP, composite_percentile=0.2)}), "HIN-Q02"
        )
        assert (hint.measured, hint.threshold) == (0.2, 0.2)

    def test_q04_low_quality(self):
        assert (
            _rule(_hints({SAP: 500}, scores={SAP: _score(SAP, quality_score=0.31)}), "HIN-Q04")
            == []
        )
        assert (
            len(_rule(_hints({SAP: 500}, scores={SAP: _score(SAP, quality_score=0.3)}), "HIN-Q04"))
            == 1
        )

    def test_q05_without_composite_or_without_score(self):
        bank = _score(
            SAP,
            quality_score=None,
            composite_score=None,
            composite_percentile=None,
            reason="no_quality",
        )
        assert len(_rule(_hints({SAP: 500}, scores={SAP: bank}), "HIN-Q05")) == 1
        assert len(_rule(_hints({SAP: 500}, scores={}), "HIN-Q05")) == 1
        assert _rule(_hints({SAP: 500}), "HIN-Q05") == []

    def test_q06_limited_comparison(self):
        for reference in ("outside", "below_size_filter"):
            hints = _hints({APPLE: 500}, scores={APPLE: _score(APPLE, reference=reference)})
            assert len(_rule(hints, "HIN-Q06")) == 1
        assert _rule(_hints({APPLE: 500}), "HIN-Q06") == []


class TestEtfs:
    def test_e01_ter(self):
        assert _rule(_hints({WORLD: 1000}, etfs={WORLD: _etf(ter=0.5)}), "HIN-E01") == []
        [hint] = _rule(_hints({WORLD: 1000}, etfs={WORLD: _etf(ter=0.51)}), "HIN-E01")
        assert (hint.measured, hint.as_of) == (0.51, date(2026, 11, 20))

    def test_e02_overlap(self):
        a = _etf((SAP, 60.0), (SIE, 40.0))
        below = _etf((SAP, 49.0), (APPLE, 51.0))
        above = _etf((SAP, 50.0), (APPLE, 50.0))
        assert (
            _rule(_hints({WORLD: 1000, EUROPE: 1000}, etfs={WORLD: a, EUROPE: below}), "HIN-E02")
            == []
        )
        [hint] = _rule(
            _hints({WORLD: 1000, EUROPE: 1000}, etfs={WORLD: a, EUROPE: above}), "HIN-E02"
        )
        assert hint.subject == f"{EUROPE}+{WORLD}"

    def test_e03_fund_size_only_from_provider_files(self):
        etfs = {WORLD: _etf()}
        assert _rule(_hints({WORLD: 1000}, etfs=etfs, fund_sizes={WORLD: 101.0}), "HIN-E03") == []
        assert (
            len(_rule(_hints({WORLD: 1000}, etfs=etfs, fund_sizes={WORLD: 99.0}), "HIN-E03")) == 1
        )
        assert _rule(_hints({WORLD: 1000}, etfs=etfs), "HIN-E03") == []


class TestBonds:
    def _bund(self, maturity: date) -> dict[str, BondData]:
        return {BUND: BondData(BondTerms(coupon=2.6, maturity=maturity))}

    def test_b01_maturity_soon(self):
        assert (
            _rule(_hints({BUND: 1000}, bonds=self._bund(TODAY + timedelta(days=91))), "HIN-B01")
            == []
        )
        [hint] = _rule(
            _hints({BUND: 1000}, bonds=self._bund(TODAY + timedelta(days=89))), "HIN-B01"
        )
        assert (hint.measured, hint.threshold) == (89.0, 90.0)

    def test_b02_low_price(self):
        def quote(close: str) -> dict[str, Quote]:
            return {BUND: Quote(BUND, TODAY, Decimal(close), "EUR", percent_of_par=True)}

        assert _rule(_hints({BUND: 1000}, quotes=quote("80.1")), "HIN-B02") == []
        [hint] = _rule(_hints({BUND: 1000}, quotes=quote("79.9")), "HIN-B02")
        assert hint.severity == "warning"

    def test_b03_one_maturity_year(self):
        def bonds(second: date) -> dict[str, BondData]:
            return {
                BUND: BondData(BondTerms(coupon=2.6, maturity=date(2033, 8, 15))),
                BUND_OLD: BondData(BondTerms(coupon=1.7, maturity=second)),
            }

        equal = _hints({BUND: 1000, BUND_OLD: 1000}, bonds=bonds(date(2032, 8, 15)))
        assert _rule(equal, "HIN-B03") == []
        [hint] = _rule(
            _hints({BUND: 1000, BUND_OLD: 1000}, bonds=bonds(date(2033, 2, 15))), "HIN-B03"
        )
        assert (hint.subject, hint.measured) == ("2033", 1.0)
        # Eine einzelne Anleihe ist immer zu 100 % in einem Jahr: kein Hinweis
        assert _rule(_hints({BUND: 1000}, bonds=self._bund(date(2033, 8, 15))), "HIN-B03") == []


class TestData:
    def test_d01_price_missing_or_old(self):
        # Kurs vom Do. 19.11.: sechs Handelstage bis Fr. 27.11.; vom Fr. 20.11.: fünf
        stale: dict[str, Quote | None] = {
            SAP: Quote(SAP, TODAY - timedelta(days=8), Decimal(1), "EUR")
        }
        fresh: dict[str, Quote | None] = {
            SAP: Quote(SAP, TODAY - timedelta(days=7), Decimal(1), "EUR")
        }
        assert _rule(_hints({SAP: 500}, quotes=fresh), "HIN-D01") == []
        [hint] = _rule(_hints({SAP: 500}, quotes=stale), "HIN-D01")
        assert (hint.measured, hint.threshold) == (6.0, 5.0)

    def test_d01_without_price(self):
        assert _rule(_hints({SAP: 500, SIE: 500}), "HIN-D01") == []  # alle Kurse da
        [hint] = _rule(_hints({SAP: 500, SIE: 500}, quotes={SAP: None}), "HIN-D01")
        assert (hint.subject, hint.severity, hint.measured) == (SAP, "warning", None)

    def test_d03_unknown_security(self):
        [hint] = _rule(_hints({SAP: 500}, pending={SAP}), "HIN-D03")
        assert hint.severity == "warning"


class TestEvaluate:
    def test_critical_first(self):
        hints = _hints({SAP: 2500}, scores={SAP: _score(SAP, value_trap_flag=True)})
        assert hints[0].severity == "critical"
        order = {"critical": 0, "warning": 1, "info": 2}
        ranks = [order[h.severity] for h in hints]
        assert ranks == sorted(ranks)

    def test_a_rule_can_be_switched_off(self):
        params = HintParamsV1(disabled=["HIN-K01"])
        assert _rule(_hints({SAP: 2500}, params=params), "HIN-K01") == []

    def test_thresholds_are_the_params(self):
        params = HintParamsV1(k01_warning=0.05, k01_critical=0.5)
        [hint] = _rule(_hints({SAP: 600}, params=params), "HIN-K01")
        assert hint.threshold == 0.05


class TestCatalog:
    def test_every_rule_of_the_spec(self):
        assert set(HINT_CATALOG) == set(get_args(HintRuleId))

    def test_never_a_recommendation(self):
        words = re.compile(r"\b(kaufen|verkaufen|kauf|verkauf|kursziel)\b", re.IGNORECASE)
        for rule in HINT_CATALOG.values():
            for text in (rule.title, rule.reason, rule.approach):
                assert not words.search(text), (rule.id, text)

    def test_every_entry_says_why_and_what_to_check(self):
        for rule in HINT_CATALOG.values():
            assert rule.reason.endswith(".")
            assert rule.approach.endswith(".")

    def test_critical_must_be_above_warning(self):
        with pytest.raises(ValidationError):
            HintParamsV1(k01_warning=0.2, k01_critical=0.1)


class TestPercentileDrop:
    """D5.2, HIN-Q03: gegen den vorherigen Bewertungslauf."""

    def test_q03_drop(self):
        now = {SAP: _score(SAP, composite_percentile=0.5)}
        small = {SAP: _score(SAP, composite_percentile=0.69, scoring_run_id=7)}
        large = {SAP: _score(SAP, composite_percentile=0.7, scoring_run_id=7)}
        assert _rule(_hints({SAP: 500}, scores=now, previous=small), "HIN-Q03") == []
        [hint] = _rule(_hints({SAP: 500}, scores=now, previous=large), "HIN-Q03")
        assert hint.measured == pytest.approx(0.2)

    def test_without_previous_run_nothing(self):
        assert _rule(_hints({SAP: 500}), "HIN-Q03") == []


class TestLifecycle:
    """D5.2, HIN-03: neu, besteht, erledigt."""

    K01 = Hint("HIN-K01", SAP, "warning", 0.12, 0.10)
    A02 = Hint("HIN-A02", "depot", "info", 0.2, 0.1)

    def test_first_run_everything_is_new(self):
        assert [t.status for t in track([], [self.K01, self.A02])] == ["new", "new"]

    def test_existing_new_and_resolved(self):
        previous = [TrackedHint(self.K01, "new"), TrackedHint(self.A02, "new")]
        worse = Hint("HIN-K01", SAP, "critical", 0.21, 0.20)
        q01 = Hint("HIN-Q01", SAP, "warning")
        tracked = track(previous, [worse, q01])
        assert [(t.hint.key, t.status) for t in tracked] == [
            (f"HIN-K01:{SAP}", "existing"),  # die Schwere ist gestiegen
            (f"HIN-Q01:{SAP}", "new"),
            ("HIN-A02:depot", "resolved"),
        ]
        assert tracked[0].hint.severity == "critical"

    def test_resolved_shows_once(self):
        previous = [TrackedHint(self.A02, "resolved")]
        assert track(previous, []) == []
        assert [t.status for t in track(previous, [self.A02])] == ["new"]
