"""Tests fuer die Scoring-Engine."""

from __future__ import annotations

import math
from typing import Any, ClassVar

import numpy as np
import pandas as pd
import pytest

from va_scoring.domain.scoring import (
    DEFAULT_QUALITY_FACTORS,
    DEFAULT_VALUE_FACTORS,
    INDUSTRY_RULE_EXCLUDED,
    NON_MULTIPLE_FACTORS,
    QUALITY_FACTOR_CATALOG,
    VALUE_FACTOR_CATALOG,
    ScoringConfig,
    _composite_mean,
    _percentile_rank,
    industry_rule_applies,
    score,
)


class TestPercentileRank:
    def test_low_direction_inverts(self):
        s = pd.Series([10.0, 5.0, 1.0])
        r = _percentile_rank(s, direction="low", drop_non_positive=True)
        # Niedrigster Wert (1) sollte den hoechsten Rank haben
        assert r.iloc[2] > r.iloc[0]

    def test_high_direction_keeps(self):
        s = pd.Series([10.0, 5.0, 1.0])
        r = _percentile_rank(s, direction="high", drop_non_positive=False)
        assert r.iloc[0] > r.iloc[2]

    def test_nan_stays_nan(self):
        s = pd.Series([1.0, np.nan, 3.0])
        r = _percentile_rank(s, direction="high", drop_non_positive=False)
        assert pd.isna(r.iloc[1])

    def test_drop_non_positive_for_value_metrics(self):
        # Negative Werte (Verluste) sollen aus dem Ranking ausgeschlossen werden
        s = pd.Series([10.0, -5.0, 2.0])
        r = _percentile_rank(s, direction="low", drop_non_positive=True)
        assert pd.isna(r.iloc[1])
        assert not pd.isna(r.iloc[0])
        assert not pd.isna(r.iloc[2])

    def test_drop_non_positive_false_keeps_negatives(self):
        s = pd.Series([10.0, -5.0, 2.0])
        r = _percentile_rank(s, direction="high", drop_non_positive=False)
        assert not pd.isna(r.iloc[1])

    def test_inf_is_not_ranked(self):
        # inf ist kein Messwert (z. B. Ueberlauf) - weder Bestwert noch Schlusslicht
        s = pd.Series([1.0, np.inf, 3.0, -np.inf])
        r = _percentile_rank(s, direction="high", drop_non_positive=False)
        assert pd.isna(r.iloc[1])
        assert pd.isna(r.iloc[3])
        assert r.iloc[0] == 0.5
        assert r.iloc[2] == 1.0


class TestCompositeMean:
    def test_min_share_filters_sparse_rows(self):
        df = pd.DataFrame(
            {
                "f1": [1.0, np.nan, 1.0],
                "f2": [1.0, np.nan, 1.0],
                "f3": [1.0, 1.0, np.nan],
                "f4": [1.0, 1.0, np.nan],
            },
        )
        # Zeile 1 hat nur 2/4 = 50 %, mit min_share 0.6 -> NaN
        score_s = _composite_mean(df, min_share=0.6, min_count=2)
        assert pd.isna(score_s.iloc[1])
        assert not pd.isna(score_s.iloc[0])

    def test_min_count_applies_beside_the_share(self):
        df = pd.DataFrame({"f1": [1.0, 1.0], "f2": [1.0, 1.0], "f3": [1.0, np.nan]})
        # 2 von 3 erfuellen den Anteil 0.5, aber nicht die Mindestzahl 3
        score_s = _composite_mean(df, min_share=0.5, min_count=3)
        assert not pd.isna(score_s.iloc[0])
        assert pd.isna(score_s.iloc[1])

    def test_empty_df(self):
        result = _composite_mean(pd.DataFrame(), min_share=0.5, min_count=2)
        assert result.empty


