"""Request/Reply-Contracts v1 (P4.8): Vorschau und Profil-Befehle zwischen web-api und scoring.

Wie bei den Events: Die JSON-Schemas stehen als Golden-Files unter ``tests/golden/contracts/rpc/v1``.
Eine Aenderung braucht ``--update-golden`` und eine Begruendung im Review.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest

from va_contracts.profile import ProfileParamsV1
from va_contracts.rpc.v1 import (
    PROFILE_ACTIVATE,
    PROFILE_SAVE,
    RPCS,
    SCORING_FACTORS,
    SCORING_PREVIEW,
    PreviewBasisV1,
    PreviewReplyV1,
    ProfileDetailV1,
    ProfileGetRequestV1,
    ProfileReplyV1,
    ProfilesReplyV1,
    ProfilesRequestV1,
    ProfileSummaryV1,
    ProfileVersionV1,
    RankedTitleV1,
    ReportCsvReplyV1,
    ReportReplyV1,
    ReportRequestV1,
    ReportV1,
    RpcErrorV1,
    SaveVersionReplyV1,
    SaveVersionRequestV1,
)

GOLDEN = Path(__file__).parent / "golden" / "contracts" / "rpc" / "v1"


def _schema_bytes(schema: dict[str, Any]) -> bytes:
    return (json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode()


class TestCatalog:
    def test_the_commands(self):
        assert set(RPCS) == {
            "scoring.factors",
            "scoring.preview",
            "scoring.profiles.save",
            "scoring.profiles.activate",
            # P4.9: was das web-api nicht mehr selbst aus fremden Schemas liest
            "scoring.profiles.list",
            "scoring.profiles.get",
            "notification.report",
            "notification.report.csv",
        }
        assert RPCS["scoring.preview"] is SCORING_PREVIEW

    @pytest.mark.parametrize("name", sorted(RPCS))
    def test_subjects_are_outside_the_stream(self, name):
        """``rpc.va.…``: Core-NATS, JetStream speichert nichts (Stream ``va.>``)."""
        assert RPCS[name].subject == f"rpc.va.{name}"

    def test_specs_name_their_models(self):
        assert SCORING_FACTORS.name == "scoring.factors"
        assert PROFILE_SAVE.request is SaveVersionRequestV1
        assert PROFILE_SAVE.reply is SaveVersionReplyV1
        assert PROFILE_ACTIVATE.subject == "rpc.va.scoring.profiles.activate"


class TestReplies:
    def test_every_reply_can_carry_an_error(self):
        for spec in RPCS.values():
            reply = spec.reply(error=RpcErrorV1(code="internal", message="kaputt"))
            assert reply.error is not None
            assert reply.error.code == "internal"

    def test_a_conflict_names_the_newest_version(self):
        reply = SaveVersionReplyV1(
            error=RpcErrorV1(code="conflict", message="nicht mehr die neueste", newest=3)
        )
        again = SaveVersionReplyV1.model_validate_json(reply.model_dump_json())
        assert again == reply
        assert again.error is not None
        assert again.error.newest == 3

    def test_a_preview_round_trips(self):
        title = RankedTitleV1(
            symbol="SAP.DE",
            name="SAP",
            index="DAX",
            passed_filter=True,
            rank=1,
            composite_score=0.9,
            value_score=0.8,
            quality_score=0.95,
            value_trap_flag=False,
        )
        basis = PreviewBasisV1(
            scoring_run_id=7,
            fetch_run_id=5,
            fetched_on=date(2026, 10, 30),
            active_profile_id=1,
            active_name="Standard",
            active_version=1,
            current=[title],
            preview=[title.model_copy(update={"rank": None, "passed_filter": False})],
        )
        reply = PreviewReplyV1(basis=basis)
        assert PreviewReplyV1.model_validate_json(reply.model_dump_json()) == reply

    def test_a_save_request_carries_the_params(self):
        request = SaveVersionRequestV1(
            profile_id=1, params=ProfileParamsV1(), based_on=2, comment=None
        )
        again = SaveVersionRequestV1.model_validate_json(request.model_dump_json())
        assert again.params == ProfileParamsV1()


class TestJsonSchemas:
    @pytest.mark.parametrize("name", sorted(RPCS))
    def test_request_schema(self, golden, name):
        schema = RPCS[name].request.model_json_schema()
        golden(f"contracts/rpc/v1/{name}.request.schema.json", _schema_bytes(schema))

    @pytest.mark.parametrize("name", sorted(RPCS))
    def test_reply_schema(self, golden, name):
        schema = RPCS[name].reply.model_json_schema()
        golden(f"contracts/rpc/v1/{name}.reply.schema.json", _schema_bytes(schema))

    def test_no_stale_schema_files(self):
        expected = {f"{n}.{part}.schema.json" for n in RPCS for part in ("request", "reply")}
        actual = {p.name for p in GOLDEN.iterdir()} if GOLDEN.exists() else set()
        assert actual == expected, f"Unerwartet: {actual - expected}, fehlt: {expected - actual}"


class TestReads:
    """P4.9: Nicht gefunden ist eine leere Antwort, kein Fehler (daraus wird 404)."""

    def test_an_unknown_report_is_empty(self):
        reply = ReportReplyV1()
        assert (reply.report, reply.error) == (None, None)

    def test_the_csv_travels_as_base64(self):
        content = b"\xef\xbb\xbfsymbol;name\nSAP.DE;SAP\n"  # BOM wie im Mail-Anhang
        reply = ReportCsvReplyV1(filename="value_ranking_20261107.csv", content=content)
        raw = reply.model_dump_json()
        assert "SAP.DE" not in raw  # Base64, nicht Klartext
        assert ReportCsvReplyV1.model_validate_json(raw).content == content

    def test_a_report_round_trips(self):
        report = ReportV1(
            id=3,
            run_id=1,
            scoring_run_id=2,
            subject="[Value] partial",
            generated_at=datetime(2026, 11, 7, 7, 45, tzinfo=UTC),
            csv_filename="value_ranking_20261107.csv",
            html="<!DOCTYPE html>",
        )
        reply = ReportReplyV1(report=report)
        assert ReportReplyV1.model_validate_json(reply.model_dump_json()) == reply

    def test_profiles_round_trip(self):
        created = datetime(2026, 10, 31, 9, 0, tzinfo=UTC)
        version = ProfileVersionV1(
            version=1,
            params=ProfileParamsV1(),
            parent_version=None,
            comment="Startwerte",
            created_at=created,
            active=True,
        )
        detail = ProfileDetailV1(
            id=1,
            name="Standard",
            created_at=created,
            latest_version=1,
            active_version=1,
            versions=[version],
        )
        listed = ProfilesReplyV1(
            profiles=[ProfileSummaryV1(**detail.model_dump(exclude={"versions"}))]
        )
        assert ProfilesReplyV1.model_validate_json(listed.model_dump_json()) == listed
        reply = ProfileReplyV1(profile=detail)
        assert ProfileReplyV1.model_validate_json(reply.model_dump_json()) == reply
        assert ProfileGetRequestV1(profile_id=1).profile_id == 1
        assert ProfilesRequestV1() == ProfilesRequestV1()
        assert ReportRequestV1(report_id=3).report_id == 3
