"""Contracts v1 (P1.2): Datenformate zwischen den Services, siehe docs/architecture/events.md.

Die Modelle liegen in ``va_contracts`` und duerfen den Altbestand ``src`` nicht kennen
(import-linter). Die Tests pruefen deshalb hier, dass sie zu ``src.fundamentals`` und zur
Ausgabe von ``src.scoring.score`` passen - mit dem eingefrorenen Golden-Datensatz.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, fields
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import pandas as pd
import pytest
from pydantic import BaseModel, ValidationError
from va_contracts import Envelope, new_envelope
from va_contracts.events.v1 import (
    EVENTS,
    FETCH_PROGRESSED,
    PROFILE_ACTIVATED,
    PROFILE_SAVED,
    REPORT_SENT,
    RUN_FAILED,
    RUN_REQUESTED,
    SCORING_RUN_COMPLETED,
    SNAPSHOT_COMPLETED,
    FetchProgressedV1,
    FundamentalsV1,
    ProfileActivatedV1,
    ProfileRefV1,
    ProfileSavedV1,
    RankingRowV1,
    ReportSentV1,
    RunFailedV1,
    ScoringRunCompletedV1,
    ScreeningRunRequestedV1,
    SnapshotCompletedV1,
)

from src.fundamentals import (
    Fundamentals,
    Growth,
    Identity,
    MarketData,
    Provenance,
    QualityMetrics,
    ValueMetrics,
)
from src.scoring import score

GOLDEN_INPUT = Path(__file__).parent / "golden" / "input_fundamentals.json"
FETCHED = datetime(2026, 10, 17, 5, 30, tzinfo=UTC)

# Gruppe im Contract -> Dataclass in src.fundamentals
GROUPS: dict[str, type] = {
    "identity": Identity,
    "market": MarketData,
    "value": ValueMetrics,
    "quality": QualityMetrics,
    "growth": Growth,
    "provenance": Provenance,
}


def _golden_fundamentals() -> list[Fundamentals]:
    """Der eingefrorene Datensatz des Golden-Masters als Dataclasses, mit Herkunftsangaben."""
    records = json.loads(GOLDEN_INPUT.read_text(encoding="utf-8"))
    result = []
    for i, flat in enumerate(records):
        groups = {
            name: cls(**{f.name: flat.get(f.name) for f in fields(cls) if f.name in flat})
            for name, cls in GROUPS.items()
            if name != "provenance"
        }
        errors = [e for e in str(flat.get("errors") or "").split("; ") if e]
        if i == 0:
            errors = ["income: kein Periodenende", "fx; mit Semikolon im Text"]
        result.append(
            Fundamentals(
                **groups,
                provenance=Provenance(
                    fetched_at=FETCHED,
                    fiscal_period_end=date(2025, 12, 31),
                    statement_fx=1.0 if i % 2 else None,
                ),
                errors=errors,
            )
        )
    return result


def _nested(f: Fundamentals) -> dict[str, Any]:
    """Wie der Contract: alle Gruppen und Fehler, ohne Rohdaten."""
    data = asdict(f)
    data.pop("raw")
    return data


def _same(a: Any, b: Any) -> bool:
    missing = (a is None or (isinstance(a, float) and math.isnan(a))) and (
        b is None or (isinstance(b, float) and math.isnan(b))
    )
    return missing or a == b


class TestFundamentalsV1:
    def test_fields_match_the_dataclass(self):
        """Ein neues Feld in src.fundamentals ohne Contract faellt hier auf (und umgekehrt)."""
        top = {f.name for f in fields(Fundamentals)} - {"raw"}
        assert set(FundamentalsV1.model_fields) == top
        for name, cls in GROUPS.items():
            annotation = FundamentalsV1.model_fields[name].annotation
            assert isinstance(annotation, type)
            assert issubclass(annotation, BaseModel)
            assert set(annotation.model_fields) == {f.name for f in fields(cls)}, name

    def test_round_trip_with_the_golden_records(self):
        for f in _golden_fundamentals():
            v1 = FundamentalsV1.model_validate(_nested(f))
            assert v1.model_dump() == _nested(f)
            assert FundamentalsV1.model_validate_json(v1.model_dump_json()) == v1

    def test_flat_form_matches_the_dataframe_columns(self):
        """scoring und notification arbeiten flach - wie Fundamentals.to_flat_dict()."""
        for f in _golden_fundamentals():
            assert FundamentalsV1.model_validate(_nested(f)).to_flat() == f.to_flat_dict()

    def test_errors_survive_as_a_list(self):
        f = _golden_fundamentals()[0]
        v1 = FundamentalsV1.model_validate(_nested(f))
        assert v1.errors == ["income: kein Periodenende", "fx; mit Semikolon im Text"]

    @pytest.mark.parametrize("bad", [float("nan"), float("inf")])
    def test_non_finite_numbers_are_rejected(self, bad):
        """Fehlt ein Wert, steht im Contract None - NaN und inf sind kein gueltiges JSON."""
        data = _nested(_golden_fundamentals()[1])
        data["market"]["price"] = bad
        with pytest.raises(ValidationError):
            FundamentalsV1.model_validate(data)

    def test_fetched_at_needs_a_timezone(self):
        data = _nested(_golden_fundamentals()[1])
        data["provenance"]["fetched_at"] = datetime(2026, 10, 17, 5, 30)
        with pytest.raises(ValidationError):
            FundamentalsV1.model_validate(data)


def _ranking_rows() -> tuple[pd.DataFrame, list[RankingRowV1]]:
    """Golden-Datensatz durch score(), dann je Zeile ein RankingRowV1."""
    funds = _golden_fundamentals()
    contracts = {f.symbol: FundamentalsV1.model_validate(_nested(f)) for f in funds}
    scored = score(pd.DataFrame([f.to_flat_dict() for f in funds]))
    rows = []
    for rec in scored.to_dict("records"):
        factor_ranks = {
            col.removeprefix("rank_"): None if pd.isna(rec[col]) else float(rec[col])
            for col in scored.columns
            if col.startswith("rank_") and col != "rank_overall"
        }
        rows.append(
            RankingRowV1(
                fundamentals=contracts[rec["symbol"]],
                rank_overall=int(rec["rank_overall"]),
                value_score=None if pd.isna(rec["value_score"]) else rec["value_score"],
                quality_score=None if pd.isna(rec["quality_score"]) else rec["quality_score"],
                composite_score=None if pd.isna(rec["composite_score"]) else rec["composite_score"],
                value_trap_flag=bool(rec["value_trap_flag"]),
                factor_ranks=factor_ranks,
            )
        )
    return scored, rows


class TestRankingRowV1:
    def test_flat_form_matches_the_scored_frame(self):
        scored, rows = _ranking_rows()
        assert len(rows) == len(scored) > 0
        for rec, row in zip(scored.to_dict("records"), rows, strict=True):
            flat = row.to_flat()
            for col in scored.columns:
                assert _same(flat[col], rec[col]), (rec["symbol"], col, flat[col], rec[col])

    def test_round_trip_as_json(self):
        _, rows = _ranking_rows()
        for row in rows:
            assert RankingRowV1.model_validate_json(row.model_dump_json()) == row

    def test_rank_starts_at_one(self):
        _, rows = _ranking_rows()
        with pytest.raises(ValidationError):
            RankingRowV1.model_validate({**rows[0].model_dump(), "rank_overall": 0})


def _examples() -> dict[str, BaseModel]:
    """Je Event ein vollstaendig befuelltes Beispiel."""
    funds = [FundamentalsV1.model_validate(_nested(f)) for f in _golden_fundamentals()[:2]]
    _, ranking = _ranking_rows()
    return {
        RUN_REQUESTED.type: ScreeningRunRequestedV1(
            run_id=42, trigger="scheduled", force_refresh=True, dry_run=False, notify=True
        ),
        FETCH_PROGRESSED.type: FetchProgressedV1(
            run_id=42, done=57, total=90, symbol="SAP.DE", ok=True
        ),
        SNAPSHOT_COMPLETED.type: SnapshotCompletedV1(
            run_id=42,
            fetch_run_id=7,
            as_of=date(2026, 10, 17),
            success_share=0.97,
            universe_source="iShares",
            fundamentals=funds,
        ),
        SCORING_RUN_COMPLETED.type: ScoringRunCompletedV1(
            run_id=None,
            scoring_run_id=3,
            trigger="rescore",
            profile=ProfileRefV1(profile_id=1, version=2),
            ranking=ranking[:3],
        ),
        PROFILE_SAVED.type: ProfileSavedV1(profile_id=1, version=3),
        PROFILE_ACTIVATED.type: ProfileActivatedV1(profile_id=1, version=3),
        REPORT_SENT.type: ReportSentV1(
            run_id=42, report_id=9, subject="[Value-Screening] Top: Value Co", dry_run=True
        ),
        RUN_FAILED.type: RunFailedV1(run_id=42, stage="market-data", reason="timeout"),
    }


class TestEventCatalog:
    def test_catalog_matches_events_md(self):
        assert set(EVENTS) == {
            "screening.run.requested",
            "marketdata.fetch.progressed",
            "marketdata.snapshot.completed",
            "scoring.run.completed",
            "scoring.profile.saved",
            "scoring.profile.activated",
            "notification.report.sent",
            "screening.run.failed",
        }
        for event_type, spec in EVENTS.items():
            assert spec.type == event_type
            assert spec.dataschema == f"va-contracts/{event_type}/v1"

    def test_only_progress_is_volatile(self):
        """Fluechtige Meldungen liegen ausserhalb von va.>, sonst speichert JetStream sie."""
        for spec in EVENTS.values():
            expected = f"live.va.{spec.type}" if spec is FETCH_PROGRESSED else f"va.{spec.type}"
            assert spec.subject == expected

    def test_every_event_has_an_example_and_survives_json(self):
        examples = _examples()
        assert set(examples) == set(EVENTS)
        for event_type, payload in examples.items():
            model = EVENTS[event_type].model
            assert isinstance(payload, model)
            assert model.model_validate_json(payload.model_dump_json()) == payload

    def test_unknown_fields_are_ignored(self):
        """Additive Aenderungen: Ein aelterer Empfaenger versteht ein neueres Event."""
        newer = {**_examples()[RUN_FAILED.type].model_dump(), "retry_in": 60}
        assert RunFailedV1.model_validate(newer) == _examples()[RUN_FAILED.type]

    def test_events_are_immutable(self):
        with pytest.raises(ValidationError):
            _examples()[RUN_FAILED.type].reason = "anders"  # type: ignore[misc]

    @pytest.mark.parametrize(
        ("model", "data"),
        [
            (ScreeningRunRequestedV1, {"run_id": 1, "trigger": "rescore"}),
            (ScoringRunCompletedV1, {"run_id": 1, "scoring_run_id": 2, "trigger": "weekly"}),
            (RunFailedV1, {"run_id": 1, "stage": "irgendwo", "reason": "x"}),
            (FetchProgressedV1, {"run_id": 1, "done": 91, "total": 90, "symbol": "X", "ok": 1}),
        ],
    )
    def test_invalid_values_are_rejected(self, model, data):
        with pytest.raises(ValidationError):
            model.model_validate(data)

    def test_run_request_defaults(self):
        request = ScreeningRunRequestedV1(run_id=1, trigger="manual")
        assert (request.force_refresh, request.dry_run, request.notify) == (False, False, True)


class TestEnvelope:
    def test_new_envelope_fills_the_cloudevents_fields(self):
        payload = _examples()[SCORING_RUN_COMPLETED.type]
        cause = uuid4()
        env = new_envelope(
            SCORING_RUN_COMPLETED,
            payload,
            source="va/scoring",
            correlationid="42",
            causationid=cause,
        )
        assert env.specversion == "1.0"
        assert env.id.version == 7
        assert env.type == "scoring.run.completed"
        assert env.dataschema == "va-contracts/scoring.run.completed/v1"
        assert env.time.tzinfo is not None
        assert (env.source, env.correlationid, env.causationid) == ("va/scoring", "42", cause)
        assert env.data is payload

    def test_round_trip_as_json(self):
        env = new_envelope(SNAPSHOT_COMPLETED, _examples()[SNAPSHOT_COMPLETED.type], source="va/md")
        restored = Envelope[SnapshotCompletedV1].model_validate_json(env.model_dump_json())
        assert restored == env

    def test_ids_are_time_ordered(self):
        payload = _examples()[RUN_FAILED.type]
        first = new_envelope(RUN_FAILED, payload, source="va/web-api")
        second = new_envelope(RUN_FAILED, payload, source="va/web-api")
        assert second.id > first.id

    def test_payload_must_match_the_event(self):
        with pytest.raises(TypeError):
            new_envelope(RUN_FAILED, _examples()[REPORT_SENT.type], source="va/notification")


class TestJsonSchemas:
    """Jede Aenderung an einem Contract wird im Diff sichtbar (tests/golden/contracts/v1)."""

    @pytest.mark.parametrize("event_type", sorted(EVENTS))
    def test_payload_schema(self, golden, event_type):
        schema = EVENTS[event_type].model.model_json_schema()
        golden(f"contracts/v1/{event_type}.schema.json", _schema_bytes(schema))

    def test_envelope_schema(self, golden):
        schema = Envelope[dict[str, Any]].model_json_schema()
        golden("contracts/v1/envelope.schema.json", _schema_bytes(schema))


def _schema_bytes(schema: dict[str, Any]) -> bytes:
    return (json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode()