def _frame(rows: dict[str, dict[str, Any]]) -> pd.DataFrame:
    """Kleines Universum: Symbol -> Kennzahlen, alle ueber der Mindest-Marktkapitalisierung."""
    return pd.DataFrame(
        [{"symbol": s, "market_cap": 1e9, **metrics} for s, metrics in rows.items()]
    )


# Vier Titel mit allen Faktoren, ein fuenfter mit 2 von 5 Quality-Faktoren
_FULL_QUALITY = {
    "roic": 0.10,
    "fcf_margin": 0.10,
    "operating_margin": 0.10,
    "net_debt_ebitda": 2.0,
    "earnings_stability": 0.5,
}
_UNIVERSE = {
    f"T{i}.DE": {
        "ev_ebit": 10.0 + i,
        "pb_ratio": 2.0 + i,
        "p_fcf": 15.0 + i,
        "shareholder_yield": 0.03 - 0.005 * i,
        **{k: v * (1 + 0.2 * i) for k, v in _FULL_QUALITY.items()},
    }
    for i in range(4)
} | {
    # Billigster Titel, aber kaum Quality-Daten (wie die Deutsche Bank: 2 von 5)
    "BANK.DE": {
        "ev_ebit": 5.0,
        "pb_ratio": 0.5,
        "p_fcf": 4.0,
        "shareholder_yield": 0.08,
        "fcf_margin": -0.5,
        "earnings_stability": 0.1,
    }
}


class TestMissingSubscore:
    """M1 (Entscheidung 30.10.2026): Ein Composite entsteht nur aus beiden Teilscores.

    Bis dahin war er bei fehlendem Quality-Score der Value-Score allein (Sicherungstest aus
    P1.10). Ein Titel ohne Quality-Daten stand so besser da als einer mit mittelmaessiger
    Quality, und das Value-Trap-Flag konnte nie greifen.
    """

    def test_no_composite_without_quality_score(self):
        out = score(_frame(_UNIVERSE), ScoringConfig())
        bank = out.set_index("symbol").loc["BANK.DE"].to_dict()
        assert pd.isna(bank["quality_score"])
        assert float(bank["value_score"]) >= 0.70  # billig, aber ohne Urteil zur Quality
        assert pd.isna(bank["composite_score"])
        assert bool(bank["value_trap_flag"]) is False
        assert out["symbol"].iloc[-1] == "BANK.DE"  # hinter allen bewerteten Titeln

    def test_no_composite_without_value_score(self):
        # Nur negative Multiples: kein Value-Faktor zaehlt, Quality ist vollstaendig
        universe = _UNIVERSE | {"QONLY.DE": {"ev_ebit": -5.0, "pb_ratio": -1.0, **_FULL_QUALITY}}
        row = score(_frame(universe), ScoringConfig()).set_index("symbol").loc["QONLY.DE"]
        values = row.to_dict()
        assert pd.isna(values["value_score"])
        assert pd.notna(values["quality_score"])
        assert pd.isna(values["composite_score"])

    def test_both_subscores_keep_the_weighting(self):
        out = score(_frame(_UNIVERSE), ScoringConfig()).set_index("symbol")
        t0 = out.loc["T0.DE"].to_dict()
        expected = 0.6 * float(t0["value_score"]) + 0.4 * float(t0["quality_score"])
        assert float(t0["composite_score"]) == pytest.approx(expected)


