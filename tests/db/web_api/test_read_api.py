"""Lese-Endpunkte des web-api gegen ein echtes PostgreSQL (P3.2).

Ein kompletter Lauf (Yahoo gepatcht wie in ``test_pipeline_db``) legt Runs, Ranking, Titel und
die Mail an. Das web-api liest mit der Rolle ``va_read``.

Seit P4.9 laeuft jeder Test zweimal: aus den Tabellen und aus den Projektionen. Fuer die
Projektionen fuellt ``backfill_projections`` sie aus den Tabellen nach, Reports und Profile
beantwortet der Worker ueber NATS. Die Variante braucht ``TEST_NATS_URL``.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy.engine import make_url

from src.db.backfill import backfill_projections
from src.worker import serve
from tests.db.conftest import ROLE_PASSWORDS, _url_for
from tests.db.test_pipeline_db import _patched_run
from va_web_api.main import create_app
from va_web_api.settings import WebApiSettings

SYMBOLS = {"AAA.DE", "BBB.DE", "CCC.DE", "TINY.DE"}


def _read_client(db_url: str, nats_url: str | None = None) -> TestClient:
    """Ohne ``nats_url`` aus den Tabellen (``va_read``), mit aus den Projektionen (``va_web``)."""
    database = make_url(db_url).database
    assert database
    url = _url_for(database, "va_read", ROLE_PASSWORDS["va_read"])
    web = _url_for(database, "va_web", ROLE_PASSWORDS["va_web"])
    settings = WebApiSettings(
        auth_required=False,  # D1.2: Endpunkte, nicht Anmeldung
        database_url=SecretStr(url),
        nats_url=nats_url,
        projections_database_url=None if nats_url is None else SecretStr(web),
    )
    return TestClient(create_app(settings))


@contextmanager
def _projection_client(db_settings, db_url: str, nats_url: str, engine) -> Iterator[TestClient]:
    """P4.9: Projektionen aus den Tabellen nachfuellen, Worker fuer Reports und Profile starten."""
    backfill_projections(engine)
    stop = threading.Event()
    settings = db_settings.model_copy(update={"event_bus": "nats", "nats_url": nats_url})
    worker = threading.Thread(target=serve, args=(settings, stop), daemon=True)
    worker.start()
    try:
        with _read_client(db_url, nats_url) as client:
            deadline = time.monotonic() + 60
            while client.get("/api/v1/reports/999").status_code == 503:
                assert time.monotonic() < deadline, "Worker antwortet nicht"
                time.sleep(0.2)
            yield client
    finally:
        stop.set()
        worker.join(timeout=60)


@contextmanager
def _client(request, db_settings, db_url, engine) -> Iterator[TestClient]:
    if request.param == "tables":
        with _read_client(db_url) as client:
            yield client
        return
    nats_url = request.getfixturevalue("nats_url")
    with _projection_client(db_settings, db_url, nats_url, engine) as client:
        yield client


@pytest.fixture(params=["tables", "projections"])
def api(request, db_settings, db_url, engine):
    rc, _, _ = _patched_run(db_settings)
    assert rc == 0
    with _client(request, db_settings, db_url, engine) as client:
        yield client


@pytest.fixture(params=["tables", "projections"])
def empty_api(request, db_settings, db_url, engine):
    with _client(request, db_settings, db_url, engine) as client:
        yield client


VALUE_FACTORS = {"ev_ebit", "pb", "p_fcf", "shareholder_yield"}


def _run(api: TestClient) -> dict:
    [run] = api.get("/api/v1/runs").json()
    return run


class TestRuns:
    def test_list_shows_the_run(self, api):
        run = _run(api)
        assert (run["kind"], run["status"], run["dry_run"]) == ("batch", "partial", False)
        assert (run["universe_size"], run["scored_count"], run["failed_count"]) == (4, 3, 1)
        assert run["exit_code"] == 0
        assert run["finished_at"] is not None

    def test_newest_first_and_limited(self, db_settings, db_url):
        _patched_run(db_settings)
        _patched_run(db_settings, dry_run=True)
        with _read_client(db_url) as client:
            runs = client.get("/api/v1/runs").json()
            assert [r["dry_run"] for r in runs] == [True, False]
            assert len(client.get("/api/v1/runs?limit=1").json()) == 1
            assert client.get("/api/v1/runs?limit=1&offset=1").json()[0]["dry_run"] is False

    def test_limit_is_bounded(self, api):
        assert api.get("/api/v1/runs?limit=0").status_code == 422
        assert api.get("/api/v1/runs?limit=1000").status_code == 422

    def test_detail_links_fetch_scoring_and_report(self, api):
        detail = api.get(f"/api/v1/runs/{_run(api)['id']}").json()
        assert detail["fetch_run_id"] is not None
        assert detail["scoring_run_id"] is not None
        assert detail["report_id"] is not None
        assert detail["error"] is None

    def test_unknown_run_is_404(self, api):
        assert api.get("/api/v1/runs/999").status_code == 404


class TestRanking:
    def test_latest_lists_every_title_of_the_run(self, api):
        ranking = api.get("/api/v1/ranking/latest").json()
        rows = {row["symbol"]: row for row in ranking["rows"]}
        assert set(rows) == SYMBOLS
        assert rows["TINY.DE"]["passed_filter"] is False  # unter MIN_MARKET_CAP
        assert rows["TINY.DE"]["rank"] is None
        assert (rows["AAA.DE"]["name"], rows["AAA.DE"]["index"]) == ("Alpha", "DAX")
        assert rows["AAA.DE"]["market_cap"] == 5e9
        assert (ranking["value_weight"], ranking["quality_weight"]) == (0.6, 0.4)
        assert ranking["fetched_on"] == date.today().isoformat()
        assert ranking["universe_source"] == "iShares"

    def test_names_profile_and_parameters_of_the_scoring_run(self, api):
        # Track G (G3): Tooltips nennen Gewichte, Schwellen und Größenschwelle des Laufs
        ranking = api.get("/api/v1/ranking/latest").json()
        profile = ranking["profile"]
        assert profile["name"] == "Standard"
        assert profile["version"] >= 1
        params = ranking["params"]
        assert (params["value_weight"], params["value_trap_value_threshold"]) == (0.6, 0.7)
        assert params["value_trap_quality_threshold"] == 0.3
        assert params["min_market_cap"] > 0
        assert set(params["value_factors"]) <= VALUE_FACTORS
        assert params["value_factors"]

    def test_rows_are_in_rank_order(self, api):
        rows = api.get("/api/v1/ranking/latest").json()["rows"]
        ranks = [row["rank"] for row in rows]
        ranked = [r for r in ranks if r is not None]
        assert ranked == list(range(1, len(ranked) + 1))
        assert ranks[len(ranked) :] == [None] * (len(ranks) - len(ranked))  # Gefilterte am Ende

    def test_by_id_is_the_same_as_latest(self, api):
        latest = api.get("/api/v1/ranking/latest").json()
        by_id = api.get(f"/api/v1/ranking/{latest['scoring_run_id']}").json()
        assert by_id == latest

    def test_unknown_scoring_run_is_404(self, api):
        assert api.get("/api/v1/ranking/999").status_code == 404

    def test_without_any_scoring_run_latest_is_404(self, empty_api):
        assert empty_api.get("/api/v1/ranking/latest").status_code == 404


class TestInstruments:
    def test_detail_with_latest_snapshot_and_score_history(self, api):
        alpha = api.get("/api/v1/instruments/AAA.DE").json()
        assert (alpha["symbol"], alpha["isin"]) == ("AAA.DE", "DE000AAA0001")
        assert (alpha["name"], alpha["index"], alpha["sector"]) == ("Alpha", "DAX", "Industrials")
        assert alpha["latest"]["market_cap"] == 5e9
        assert alpha["latest"]["fetched_on"] == date.today().isoformat()
        [point] = alpha["score_history"]
        assert point["rank"] is not None
        assert point["composite_score"] is not None

    def test_score_point_says_how_many_titles_have_a_rank(self, api):
        ranking = api.get("/api/v1/ranking/latest").json()
        ranked = sum(row["rank"] is not None for row in ranking["rows"])
        [point] = api.get("/api/v1/instruments/AAA.DE").json()["score_history"]
        assert point["ranked_count"] == ranked

    def test_factor_ranks_of_the_newest_scoring_run(self, api):
        latest = api.get("/api/v1/ranking/latest").json()
        factors = api.get("/api/v1/instruments/AAA.DE").json()["factor_ranks"]
        assert factors["scoring_run_id"] == latest["scoring_run_id"]
        # Genau die Faktoren des Profils dieses Laufs; fehlende Daten als null
        active = set(latest["params"]["value_factors"]) | set(latest["params"]["quality_factors"])
        assert set(factors["ranks"]) == active
        assert all(rank is None or 0 <= rank <= 1 for rank in factors["ranks"].values())
        assert any(rank is not None for rank in factors["ranks"].values())

    def test_filtered_title_has_no_factor_ranks(self, api):
        assert api.get("/api/v1/instruments/TINY.DE").json()["factor_ranks"] is None

    def test_filtered_title_has_history_without_scores(self, api):
        [point] = api.get("/api/v1/instruments/TINY.DE").json()["score_history"]
        assert point["passed_filter"] is False
        assert point["composite_score"] is None

    def test_unknown_symbol_is_404(self, api):
        assert api.get("/api/v1/instruments/GIBTS.DE").status_code == 404


class TestReports:
    def test_report_with_html(self, api):
        report_id = api.get(f"/api/v1/runs/{_run(api)['id']}").json()["report_id"]
        report = api.get(f"/api/v1/reports/{report_id}").json()
        assert report["html"].startswith("<!DOCTYPE")
        assert "partial" in report["subject"]
        assert report["csv_filename"].startswith("value_ranking_")

    def test_csv_download(self, api):
        report_id = api.get(f"/api/v1/runs/{_run(api)['id']}").json()["report_id"]
        response = api.get(f"/api/v1/reports/{report_id}/csv")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/csv")
        assert 'filename="value_ranking_' in response.headers["content-disposition"]
        assert response.content.startswith(b"\xef\xbb\xbf")  # BOM wie im Mail-Anhang

    def test_unknown_report_is_404(self, api):
        assert api.get("/api/v1/reports/999").status_code == 404
        assert api.get("/api/v1/reports/999/csv").status_code == 404


class TestReadRole:
    def test_reads_with_the_read_role(self, api):
        assert api.app.state.engine.url.username == "va_read"  # type: ignore[attr-defined]


class TestBilanzqualitaet:
    """F2.1: F-Score, Accruals und CFO/Bilanzsumme kommen aus dem Abruf bis in Ranking und
    Titel-Detail, aus den Tabellen wie aus den Projektionen. Von Hand für AAA (Testdaten in
    ``test_pipeline_db``): F-Score 9, Accruals (100 - 150) / 4.900, CFO/Bilanzsumme 150 / 4.900."""

    def _check(self, figures: dict) -> None:
        assert figures["f_score"] == 9
        assert figures["operating_accruals"] == pytest.approx(-50.0 / 4_900.0)
        assert figures["cfo_assets"] == pytest.approx(150.0 / 4_900.0)

    def test_in_the_ranking(self, api):
        rows = api.get("/api/v1/ranking/latest").json()["rows"]
        self._check(next(row for row in rows if row["symbol"] == "AAA.DE"))

    def test_in_the_instrument_detail(self, api):
        self._check(api.get("/api/v1/instruments/AAA.DE").json()["latest"])

    def test_off_in_profile_v1(self, api):
        params = api.get("/api/v1/ranking/latest").json()["params"]
        assert not {"f_score", "operating_accruals", "cfo_assets"} & set(params["quality_factors"])


def _shares_over_a_year(symbol: str, start: date):
    """F2.2: ein Jahr Aktienanzahl relativ zu heute, 5 % zurückgekauft; CCC.DE ohne."""
    import pandas as pd

    if symbol == "CCC.DE":
        return None
    today = date.today()
    days = pd.DatetimeIndex(
        [pd.Timestamp(today - timedelta(days=370)), pd.Timestamp(today - timedelta(days=5))]
    ).tz_localize("Europe/Berlin")
    return pd.Series([1_000_000, 950_000], index=days)


@pytest.fixture(params=["tables", "projections"])
def issuance_api(request, db_settings, db_url, engine):
    rc, _, _ = _patched_run(db_settings, shares=_shares_over_a_year)
    assert rc == 0
    with _client(request, db_settings, db_url, engine) as client:
        yield client


class TestNettoEmission:
    """F2.2: Die Netto-Emission kommt aus dem Abruf bis in Ranking und Titel-Detail, aus den
    Tabellen wie aus den Projektionen; im Profil v1 ist sie aus."""

    def test_in_the_ranking(self, issuance_api):
        rows = issuance_api.get("/api/v1/ranking/latest").json()["rows"]
        row = next(row for row in rows if row["symbol"] == "AAA.DE")
        assert row["net_share_issuance"] == pytest.approx(-0.05)

    def test_in_the_instrument_detail(self, issuance_api):
        latest = issuance_api.get("/api/v1/instruments/AAA.DE").json()["latest"]
        assert latest["net_share_issuance"] == pytest.approx(-0.05)

    def test_off_in_profile_v1(self, issuance_api):
        params = issuance_api.get("/api/v1/ranking/latest").json()["params"]
        assert "net_share_issuance" not in params["value_factors"]


def _prices_over_a_year(symbol: str, start: date | None, known_splits: frozenset[date]):
    """F2.3: drei Handelstage relativ zu heute, 12-1-Momentum +20 %; CCC.DE ohne Kurse."""
    import pandas as pd

    if symbol == "CCC.DE":
        return None
    today = date.today()
    days = [today - timedelta(days=370), today - timedelta(days=35), today - timedelta(days=3)]
    index = pd.DatetimeIndex([pd.Timestamp(d) for d in days]).tz_localize("Europe/Berlin")
    closes = [100.0, 120.0, 110.0]
    return pd.DataFrame(
        {"close": closes, "adj_close": closes, "dividend": 0.0, "split": 0.0}, index=index
    )


@pytest.fixture(params=["tables", "projections"])
def momentum_api(request, db_settings, db_url, engine):
    rc, _, _ = _patched_run(db_settings, prices=_prices_over_a_year)
    assert rc == 0
    with _client(request, db_settings, db_url, engine) as client:
        yield client


class TestMomentumAndTrapReason:
    """F2.3: Momentum im Titel-Detail, der Grund des Flags in Ranking und Score-Verlauf, aus den
    Tabellen wie aus den Projektionen; im Profil v1 ist die Regel aus."""

    def test_momentum_in_the_instrument_detail(self, momentum_api):
        latest = momentum_api.get("/api/v1/instruments/AAA.DE").json()["latest"]
        assert latest["momentum_12_1"] == pytest.approx(0.20)

    def test_reason_in_the_ranking(self, momentum_api):
        rows = momentum_api.get("/api/v1/ranking/latest").json()["rows"]
        for row in rows:
            assert row["value_trap_reason"] == ("quality" if row["value_trap_flag"] else None)

    def test_reason_in_the_score_history(self, momentum_api):
        history = momentum_api.get("/api/v1/instruments/AAA.DE").json()["score_history"]
        assert history
        for point in history:
            assert "value_trap_reason" in point
            assert point["value_trap_reason"] == ("quality" if point["value_trap_flag"] else None)

    def test_rule_off_in_profile_v1(self, momentum_api):
        params = momentum_api.get("/api/v1/ranking/latest").json()["params"]
        assert params["trap_momentum_rule"] is False
