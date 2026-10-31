"""Lese-Endpunkte des web-api gegen ein echtes PostgreSQL (P3.2).

Ein kompletter Lauf (Yahoo gepatcht wie in ``test_pipeline_db``) legt Runs, Ranking, Titel und
die Mail an. Das web-api liest mit der Rolle ``va_read``.
"""

from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy.engine import make_url

from tests.db.conftest import ROLE_PASSWORDS, _url_for
from tests.db.test_pipeline_db import _patched_run
from va_web_api.main import create_app
from va_web_api.settings import WebApiSettings

SYMBOLS = {"AAA.DE", "BBB.DE", "CCC.DE", "TINY.DE"}


def _read_client(db_url: str) -> TestClient:
    database = make_url(db_url).database
    assert database
    url = _url_for(database, "va_read", ROLE_PASSWORDS["va_read"])
    return TestClient(create_app(WebApiSettings(database_url=SecretStr(url))))


@pytest.fixture
def api(db_settings, db_url):
    rc, _, _ = _patched_run(db_settings)
    assert rc == 0
    with _read_client(db_url) as client:
        yield client


@pytest.fixture
def empty_api(db_url):
    with _read_client(db_url) as client:
        yield client


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