class TestDeterministicOrder:
    """Gefunden mit der Replay-Regression (P2b.0): Titel ohne Composite standen in der
    Reihenfolge, in der sie hereinkamen. Der Abruf liefert sie in der Reihenfolge des
    Universums, ein wiederverwendeter Abruf vom selben Tag alphabetisch aus der Datenbank.
    Derselbe Tag ergab so verschiedene Raenge (Deutsche Bank und Commerzbank, 89/90)."""

    # Zwei Titel ohne Composite und zwei mit gleichem Composite
    UNIVERSE = _UNIVERSE | {
        "ABANK.DE": _UNIVERSE["BANK.DE"],
        "ZZ.DE": _UNIVERSE["T1.DE"],
        "AA.DE": _UNIVERSE["T1.DE"],
    }

    def test_rank_does_not_depend_on_input_order(self):
        forward = score(_frame(self.UNIVERSE), ScoringConfig())
        backward = score(_frame(dict(reversed(self.UNIVERSE.items()))), ScoringConfig())
        assert dict(zip(forward["symbol"], forward["rank_overall"], strict=True)) == dict(
            zip(backward["symbol"], backward["rank_overall"], strict=True)
        )

    def test_titles_without_composite_are_ordered_by_symbol(self):
        out = score(_frame(self.UNIVERSE), ScoringConfig())  # BANK.DE kommt vor ABANK.DE
        assert list(out["symbol"].iloc[-2:]) == ["ABANK.DE", "BANK.DE"]

    def test_equal_composite_is_ordered_by_symbol(self):
        out = score(_frame(self.UNIVERSE), ScoringConfig())  # ZZ.DE kommt vor AA.DE
        ranks = out.set_index("symbol")["rank_overall"]
        composite = out.set_index("symbol")["composite_score"]
        assert composite["AA.DE"] == composite["ZZ.DE"]
        assert ranks["AA.DE"] < ranks["ZZ.DE"]


class TestMinFactorCount:
    def test_default_is_two(self):
        assert ScoringConfig().min_factor_count == 2

    def test_is_used_for_both_groups(self):
        """P1.10: Die Untergrenze steht in ScoringConfig statt im Code."""
        strict = score(_frame(_UNIVERSE), ScoringConfig(min_factor_count=5)).set_index("symbol")
        # Vier Value-Faktoren reichen nicht mehr fuer 5, also fehlt jeder Value-Score
        assert strict["value_score"].isna().all()
        assert strict.loc["T0.DE", "quality_score"] == pytest.approx(
            score(_frame(_UNIVERSE), ScoringConfig())
            .set_index("symbol")
            .loc["T0.DE", "quality_score"]
        )


class TestScoreEndToEnd:
    def test_market_cap_filter(self, mock_universe_df):
        out = score(mock_universe_df, ScoringConfig(min_market_cap=300_000_000))
        symbols = set(out["symbol"])
        assert "SMALL.DE" not in symbols  # market_cap 100 Mio
        assert "VAL.DE" in symbols

    def test_value_co_ranks_top(self, mock_universe_df):
        out = score(mock_universe_df, ScoringConfig())
        # Value Co kombiniert guenstige Bewertung mit hoher Qualitaet
        assert out.iloc[0]["symbol"] == "VAL.DE"

    def test_value_trap_flag(self, mock_universe_df):
        out = score(mock_universe_df, ScoringConfig())
        trap_row = out[out["symbol"] == "TRAP.DE"].iloc[0]
        assert bool(trap_row["value_trap_flag"]) is True

    def test_loss_maker_no_score(self, mock_universe_df):
        out = score(mock_universe_df, ScoringConfig())
        loss_row = out[out["symbol"] == "LOSS.DE"].iloc[0]
        # Loss-Maker hat negative Value-Metriken -> Value-Score sehr niedrig
        # und sollte definitiv NICHT auf Platz 1 stehen
        assert loss_row["rank_overall"] > out["rank_overall"].median()

    def test_rank_overall_continuous(self, mock_universe_df):
        out = score(mock_universe_df, ScoringConfig())
        assert list(out["rank_overall"]) == list(range(1, len(out) + 1))

    def test_weights_normalised(self, mock_universe_df):
        out = score(mock_universe_df, ScoringConfig(value_weight=0.6, quality_weight=0.4))
        composites = out["composite_score"].dropna()
        # Alle Composites sollten im Bereich [0,1] liegen
        assert (composites >= 0).all() and (composites <= 1).all()

    def test_custom_factor_config(self, mock_universe_df):
        # Custom Faktoren-Set (Minimum 2 wegen min_factor_share)
        cfg = ScoringConfig(
            value_factors={
                "ev_ebit": ("ev_ebit", "low"),
                "pb": ("pb_ratio", "low"),
            }
        )
        out = score(mock_universe_df, cfg)
        assert out["value_score"].notna().sum() > 0


