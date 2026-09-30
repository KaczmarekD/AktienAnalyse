"""get/write-Zugriffe auf das Schema market_data."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pandas as pd
import pytest
from sqlalchemy.exc import IntegrityError

from src.consensus import ConsensusEntry
from src.db.engine import session_scope
from src.db.recorder import snapshot_values
from src.db.repositories.market_data import MarketDataRepository, UniverseMember
from src.fundamentals import (
    Fundamentals,
    Identity,
    MarketData,
    Provenance,
    QualityMetrics,
    ValueMetrics,
)

T0 = datetime(2026, 10, 3, 5, 30, tzinfo=UTC)


def _statements(revenue: float, ebit: float = 500.0) -> dict[str, pd.DataFrame]:
    periods = [pd.Timestamp("2025-12-31"), pd.Timestamp("2024-12-31")]
    income = pd.DataFrame(
        {periods[0]: [revenue, ebit], periods[1]: [1_800.0, float("nan")]},
        index=["Total Revenue", "EBIT"],
    )
    balance = pd.DataFrame({periods[0]: [3_000.0]}, index=["Stockholders Equity"])
    return {"income": income, "balance": balance, "cashflow": pd.DataFrame()}


def _fetch_run(repo: MarketDataRepository, started_at: datetime = T0, **kw) -> int:
    return repo.write_fetch_run_start(
        provider="yfinance",
        provider_version="0.2.66",
        universe_source="iShares",
        universe_size=2,
        started_at=started_at,
        **kw,
    )


class TestInstruments:
    def test_get_or_create_is_idempotent(self, session):
        repo = MarketDataRepository(session)
        first = repo.get_or_create_instruments(["SAP.DE", "ALV.DE"])
        second = repo.get_or_create_instruments(["ALV.DE", "SAP.DE", "BAS.DE"])
        session.commit()
        assert first["SAP.DE"] == second["SAP.DE"]
        assert set(second) == {"SAP.DE", "ALV.DE", "BAS.DE"}
        instrument = repo.get_instrument("SAP.DE")
        assert instrument is not None
        assert instrument.symbol == "SAP.DE"

    def test_isin_is_backfilled_once_and_never_duplicated(self, engine):
        with session_scope(engine) as s:
            repo = MarketDataRepository(s)
            repo.get_or_create_instruments(["DAI.DE", "MBG.DE"])
            assert repo.write_isins({"DAI.DE": "DE0007100000"}) == 1
            # Tickerwechsel: gleiche ISIN fuer neues Symbol -> bleibt leer statt Konflikt
            assert repo.write_isins({"MBG.DE": "DE0007100000"}) == 0
            # Bereits gesetzte ISIN wird nicht ueberschrieben
            assert repo.write_isins({"DAI.DE": "XX0000000000"}) == 0
        with session_scope(engine) as s:
            repo = MarketDataRepository(s)
            assert repo.get_instrument("DAI.DE").isin == "DE0007100000"  # type: ignore[union-attr]
            assert repo.get_instrument("MBG.DE").isin is None  # type: ignore[union-attr]


class TestFetchRuns:
    def test_reusable_only_when_finished_same_day_and_successful(self, engine):
        day = T0.astimezone().date()
        with session_scope(engine) as s:
            repo = MarketDataRepository(s)
            unfinished = _fetch_run(repo)
            weak = _fetch_run(repo)
            repo.write_fetch_run_finish(weak, ok_count=1, success_share=0.5)
            imported = _fetch_run(repo, origin="import")
            repo.write_fetch_run_finish(imported, ok_count=2, success_share=1.0)
            good = _fetch_run(repo)
            repo.write_fetch_run_finish(good, ok_count=2, success_share=1.0)
        with session_scope(engine) as s:
            repo = MarketDataRepository(s)
            found = repo.get_reusable_fetch_run(day, min_success_share=0.8, symbols=[])
            assert found is not None
            assert found.id == good
            assert unfinished != good
            assert repo.get_reusable_fetch_run(day + timedelta(days=1), 0.8, symbols=[]) is None

    def test_reusable_only_if_universe_covers_symbols(self, engine):
        day = T0.astimezone().date()
        with session_scope(engine) as s:
            repo = MarketDataRepository(s)
            dax_only = _fetch_run(repo)
            repo.write_universe(dax_only, [UniverseMember("SAP.DE", "DAX", "SAP", "iShares")])
            repo.write_fetch_run_finish(dax_only, ok_count=1, success_share=1.0)
        with session_scope(engine) as s:
            repo = MarketDataRepository(s)
            # Ein reiner DAX-Abruf deckt ein DAX+MDAX-Universum nicht ab
            assert repo.get_reusable_fetch_run(day, 0.8, symbols=["SAP.DE", "SAX.DE"]) is None
            found = repo.get_reusable_fetch_run(day, 0.8, symbols=["SAP.DE"])
            assert found is not None
            assert found.id == dax_only

    def test_get_fetch_run(self, session):
        repo = MarketDataRepository(session)
        fid = _fetch_run(repo, note="hallo")
        fetch_run = repo.get_fetch_run(fid)
        assert fetch_run is not None
        assert fetch_run.note == "hallo"
        assert fetch_run.finished_at is None


class TestUniverse:
    def test_write_and_get_universe_and_membership_history(self, engine):
        with session_scope(engine) as s:
            repo = MarketDataRepository(s)
            first = _fetch_run(repo, started_at=T0)
            repo.write_universe(first, [UniverseMember("BOSS.DE", "MDAX", "Hugo Boss", "iShares")])
            second = _fetch_run(repo, started_at=T0 + timedelta(days=7))
            repo.write_universe(second, [UniverseMember("SAX.DE", "MDAX", "Stroeer", "Deka")])
        with session_scope(engine) as s:
            repo = MarketDataRepository(s)
            universe = repo.get_universe(second)
            assert universe.to_dict("records") == [
                {"symbol": "SAX.DE", "index_name": "MDAX", "name": "Stroeer", "source": "Deka"}
            ]
            history = repo.get_membership_history("BOSS.DE")
            assert list(history["fetch_run_id"]) == [first]
            assert list(history["index_name"]) == ["MDAX"]


class TestRawInfo:
    def test_payload_is_sanitised_and_readable(self, session):
        repo = MarketDataRepository(session)
        fid = _fetch_run(repo)
        iid = repo.get_or_create_instruments(["SAP.DE"])["SAP.DE"]
        repo.write_raw_info(
            fid,
            iid,
            {"marketCap": 1.5e11, "beta": float("nan"), "officers": [{"age": float("inf")}]},
            fetched_at=T0,
        )
        session.commit()
        payload = repo.get_raw_info(fid, "SAP.DE")
        assert payload == {"marketCap": 1.5e11, "beta": None, "officers": [{"age": None}]}


EPS_TREND = {"+1y": {"current": 4.548, "90daysAgo": 4.71843}, "0y": {"current": 3.69}}


class TestConsensusSnapshots:
    """ADR-0010, F1.1: je Abruf, Titel und Art genau eine Zeile - nur anfuegen."""

    def test_one_row_per_kind_with_status(self, engine):
        entries = {
            "eps_trend": ConsensusEntry("ok", EPS_TREND, None),
            "growth_estimates": ConsensusEntry("empty", None, None),
            "analyst_price_targets": ConsensusEntry("error", None, "RuntimeError: 429"),
        }
        with session_scope(engine) as s:
            repo = MarketDataRepository(s)
            fid = _fetch_run(repo)
            iid = repo.get_or_create_instruments(["KGX.DE"])["KGX.DE"]
            repo.write_consensus(fid, iid, entries, fetched_at=T0)
        with session_scope(engine) as s:
            assert MarketDataRepository(s).get_consensus(fid, "KGX.DE") == entries

    def test_second_fetch_adds_rows_and_keeps_the_old_ones(self, engine):
        with session_scope(engine) as s:
            repo = MarketDataRepository(s)
            first = _fetch_run(repo, started_at=T0)
            iid = repo.get_or_create_instruments(["KGX.DE"])["KGX.DE"]
            repo.write_consensus(
                first, iid, {"eps_trend": ConsensusEntry("ok", EPS_TREND, None)}, fetched_at=T0
            )
            second = _fetch_run(repo, started_at=T0 + timedelta(days=7))
            revised = {"+1y": {"current": 4.40, "90daysAgo": 4.60}}
            repo.write_consensus(
                second,
                iid,
                {"eps_trend": ConsensusEntry("ok", revised, None)},
                fetched_at=T0 + timedelta(days=7),
            )
        with session_scope(engine) as s:
            repo = MarketDataRepository(s)
            assert repo.get_consensus(first, "KGX.DE")["eps_trend"].payload == EPS_TREND
            assert repo.get_consensus(second, "KGX.DE")["eps_trend"].payload == revised

    def test_nothing_to_write_is_fine(self, session):
        repo = MarketDataRepository(session)
        fid = _fetch_run(repo)
        iid = repo.get_or_create_instruments(["SAP.DE"])["SAP.DE"]
        repo.write_consensus(fid, iid, {}, fetched_at=T0)
        session.commit()
        assert repo.get_consensus(fid, "SAP.DE") == {}

    @pytest.mark.parametrize(
        "entry",
        [
            ConsensusEntry("ok", None, None),  # ok ohne Payload
            ConsensusEntry("error", None, None),  # Fehler ohne Text
            ConsensusEntry("empty", {"x": 1}, None),  # leer, aber mit Payload
            ConsensusEntry("unklar", None, None),  # type: ignore[arg-type] - unbekannter Status
        ],
    )
    def test_inconsistent_entries_are_rejected_by_the_database(self, session, entry):
        repo = MarketDataRepository(session)
        fid = _fetch_run(repo)
        iid = repo.get_or_create_instruments(["SAP.DE"])["SAP.DE"]
        with pytest.raises(IntegrityError):
            repo.write_consensus(fid, iid, {"eps_trend": entry}, fetched_at=T0)

    def test_unknown_kind_is_rejected_by_the_database(self, session):
        repo = MarketDataRepository(session)
        fid = _fetch_run(repo)
        iid = repo.get_or_create_instruments(["SAP.DE"])["SAP.DE"]
        with pytest.raises(IntegrityError):
            repo.write_consensus(
                fid, iid, {"kursziel_raten": ConsensusEntry("empty", None, None)}, fetched_at=T0
            )


class TestStatementVersioning:
    def _write(self, engine, fid_started: datetime, revenue: float) -> tuple[int, int]:
        with session_scope(engine) as s:
            repo = MarketDataRepository(s)
            fid = _fetch_run(repo, started_at=fid_started)
            iid = repo.get_or_create_instruments(["SAP.DE"])["SAP.DE"]
            inserted = repo.write_statements(
                fid, iid, _statements(revenue), currency="EUR", fetched_at=fid_started
            )
        return fid, inserted

    def test_unchanged_values_are_not_duplicated(self, engine):
        _, first = self._write(engine, T0, 2_000.0)
        _, second = self._write(engine, T0 + timedelta(days=7), 2_000.0)
        assert first == 4  # NaN wird nicht gespeichert
        assert second == 0

    def test_restatement_creates_new_version(self, engine):
        self._write(engine, T0, 2_000.0)
        _, inserted = self._write(engine, T0 + timedelta(days=7), 1_950.0)
        assert inserted == 1
        with session_scope(engine) as s:
            history = MarketDataRepository(s).get_statement_history("SAP.DE", "Total Revenue")
        latest = history[history["period_end"] == date(2025, 12, 31)]
        assert list(latest["value"]) == [2_000.0, 1_950.0]

    def test_flip_flop_a_b_a_is_recorded(self, engine):
        self._write(engine, T0, 2_000.0)
        self._write(engine, T0 + timedelta(days=7), 1_950.0)
        _, inserted = self._write(engine, T0 + timedelta(days=14), 2_000.0)
        assert inserted == 1

    def test_as_of_returns_point_in_time_values(self, engine):
        self._write(engine, T0, 2_000.0)
        self._write(engine, T0 + timedelta(days=7), 1_950.0)
        with session_scope(engine) as s:
            repo = MarketDataRepository(s)
            before = repo.get_statements_as_of("SAP.DE", T0 + timedelta(days=1))
            after = repo.get_statements_as_of("SAP.DE", T0 + timedelta(days=8))

        def revenue(df: pd.DataFrame) -> float:
            row = df[
                (df["line_item"] == "Total Revenue") & (df["period_end"] == date(2025, 12, 31))
            ]
            return float(row["value"].iloc[0])

        assert revenue(before) == 2_000.0
        assert revenue(after) == 1_950.0
        assert len(after) == 4


class TestFxRates:
    def test_duplicate_rate_per_fetch_run_is_ignored(self, session):
        repo = MarketDataRepository(session)
        fid = _fetch_run(repo)
        repo.write_fx_rate(fid, "USD", "EUR", 0.9, fetched_at=T0)
        repo.write_fx_rate(fid, "USD", "EUR", 0.9, fetched_at=T0)
        session.commit()
        rates = repo.get_fx_rates(fid)
        assert rates[["from_ccy", "to_ccy", "rate"]].to_dict("records") == [
            {"from_ccy": "USD", "to_ccy": "EUR", "rate": 0.9}
        ]


def _fundamentals(symbol: str = "SAP.DE", ev_ebit: float | None = 22.0) -> Fundamentals:
    return Fundamentals(
        identity=Identity(
            symbol=symbol,
            name="SAP",
            index="DAX",
            sector="Technology",
            currency="EUR",
            financial_currency="EUR",
        ),
        market=MarketData(price=200.0, market_cap=2.4e11, enterprise_value=2.5e11),
        value=ValueMetrics(ev_ebit=ev_ebit, pb_ratio=5.0),
        quality=QualityMetrics(roic=0.2),
        provenance=Provenance(
            fetched_at=T0, fiscal_period_end=date(2025, 12, 31), statement_fx=1.0
        ),
        errors=["fx irgendwas"],
    )


class TestSnapshots:
    def test_roundtrip_matches_flat_dict_columns(self, session):
        repo = MarketDataRepository(session)
        fid = _fetch_run(repo)
        fund = _fundamentals()
        iid = repo.get_or_create_instruments([fund.symbol])[fund.symbol]
        repo.write_snapshot(fid, iid, snapshot_values(fund))
        session.commit()

        df = repo.get_snapshots_df(fid)
        assert set(fund.to_flat_dict()) <= set(df.columns)
        row = df.iloc[0]
        assert row["symbol"] == "SAP.DE"
        assert row["index"] == "DAX"
        assert row["ev_ebit"] == 22.0
        assert row["errors"] == "fx irgendwas"
        assert pd.isna(row["pe_ratio"])

    def test_snapshots_can_be_limited_to_symbols(self, session):
        repo = MarketDataRepository(session)
        fid = _fetch_run(repo)
        for symbol in ("SAP.DE", "SAX.DE"):
            iid = repo.get_or_create_instruments([symbol])[symbol]
            repo.write_snapshot(fid, iid, snapshot_values(_fundamentals(symbol)))
        session.commit()
        assert list(repo.get_snapshots_df(fid, symbols=["SAP.DE"])["symbol"]) == ["SAP.DE"]
        assert len(repo.get_snapshots_df(fid)) == 2

    def test_unknown_column_is_rejected(self, session):
        repo = MarketDataRepository(session)
        fid = _fetch_run(repo)
        iid = repo.get_or_create_instruments(["SAP.DE"])["SAP.DE"]
        with pytest.raises(ValueError, match="neuer_faktor"):
            repo.write_snapshot(fid, iid, {"neuer_faktor": 1.0})

    def test_metric_history_over_fetch_runs(self, engine):
        with session_scope(engine) as s:
            repo = MarketDataRepository(s)
            for week, ev_ebit in enumerate((20.0, 18.0)):
                fid = _fetch_run(repo, started_at=T0 + timedelta(days=7 * week))
                iid = repo.get_or_create_instruments(["SAP.DE"])["SAP.DE"]
                repo.write_snapshot(fid, iid, snapshot_values(_fundamentals(ev_ebit=ev_ebit)))
        with session_scope(engine) as s:
            history = MarketDataRepository(s).get_metric_history("SAP.DE", "ev_ebit")
        assert list(history["value"]) == [20.0, 18.0]

    def test_metric_history_rejects_unknown_metric(self, session):
        with pytest.raises(ValueError, match="drop table"):
            MarketDataRepository(session).get_metric_history("SAP.DE", "drop table")
