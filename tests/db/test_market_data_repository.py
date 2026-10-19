"""get/write-Zugriffe auf das Schema market_data."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

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
from src.history import PriceBar, daily_share_counts

T0 = datetime(2026, 10, 3, 5, 30, tzinfo=UTC)
WEEK = timedelta(days=7)


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


QUARTERLY_FIXTURES = Path(__file__).parents[1] / "fixtures" / "quarterly"


def _recorded_quarters(symbol: str) -> dict[str, pd.DataFrame]:
    """Echte Quartalsabschluesse (yfinance 0.2.66, aufgezeichnet am 30.09.2026)."""
    doc = json.loads((QUARTERLY_FIXTURES / f"{symbol}.json").read_text(encoding="utf-8"))
    return {
        name: pd.DataFrame(
            part["data"],
            index=part["index"],
            columns=[pd.Timestamp(c) for c in part["columns"]],
        )
        for name, part in doc["statements"].items()
    }


def _revenue_frame(period: str, revenue: float) -> dict[str, pd.DataFrame]:
    return {"income": pd.DataFrame({pd.Timestamp(period): [revenue]}, index=["Total Revenue"])}


class TestQuarterlyStatements:
    """F1.2: Quartale werden versioniert wie Jahreswerte, aber getrennt davon."""

    def _write(self, engine, statements, *, frequency, started_at=T0, symbol="SAP.DE") -> int:
        with session_scope(engine) as s:
            repo = MarketDataRepository(s)
            fid = _fetch_run(repo, started_at=started_at)
            iid = repo.get_or_create_instruments([symbol])[symbol]
            return repo.write_statements(
                fid, iid, statements, currency="EUR", fetched_at=started_at, frequency=frequency
            )

    def test_recorded_quarters_are_stored_completely(self, engine):
        quarters = _recorded_quarters("SAP.DE")
        expected = sum(int(df.notna().sum().sum()) for df in quarters.values())
        assert self._write(engine, quarters, frequency="quarterly") == expected
        with session_scope(engine) as s:
            stored = MarketDataRepository(s).get_statements_as_of(
                "SAP.DE", T0, frequency="quarterly"
            )
        assert len(stored) == expected
        assert set(stored["period_end"]) == {
            pd.Timestamp(c).date() for c in quarters["income"].columns
        }
        revenue = stored[
            (stored["line_item"] == "Total Revenue") & (stored["period_end"] == date(2026, 6, 30))
        ]
        assert float(revenue["value"].iloc[0]) == 9_878_000_000.0

    def test_missing_quarterly_statement_is_skipped(self, engine):
        quarters = _recorded_quarters("ALV.DE")
        assert quarters["cashflow"].empty
        self._write(engine, quarters, frequency="quarterly", symbol="ALV.DE")
        with session_scope(engine) as s:
            stored = MarketDataRepository(s).get_statements_as_of(
                "ALV.DE", T0, frequency="quarterly"
            )
        assert set(stored["statement"]) == {"income", "balance"}

    def test_unchanged_quarters_are_not_duplicated(self, engine):
        quarters = _recorded_quarters("SAP.DE")
        self._write(engine, quarters, frequency="quarterly")
        assert self._write(engine, quarters, frequency="quarterly", started_at=T0 + WEEK) == 0

    def test_revised_quarter_creates_new_version(self, engine):
        self._write(engine, _revenue_frame("2026-06-30", 9_878.0), frequency="quarterly")
        revised = _revenue_frame("2026-06-30", 9_900.0)
        assert self._write(engine, revised, frequency="quarterly", started_at=T0 + WEEK) == 1
        with session_scope(engine) as s:
            history = MarketDataRepository(s).get_statement_history(
                "SAP.DE", "Total Revenue", frequency="quarterly"
            )
        assert list(history["value"]) == [9_878.0, 9_900.0]

    def test_annual_and_quarterly_values_are_kept_apart(self, engine):
        """Geschaeftsjahr 2025 und Q4 2025 enden am selben Tag - beide bleiben erhalten."""
        annual = _revenue_frame("2025-12-31", 36_000.0)
        q4 = _revenue_frame("2025-12-31", 9_700.0)
        assert self._write(engine, annual, frequency="annual") == 1
        assert self._write(engine, q4, frequency="quarterly", started_at=T0 + WEEK) == 1
        assert self._write(engine, annual, frequency="annual", started_at=T0 + 2 * WEEK) == 0
        later = T0 + 3 * WEEK
        with session_scope(engine) as s:
            repo = MarketDataRepository(s)
            assert list(repo.get_statements_as_of("SAP.DE", later)["value"]) == [36_000.0]
            quarterly = repo.get_statements_as_of("SAP.DE", later, frequency="quarterly")
            assert list(quarterly["value"]) == [9_700.0]
            assert list(repo.get_statement_history("SAP.DE", "Total Revenue")["value"]) == [
                36_000.0
            ]

    def test_unknown_frequency_is_rejected(self, session):
        repo = MarketDataRepository(session)
        fid = _fetch_run(repo)
        iid = repo.get_or_create_instruments(["SAP.DE"])["SAP.DE"]
        with pytest.raises(ValueError, match="monthly"):
            repo.write_statements(
                fid,
                iid,
                _revenue_frame("2026-06-30", 1.0),
                currency="EUR",
                fetched_at=T0,
                frequency="monthly",
            )


SHARES_FIXTURES = Path(__file__).parents[1] / "fixtures" / "shares"


def _recorded_shares(symbol: str) -> pd.Series:
    """Echte Antwort von ``get_shares_full`` (yfinance 1.7, aufgezeichnet am 19.10.2026)."""
    doc = json.loads((SHARES_FIXTURES / f"{symbol}.json").read_text(encoding="utf-8"))
    stamps, values = zip(*doc["series"], strict=True)
    # Sommer- und Winterzeit wechseln, yfinance liefert den Index in der Zeitzone der Boerse
    index = pd.to_datetime(list(stamps), utc=True).tz_convert(doc["tz"])
    return pd.Series(values, index=index)


SHARE_COUNTS = {date(2026, 3, 11): 1_167_559_048, date(2026, 7, 29): 1_154_204_232}


class TestShareCounts:
    """F1.3: Historie der Aktienanzahl - neue Zeile nur bei neuem Datum oder neuem Wert."""

    def _write(self, engine, counts, *, started_at=T0, symbol="SAP.DE") -> int:
        with session_scope(engine) as s:
            repo = MarketDataRepository(s)
            fid = _fetch_run(repo, started_at=started_at)
            iid = repo.get_or_create_instruments([symbol])[symbol]
            return repo.write_share_counts(fid, iid, counts, fetched_at=started_at)

    def test_first_write_stores_every_day(self, engine):
        assert self._write(engine, SHARE_COUNTS) == 2
        with session_scope(engine) as s:
            stored = MarketDataRepository(s).get_share_counts("SAP.DE")
        assert dict(zip(stored["as_of"], stored["shares"], strict=True)) == SHARE_COUNTS

    def test_recorded_history_is_stored_completely(self, engine):
        counts = daily_share_counts(_recorded_shares("SAP.DE"))
        assert self._write(engine, counts) == len(counts)
        assert self._write(engine, counts, started_at=T0 + WEEK) == 0

    def test_unchanged_days_are_not_duplicated(self, engine):
        self._write(engine, SHARE_COUNTS)
        assert self._write(engine, SHARE_COUNTS, started_at=T0 + WEEK) == 0

    def test_new_day_adds_one_row(self, engine):
        self._write(engine, SHARE_COUNTS)
        later = {**SHARE_COUNTS, date(2026, 10, 1): 1_150_000_000}
        assert self._write(engine, later, started_at=T0 + WEEK) == 1

    def test_changed_value_creates_new_version_and_keeps_the_old(self, engine):
        self._write(engine, SHARE_COUNTS)
        revised = {date(2026, 7, 29): 1_154_000_000}
        assert self._write(engine, revised, started_at=T0 + WEEK) == 1
        with session_scope(engine) as s:
            repo = MarketDataRepository(s)
            now = repo.get_share_counts("SAP.DE").set_index("as_of")["shares"]
            before = repo.get_share_counts("SAP.DE", known_at=T0).set_index("as_of")["shares"]
            history = repo.get_share_count_history("SAP.DE")
        assert now[date(2026, 7, 29)] == 1_154_000_000
        assert now[date(2026, 3, 11)] == 1_167_559_048  # fehlt im Abruf, bleibt stehen
        assert before[date(2026, 7, 29)] == 1_154_204_232
        july = history[history["as_of"] == date(2026, 7, 29)]
        assert list(july["shares"]) == [1_154_204_232, 1_154_000_000]

    def test_counts_are_kept_per_instrument(self, engine):
        self._write(engine, SHARE_COUNTS)
        assert self._write(engine, SHARE_COUNTS, symbol="ALV.DE") == 2

    def test_last_dates_per_symbol(self, engine):
        self._write(engine, SHARE_COUNTS)
        self._write(engine, {date(2025, 11, 17): 1_000}, symbol="KGX.DE")
        with session_scope(engine) as s:
            repo = MarketDataRepository(s)
            repo.get_or_create_instruments(["ALV.DE"])  # bekannt, aber ohne Aktienanzahl
            last = repo.get_last_share_dates(["SAP.DE", "KGX.DE", "ALV.DE", "NEU.DE"])
        assert last == {"SAP.DE": date(2026, 7, 29), "KGX.DE": date(2025, 11, 17)}

    def test_nothing_to_write(self, engine):
        assert self._write(engine, {}) == 0


def _bar(close: float, *, adj: float | None = None, dividend=0.0, split=0.0) -> PriceBar:
    return PriceBar(
        close=close, adj_close=close if adj is None else adj, dividend=dividend, split=split
    )


PRE_SPLIT = {date(2026, 7, 28): _bar(300.0), date(2026, 7, 29): _bar(303.0)}


class TestPriceBars:
    """F1.4: Kurshistorie - neue Zeile nur bei neuem Tag oder geaendertem Wert."""

    def _write(self, engine, bars, *, started_at=T0, symbol="SAP.DE") -> int:
        with session_scope(engine) as s:
            repo = MarketDataRepository(s)
            fid = _fetch_run(repo, started_at=started_at)
            iid = repo.get_or_create_instruments([symbol])[symbol]
            return repo.write_price_bars(fid, iid, bars, fetched_at=started_at)

    def test_initial_fill_stores_every_day(self, engine):
        assert self._write(engine, PRE_SPLIT) == 2
        with session_scope(engine) as s:
            stored = MarketDataRepository(s).get_price_bars("SAP.DE")
        assert list(stored["trade_date"]) == list(PRE_SPLIT)
        assert list(stored["close"]) == [300.0, 303.0]
        assert list(stored.columns) == [
            "trade_date",
            "close",
            "adj_close",
            "dividend",
            "split",
            "first_seen_at",
        ]

    def test_incremental_window_adds_only_new_days(self, engine):
        self._write(engine, PRE_SPLIT)
        window = {**PRE_SPLIT, date(2026, 7, 30): _bar(305.0)}
        assert self._write(engine, window, started_at=T0 + WEEK) == 1

    def test_float_noise_creates_no_version(self, engine):
        self._write(engine, PRE_SPLIT)
        noisy = {d: _bar(b.close, adj=b.close * (1 + 6e-7)) for d, b in PRE_SPLIT.items()}
        assert self._write(engine, noisy, started_at=T0 + WEEK) == 0

    def test_split_creates_new_versions_and_keeps_the_old(self, engine):
        """1:3-Split am 30.07.: Yahoo passt alle aelteren Kurse an."""
        self._write(engine, PRE_SPLIT)
        after = {
            date(2026, 7, 28): _bar(100.0),
            date(2026, 7, 29): _bar(101.0),
            date(2026, 7, 30): _bar(102.0, split=3.0),
        }
        assert self._write(engine, after, started_at=T0 + WEEK) == 3
        with session_scope(engine) as s:
            repo = MarketDataRepository(s)
            now = repo.get_price_bars("SAP.DE").set_index("trade_date")
            before = repo.get_price_bars("SAP.DE", known_at=T0).set_index("trade_date")
            history = repo.get_price_bar_history("SAP.DE")
        assert list(now["close"]) == [100.0, 101.0, 102.0]
        assert now.at[date(2026, 7, 30), "split"] == 3.0
        assert list(before["close"]) == [300.0, 303.0]
        assert len(history) == 5
        july_28 = history[history["trade_date"] == date(2026, 7, 28)]
        assert list(july_28["close"]) == [300.0, 100.0]

    def test_dividend_adjustment_of_adj_close_is_a_new_version(self, engine):
        self._write(engine, PRE_SPLIT)
        adjusted = {d: _bar(b.close, adj=b.close * 0.99) for d, b in PRE_SPLIT.items()}
        assert self._write(engine, adjusted, started_at=T0 + WEEK) == 2

    def test_missing_adj_close_is_stored_empty(self, engine):
        bars = {date(2026, 7, 28): PriceBar(300.0, None, 0.0, 0.0)}
        assert self._write(engine, bars) == 1
        with session_scope(engine) as s:
            stored = MarketDataRepository(s).get_price_bars("SAP.DE")
        assert stored["adj_close"].isna().all()

    def test_history_state_per_symbol(self, engine):
        self._write(engine, {**PRE_SPLIT, date(2000, 6, 26): _bar(50.0, split=3.0)})
        self._write(engine, {date(2025, 11, 17): _bar(40.0)}, symbol="KGX.DE")
        with session_scope(engine) as s:
            repo = MarketDataRepository(s)
            repo.get_or_create_instruments(["ALV.DE"])  # bekannt, aber ohne Kurse
            symbols = ["SAP.DE", "KGX.DE", "ALV.DE"]
            last = repo.get_last_price_dates(symbols)
            splits = repo.get_price_split_days(symbols)
        assert last == {"SAP.DE": date(2026, 7, 29), "KGX.DE": date(2025, 11, 17)}
        assert splits == {"SAP.DE": frozenset({date(2000, 6, 26)})}

    def test_nothing_to_write(self, engine):
        assert self._write(engine, {}) == 0


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