class TestDefaultFactors:
    def test_default_value_factors_complete(self):
        assert "ev_ebit" in DEFAULT_VALUE_FACTORS
        assert "shareholder_yield" in DEFAULT_VALUE_FACTORS
        # Direction muss "low" oder "high" sein
        for col, direction in DEFAULT_VALUE_FACTORS.values():
            assert direction in ("low", "high")
            assert isinstance(col, str)

    def test_default_quality_factors_complete(self):
        assert "roic" in DEFAULT_QUALITY_FACTORS
        for col, direction in DEFAULT_QUALITY_FACTORS.values():
            assert direction in ("low", "high")


class TestIndustryRules:
    """F2.4 (ADR-0011, Punkt 3, angenommen am 06.11.2026): Bei Banken, Versicherern, „Capital
    Markets“ und Immobilien zählen EV-, FCF- und Margen-Kennzahlen nicht. Die Titel fallen unter
    den Mindestanteil und bekommen keinen Composite. Alle Ränge bleiben global."""

    PREFIXES = ScoringConfig().industry_prefixes
    INSURER: ClassVar[dict[str, Any]] = {
        "industry": "Insurance - Diversified",
        "ev_ebit": 4.0,
        "pb_ratio": 2.6,
        "p_fcf": 5.0,
        "shareholder_yield": 0.06,
        **_FULL_QUALITY,
    }

    def _universe(self) -> pd.DataFrame:
        frame = _frame(_UNIVERSE | {"INS.DE": self.INSURER})
        frame["industry"] = frame["industry"].fillna("Specialty Chemicals")
        return frame

    @pytest.mark.parametrize(
        ("industry", "applies"),
        [
            ("Banks - Regional", True),
            ("Insurance - Reinsurance", True),
            ("Capital Markets", True),
            ("Real Estate Services", True),
            ("Real Estate - Diversified", True),
            ("REIT - Residential", True),
            ("Financial Data & Stock Exchanges", False),
            ("Asset Management", False),
            ("Specialty Chemicals", False),
            (None, False),
            ("", False),
        ],
    )
    def test_industry_prefixes(self, industry: str | None, applies: bool):
        assert industry_rule_applies(industry, self.PREFIXES) is applies

    def test_excluded_factors_follow_adr_0011(self):
        assert {
            "ev_ebit",
            "p_fcf",
            "fcf_margin",
            "net_debt_ebitda",
            "operating_margin",
            "roic",
            # F2.1: ADR-0011, Punkt 3 nennt sie mit
            "f_score",
            "operating_accruals",
            "cfo_assets",
        } == (INDUSTRY_RULE_EXCLUDED)

    def test_off_by_default(self):
        out = score(self._universe(), ScoringConfig()).set_index("symbol")
        assert not out["industry_rule"].any()
        assert out["rank_ev_ebit"].notna()["INS.DE"]

    def test_excluded_factors_are_not_ranked(self):
        out = score(self._universe(), ScoringConfig(industry_rules=True)).set_index("symbol")
        insurer = out.loc["INS.DE"].to_dict()
        assert bool(insurer["industry_rule"]) is True
        missing = {key for key, value in insurer.items() if _missing(value)}
        cfg = ScoringConfig()
        active = set(cfg.value_factors) | set(cfg.quality_factors)
        assert {f"rank_{key}" for key in INDUSTRY_RULE_EXCLUDED & active} <= missing
        # KBV und Shareholder Yield bleiben, Gewinnstabilität auch
        assert not {"rank_pb", "rank_shareholder_yield", "rank_earnings_stability"} & missing
        # Nur ein Quality-Faktor: kein Quality-Score, also kein Composite (M1)
        assert {"quality_score", "composite_score"} <= missing
        assert out.index[-1] == "INS.DE"  # hinter allen bewerteten Titeln, nach Symbol
        assert not out.drop(index="INS.DE")["industry_rule"].any()
        # Die Kennzahlen selbst bleiben stehen (CSV, Speicherung), sie zählen nur nicht
        assert insurer["ev_ebit"] == 4.0
        assert insurer["roic"] == _FULL_QUALITY["roic"]

    def test_others_only_lose_them_from_the_cross_section(self):
        frame = self._universe()
        ruled = score(frame, ScoringConfig(industry_rules=True)).set_index("symbol")
        without = score(frame[frame["symbol"] != "INS.DE"], ScoringConfig()).set_index("symbol")
        unruled = score(frame, ScoringConfig()).set_index("symbol")
        others = [s for s in ruled.index[ruled["rank_roic"].notna()] if s != "INS.DE"]
        assert others
        # Ausgeschlossene Faktoren: gerankt, als gäbe es den Versicherer nicht
        assert ruled.loc[others, "rank_ev_ebit"].tolist() == pytest.approx(
            without.loc[others, "rank_ev_ebit"].tolist()
        )
        # Übrige Faktoren: unverändert, der Versicherer zählt dort weiter mit
        assert ruled.loc[others, "rank_pb"].tolist() == pytest.approx(
            unruled.loc[others, "rank_pb"].tolist()
        )


