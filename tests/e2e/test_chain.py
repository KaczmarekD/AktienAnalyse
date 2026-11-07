"""Ende-zu-Ende (U5.2): ein Lauf durch die ganze Kette, von aussen geprueft.

Batch -> Datenbank -> Mail in Mailpit, web-api hinter nginx und das UI. Ersetzt den
Frontend-Smoke der CI (P3.6) und prueft dazu, dass Mail, API und UI dasselbe zeigen.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import httpx
import pandas as pd
import pytest

from src.regression.case import SCORE_COLUMNS
from src.regression.compare import compare_csv, compare_scores

from .conftest import get_json

if TYPE_CHECKING:
    from src.regression.case import ReplayCase


def _csv_attachment(mailpit: httpx.Client, mail: dict[str, Any]) -> bytes:
    [attachment] = [a for a in mail["Attachments"] if a["FileName"].endswith(".csv")]
    response = mailpit.get(f"/api/v1/message/{mail['ID']}/part/{attachment['PartID']}")
    response.raise_for_status()
    return response.content


def _lines(text: str) -> list[str]:
    """Zeilen ohne Unterschiede im Zeilenende: SMTP uebertraegt CRLF."""
    return [line.rstrip() for line in text.replace("\r\n", "\n").split("\n") if line.strip()]


class TestUi:
    """nginx vor dem web-api, wie auf der NAS (vorher docker/frontend-smoke.sh)."""

    @pytest.mark.parametrize("path", ["/", "/runs/1", "/ranking"])
    def test_angular_routes_return_the_app(self, ui, path):
        response = ui.get(path)
        assert response.status_code == 200
        assert "<app-root" in response.text

    def test_api_answers_through_nginx(self, ui):
        assert get_json(ui, "/api/v1/health")["status"] == "ok"

    def test_security_headers(self, ui):
        headers = ui.get("/").headers
        assert headers["x-content-type-options"] == "nosniff"
        assert "default-src 'self'" in headers["content-security-policy"]
        assert "no-cache" in headers["cache-control"]  # index.html nie aus dem Cache

    def test_unknown_host_gets_no_answer(self, base_url):
        # return 444: nginx schliesst die Verbindung ohne Antwort (DNS-Rebinding)
        with pytest.raises(httpx.RemoteProtocolError):
            httpx.get(f"{base_url}/", headers={"Host": "boese.example"}, timeout=10)


class TestRunReachesEveryone:
    """Mail, API und Report zeigen denselben Lauf - mit echten wie mit Replay-Daten."""

    def test_run_finished_and_sent(self, run):
        assert run["status"] in {"success", "partial"}, run
        assert run["exit_code"] == 0
        assert run["scoring_run_id"] is not None

    def test_mail_carries_the_report(self, mail, report):
        assert _lines(mail["HTML"]) == _lines(report["html"])

    def test_mail_csv_equals_the_report_csv(self, ui, mailpit, mail, report):
        api_csv = ui.get(f"/api/v1/reports/{report['id']}/csv")
        api_csv.raise_for_status()
        assert compare_csv(api_csv.content, _csv_attachment(mailpit, mail)) == []

    def test_ranking_of_the_run_is_complete(self, ui, run):
        # Das Ranking dieses Laufs, nicht "latest": Lokal kann ein Dry-Run juenger sein
        ranking = get_json(ui, f"/api/v1/ranking/{run['scoring_run_id']}")
        ranked = [r["rank"] for r in ranking["rows"] if r["rank"] is not None]
        assert ranked == list(range(1, len(ranked) + 1))

    def test_instrument_shows_the_rank_of_the_run(self, ui, run):
        top = get_json(ui, f"/api/v1/ranking/{run['scoring_run_id']}")["rows"][0]
        instrument = get_json(ui, f"/api/v1/instruments/{top['symbol']}")
        assert instrument["symbol"] == top["symbol"]
        [point] = [
            p for p in instrument["score_history"] if p["scoring_run_id"] == run["scoring_run_id"]
        ]
        assert point["rank"] == 1


class TestReplayResult:
    """Nur mit Replay-Daten (E2E_FIXTURE): Das Ergebnis steht fest."""

    @pytest.mark.usefixtures("expected")
    def test_only_this_mail_in_mailpit(self, mailpit):
        """Genau ein Report. Bestaetigungsmails (D1.6, tests/e2e/test_auth.py) zaehlen nicht mit,
        sie gehen an die neue Adresse eines Kontos."""
        messages = get_json(mailpit, "/api/v1/messages", limit=50)["messages"]
        reports = [m for m in messages if not m["Subject"].endswith("Mail-Adresse bestätigen")]
        assert len(reports) == 1

    @pytest.mark.usefixtures("expected")
    def test_latest_ranking_is_the_replayed_run(self, ui, run):
        ranking = get_json(ui, "/api/v1/ranking/latest")
        assert ranking["scoring_run_id"] == run["scoring_run_id"]
        assert ranking["universe_source"] == "Replay"

    def test_scores_and_ranks_as_in_the_fixture(self, ui, expected: ReplayCase):
        rows = get_json(ui, "/api/v1/ranking/latest")["rows"]
        actual = pd.DataFrame(rows).rename(columns={"rank": "rank_overall"})
        assert compare_scores(expected.scores, actual.reindex(columns=list(SCORE_COLUMNS))) == []

    def test_csv_as_in_the_fixture(self, mailpit, mail, expected: ReplayCase):
        assert expected.csv is not None
        assert compare_csv(expected.csv, _csv_attachment(mailpit, mail)) == []

    @pytest.mark.usefixtures("expected")
    def test_mail_names_the_profile(self, mail):
        # P2b.3: Der erste Lauf legt "Standard" v1 an und rechnet damit
        assert "Profil Standard v1" in mail["HTML"]

    def test_subject_names_the_top_title(self, mail, expected: ReplayCase):
        top = expected.scores.sort_values("rank_overall").iloc[0]["symbol"]
        names = expected.snapshots.set_index("symbol")["name"]
        assert f"Top: {names[top]}" in mail["Subject"]


class TestScoringProfiles:
    """P3.3: Profile ueber nginx; das web-api speichert mit va_profiles aus dem Init-Skript."""

    def _standard(self, ui: httpx.Client) -> dict[str, Any]:
        [standard] = [
            p for p in get_json(ui, "/api/v1/scoring/profiles") if p["name"] == "Standard"
        ]
        return get_json(ui, f"/api/v1/scoring/profiles/{standard['id']}")

    @pytest.mark.usefixtures("run")
    def test_standard_is_active(self, ui):
        assert self._standard(ui)["active_version"] is not None

    @pytest.mark.usefixtures("run")
    def test_preview_with_the_active_profile_changes_nothing(self, ui):
        active = next(v for v in self._standard(ui)["versions"] if v["active"])
        response = ui.post("/api/v1/scoring/preview", json=active["params"])
        response.raise_for_status()
        body = response.json()
        assert (body["entered"], body["left"]) == ([], [])
        assert all(r["rank"] == r["rank_active"] for r in body["rows"])

    @pytest.mark.usefixtures("expected")  # nur im Wegwerf-Stack: legt eine Version an
    def test_saving_needs_the_newest_version(self, ui):
        detail = self._standard(ui)
        newest = detail["latest_version"]
        body = {"params": {**detail["versions"][0]["params"], "value_weight": 0.5}}
        url = f"/api/v1/scoring/profiles/{detail['id']}"
        saved = ui.put(url, json=body, headers={"If-Match": f'"{newest}"'})
        assert saved.status_code == 201, saved.text
        assert saved.json()["version"] == newest + 1
        stale = ui.put(url, json=body, headers={"If-Match": f'"{newest}"'})
        assert stale.status_code == 409