def _missing(value: object) -> bool:
    return value is None or (isinstance(value, float) and math.isnan(value))


class TestBilanzqualitaetFactors:
    """F2.1 (ADR-0011, Punkt 1): F-Score, Accruals und CFO/Bilanzsumme stehen im Katalog. Die
    Standardauswahl (Profil v1, ``ScoringConfig()``) bleibt bei den fünf bisherigen."""

    NEW: ClassVar[dict[str, tuple[str, str]]] = {
        "f_score": ("f_score", "high"),
        "operating_accruals": ("operating_accruals", "low"),
        "cfo_assets": ("cfo_assets", "high"),
    }

    def test_in_the_catalog_with_direction(self):
        for key, factor in self.NEW.items():
            assert QUALITY_FACTOR_CATALOG[key] == factor

    def test_catalog_starts_with_the_default_selection(self):
        assert list(QUALITY_FACTOR_CATALOG)[: len(DEFAULT_QUALITY_FACTORS)] == list(
            DEFAULT_QUALITY_FACTORS
        )

    def test_off_by_default(self):
        assert not set(self.NEW) & set(DEFAULT_QUALITY_FACTORS)
        assert not set(self.NEW) & set(ScoringConfig().quality_factors)

    def test_ranked_when_switched_on(self):
        frame = _frame(
            {
                f"Q{i}.DE": {
                    "f_score": 9 - i,
                    "operating_accruals": -0.05 + 0.02 * i,
                    **_FULL_QUALITY,
                }
                for i in range(4)
            }
        )
        factors = {
            key: QUALITY_FACTOR_CATALOG[key] for key in ("roic", "f_score", "operating_accruals")
        }
        out = score(frame, ScoringConfig(quality_factors=factors)).set_index("symbol")
        # Hoher F-Score und niedrige Accruals sind gut
        assert out["rank_f_score"].idxmax() == "Q0.DE"
        assert out["rank_operating_accruals"].idxmax() == "Q0.DE"


class TestNetShareIssuanceFactor:
    """F2.2 (ADR-0011, Punkt 1): Netto-Emission im Katalog, niedrig ist gut. Sie ist kein
    Multiple: Negative Werte (Rückkäufe) bleiben im Ranking, auch wenn negative Multiples
    ausgeschlossen werden. Die Standardauswahl bleibt bei den vier bisherigen Value-Faktoren."""

    def test_in_the_catalog_and_not_a_multiple(self):
        assert VALUE_FACTOR_CATALOG["net_share_issuance"] == ("net_share_issuance", "low")
        assert "net_share_issuance" in NON_MULTIPLE_FACTORS
        assert not {"ev_ebit", "pb", "p_fcf"} & NON_MULTIPLE_FACTORS

    def test_catalog_starts_with_the_default_selection(self):
        assert list(VALUE_FACTOR_CATALOG)[: len(DEFAULT_VALUE_FACTORS)] == list(
            DEFAULT_VALUE_FACTORS
        )

    def test_off_by_default(self):
        assert "net_share_issuance" not in DEFAULT_VALUE_FACTORS
        assert "net_share_issuance" not in ScoringConfig().value_factors

    def test_buybacks_stay_in_the_ranking(self):
        frame = _frame(
            {
                "BUY.DE": {"net_share_issuance": -0.05, "ev_ebit": 10.0},
                "SAME.DE": {"net_share_issuance": 0.0, "ev_ebit": 11.0},
                "ISSUE.DE": {"net_share_issuance": 0.10, "ev_ebit": -3.0},
            }
        )
        factors = {key: VALUE_FACTOR_CATALOG[key] for key in ("ev_ebit", "net_share_issuance")}
        cfg = ScoringConfig(value_factors=factors, drop_negative_value_metrics=True)
        out = score(frame, cfg).set_index("symbol")
        ranks = out["rank_net_share_issuance"]
        assert ranks.notna().all()
        assert ranks.idxmax() == "BUY.DE"  # zurückgekauft: am besten
        # Negative Multiples bleiben ausgeschlossen
        assert out["rank_ev_ebit"].isna()["ISSUE.DE"]


# --- F2.3 (ADR-0011, Punkt 5): Momentum als Anker-Prüfung -------------------------------------


def _trap_universe(**cheap: Any) -> pd.DataFrame:
    """Fünf Titel. CHEAP.DE ist billig (Value 0,87), mittlere Quality (0,6), das schwächste
    Momentum (Rang 0,2) und F-Score 2: ein fallendes Messer."""
    rows: dict[str, dict[str, Any]] = {
        "CHEAP.DE": {
            "ev_ebit": 5.0,
            "pb_ratio": 0.5,
            "shareholder_yield": 0.10,
            "roic": 0.10,
            "fcf_margin": 0.10,
            "momentum_12_1": -0.40,
            "f_score": 2,
        },
        "B.DE": {
            "ev_ebit": 8.0,
            "pb_ratio": 1.0,
            "shareholder_yield": 0.05,
            "roic": 0.05,
            "fcf_margin": 0.05,
            "momentum_12_1": 0.05,
            "f_score": 6,
        },
        "C.DE": {
            "ev_ebit": 10.0,
            "pb_ratio": 1.5,
            "shareholder_yield": 0.04,
            "roic": 0.15,
            "fcf_margin": 0.15,
            "momentum_12_1": 0.10,
            "f_score": 7,
        },
        "D.DE": {
            "ev_ebit": 12.0,
            "pb_ratio": 2.0,
            "shareholder_yield": 0.03,
            "roic": 0.02,
            "fcf_margin": 0.02,
            "momentum_12_1": 0.20,
            "f_score": 5,
        },
        "E.DE": {
            "ev_ebit": 15.0,
            "pb_ratio": 3.0,
            "shareholder_yield": 0.02,
            "roic": 0.20,
            "fcf_margin": 0.20,
            "momentum_12_1": 0.30,
            "f_score": 8,
        },
    }
    rows["CHEAP.DE"].update(cheap)
    return _frame(rows)


def _trap_config(**values: Any) -> ScoringConfig:
    value = {k: DEFAULT_VALUE_FACTORS[k] for k in ("ev_ebit", "pb", "shareholder_yield")}
    quality = {k: DEFAULT_QUALITY_FACTORS[k] for k in ("roic", "fcf_margin")}
    return ScoringConfig(value_factors=value, quality_factors=quality, **values)


def _trap(frame: pd.DataFrame, **values: Any) -> pd.DataFrame:
    return score(frame, _trap_config(**values)).set_index("symbol")


def _value_score(out: pd.DataFrame) -> float:
    return float(out["value_score"].to_dict()["CHEAP.DE"])


class TestMomentumTrapRule:
    """Das Flag kommt zusätzlich bei hohem Value-Score, schwachem Momentum und schwachem
    F-Score. Das Ergebnis nennt die Regel; Momentum geht nicht in den Composite ein."""

    def test_off_by_default(self):
        cfg = ScoringConfig()
        assert (cfg.trap_momentum_rule, cfg.trap_momentum_max_rank, cfg.trap_fscore_max) == (
            False,
            0.30,
            3,
        )
        out = _trap(_trap_universe())
        assert not out.loc["CHEAP.DE", "value_trap_flag"]
        assert out["value_trap_reason"].isna().all()

    def test_the_combination_sets_the_flag(self):
        out = _trap(_trap_universe(), trap_momentum_rule=True)
        assert _value_score(out) >= 0.70
        assert out.loc["CHEAP.DE", "value_trap_flag"]
        assert out.loc["CHEAP.DE", "value_trap_reason"] == "momentum"
        others = out.drop(index="CHEAP.DE")
        assert not others["value_trap_flag"].any()
        assert others["value_trap_reason"].isna().all()

    @pytest.mark.parametrize(
        "change",
        [
            {"f_score": 4},  # F-Score über trap_fscore_max
            {"momentum_12_1": 0.50},  # starkes Momentum
            {"ev_ebit": 20.0, "pb_ratio": 4.0, "shareholder_yield": 0.0},  # nicht billig
            {"momentum_12_1": None},  # ohne Kurshistorie
            {"f_score": None},  # ohne F-Score
        ],
    )
    def test_each_condition_is_needed(self, change: dict[str, Any]):
        out = _trap(_trap_universe(**change), trap_momentum_rule=True)
        assert not out.loc["CHEAP.DE", "value_trap_flag"]
        assert pd.isna(out.loc["CHEAP.DE", "value_trap_reason"])

    def test_thresholds_come_from_the_config(self):
        loose = _trap(_trap_universe(f_score=4), trap_momentum_rule=True, trap_fscore_max=4)
        assert loose.loc["CHEAP.DE", "value_trap_reason"] == "momentum"
        strict = _trap(_trap_universe(), trap_momentum_rule=True, trap_momentum_max_rank=0.1)
        assert not strict.loc["CHEAP.DE", "value_trap_flag"]

    def test_the_quality_rule_comes_first(self):
        weak = {"roic": 0.01, "fcf_margin": 0.01}
        assert _trap(_trap_universe(**weak)).loc["CHEAP.DE", "value_trap_reason"] == "quality"
        both = _trap(_trap_universe(**weak), trap_momentum_rule=True)
        assert both.loc["CHEAP.DE", "value_trap_reason"] == "quality"

    def test_momentum_is_not_in_the_composite(self):
        with_momentum = _trap(_trap_universe(), trap_momentum_rule=True)
        without = _trap(_trap_universe().drop(columns=["momentum_12_1"]))
        pd.testing.assert_series_equal(with_momentum["composite_score"], without["composite_score"])
        # Kein Faktor-Rang: Der Momentum-Rang bleibt in score(), das Event traegt den Grund
        assert not any("momentum" in c and "rank" in c for c in with_momentum.columns)

    def test_no_f_score_under_the_industry_rule(self):
        frame = _trap_universe(industry="Banks - Regional")
        out = _trap(frame, trap_momentum_rule=True, industry_rules=True)
        assert _value_score(out) >= 0.70  # KBV und Shareholder Yield zählen weiter
        assert not out.loc["CHEAP.DE", "value_trap_flag"]
