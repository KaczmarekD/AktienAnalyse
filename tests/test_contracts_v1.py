"""Contracts v1 (P1.2): Datenformate zwischen den Services, siehe docs/architecture/events.md.

Die Modelle liegen in ``va_contracts`` und duerfen den Altbestand ``src`` nicht kennen
(import-linter). Die Tests pruefen deshalb hier, dass sie zu ``src.fundamentals``, zur
Ausgabe von ``src.scoring.score`` und zu ``src.reporting.build_report`` passen - mit dem
eingefrorenen Golden-Datensatz.
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
from va_contracts import Contract, Envelope, UnknownEventError, new_envelope, parse_envelope
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
    RunOptionsV1,
    ScoringRunCompletedV1,
    ScreeningRunRequestedV1,
    SnapshotCompletedV1,
    UniverseInfoV1,
    UniverseMemberV1,
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
from src.reporting import build_report
from src.scoring import ScoringConfig, score

GOLDEN_DIR = Path(__file__).parent / "golden"
GOLDEN_INPUT = GOLDEN_DIR / "input_fundamentals.json"
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
    """Der eingefrorene Datensatz des Golden-Masters als Dataclasses, mit allen Feldern."""
    records = json.loads(GOLDEN_INPUT.read_text(encoding="utf-8"))
    result = []
    for i, flat in enumerate(records):
        groups = {
            name: cls(**{f.name: flat.get(f.name) for f in fields(cls) if f.name in flat})
            for name, cls in GROUPS.items()
            if name != "provenance"
        }
        # Felder, die der Golden-Input nicht kennt, sollen im Round-Trip nicht nur None sein
        groups["identity"].industry = f"Branche {i}"
        groups["identity"].financial_currency = "USD" if i % 3 == 0 else "EUR"
        if groups["market"].market_cap is not None:
            groups["market"].enterprise_value = groups["market"].market_cap * 1.1
            groups["market"].shares_outstanding = 1_000_000.0 + i
        errors = [e for e in str(flat.get("errors") or "").split("; ") if e]
        if i == 0:
            errors = ["income: kein Periodenende", "fx: Kurs fehlt"]
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


def _missing(value: Any) -> bool:
    return value is None or (isinstance(value, float) and math.isnan(value))


def _same(a: Any, b: Any) -> bool:
    return (_missing(a) and _missing(b)) or a == b


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

    def test_back_from_the_flat_form(self):
        for f in _golden_fundamentals():
            v1 = FundamentalsV1.model_validate(_nested(f))
            assert FundamentalsV1.from_flat(v1.to_flat()) == v1

    def test_back_from_a_dataframe_row_with_nan(self):
        """z. B. ein wiederverwendeter Snapshot aus der DB: pandas liefert NaN, nicht None."""
        frame = pd.DataFrame([f.to_flat_dict() for f in _golden_fundamentals()])
        frame.loc[0, ["sector", "price", "roic"]] = [float("nan"), float("nan"), float("nan")]
        row = frame.to_dict("records")[0]
        v1 = FundamentalsV1.from_flat(row)
        assert (v1.identity.sector, v1.market.price, v1.quality.roic) == (None, None, None)
        assert v1.errors == ["income: kein Periodenende", "fx: Kurs fehlt"]

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


def _scored(cfg: ScoringConfig | None = None) -> tuple[pd.DataFrame, list[RankingRowV1]]:
    """Golden-Datensatz durch score(), dann je Zeile ein RankingRowV1."""
    funds = _golden_fundamentals()
    contracts = {f.symbol: FundamentalsV1.model_validate(_nested(f)) for f in funds}
    scored = score(pd.DataFrame([f.to_flat_dict() for f in funds]), cfg)
    rows = [
        RankingRowV1.from_flat(rec, fundamentals=contracts[rec["symbol"]])
        for rec in scored.to_dict("records")
    ]
    return scored, rows


UNIVERSE = UniverseInfoV1(
    source="iShares",
    as_of=date(2026, 9, 29),
    size=8,
    added=[UniverseMemberV1(symbol="NEU.DE", name="Neu AG", index="MDAX")],
    removed=[UniverseMemberV1(symbol="ALT.DE", name="Alt AG", index="DAX")],
)


class TestRankingRowV1:
    def test_flat_form_matches_the_scored_frame(self):
        scored, rows = _scored()
        assert len(rows) == len(scored) > 0
        for rec, row in zip(scored.to_dict("records"), rows, strict=True):
            flat = row.to_flat()
            for col in scored.columns:
                assert _same(flat[col], rec[col]), (rec["symbol"], col, flat[col], rec[col])

    def test_from_flat_without_contract_uses_the_row(self):
        scored, rows = _scored()
        rec = scored.to_dict("records")[0]
        assert RankingRowV1.from_flat(rec) == rows[0]

    def test_round_trip_as_json(self):
        _, rows = _scored()
        for row in rows:
            assert RankingRowV1.model_validate_json(row.model_dump_json()) == row

    def test_rank_starts_at_one(self):
        _, rows = _scored()
        with pytest.raises(ValidationError):
            RankingRowV1.model_validate({**rows[0].model_dump(), "rank_overall": 0})

    def test_composite_slightly_above_one_does_not_stop_the_run(self):
        """Settings normiert Gewichte erst ab 1 % Abweichung: 0.6 + 0.409 bleibt stehen."""
        _, rows = _scored(ScoringConfig(value_weight=0.6, quality_weight=0.409))
        row = rows[0].model_copy(update={"composite_score": 1.0057})
        assert RankingRowV1.model_validate(row.model_dump()).composite_score == 1.0057


def _examples() -> dict[str, Contract]:
    """Je Event ein vollstaendig befuelltes Beispiel."""
    funds = [FundamentalsV1.model_validate(_nested(f)) for f in _golden_fundamentals()[:2]]
    _, ranking = _scored()
    options = RunOptionsV1(force_refresh=True, dry_run=True, notify=False)
    return {
        RUN_REQUESTED.type: ScreeningRunRequestedV1(
            run_id=42, trigger="scheduled", options=options
        ),
        FETCH_PROGRESSED.type: FetchProgressedV1(
            run_id=42, done=57, total=90, symbol="SAP.DE", ok=True
        ),
        SNAPSHOT_COMPLETED.type: SnapshotCompletedV1(
            run_id=42,
            trigger="scheduled",
            options=options,
            fetch_run_id=7,
            as_of=date(2026, 10, 17),
            success_share=0.97,
            universe=UNIVERSE,
            fundamentals=funds,
        ),
        SCORING_RUN_COMPLETED.type: ScoringRunCompletedV1(
            run_id=42,
            trigger="scheduled",
            options=options,
            scoring_run_id=3,
            fetch_run_id=7,
            as_of=date(2026, 10, 17),
            universe=UNIVERSE,
            value_weight=0.6,
            quality_weight=0.4,
            profile=ProfileRefV1(profile_id=1, version=2, name="Standard"),
            ranking=ranking[:3],
        ),
        PROFILE_SAVED.type: ProfileSavedV1(profile_id=1, version=3),
        PROFILE_ACTIVATED.type: ProfileActivatedV1(profile_id=1, version=3),
        REPORT_SENT.type: ReportSentV1(
            run_id=42, report_id=9, subject="[Value-Screening] Top: Value Co", dry_run=True
        ),
        RUN_FAILED.type: RunFailedV1(
            run_id=42, trigger="manual", options=options, stage="market-data", reason="timeout"
        ),
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
            # CloudEvents 1.0: dataschema ist eine absolute URI
            assert spec.dataschema == f"urn:va-contracts:{event_type}:v1"

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
            _examples()[RUN_FAILED.type].reason = "anders"  # type: ignore[attr-defined]

    @pytest.mark.parametrize(
        ("model", "data"),
        [
            (ScreeningRunRequestedV1, {"run_id": 1, "trigger": "rescore"}),
            (ScreeningRunRequestedV1, {"run_id": 0, "trigger": "manual"}),
            (FetchProgressedV1, {"run_id": 1, "done": 91, "total": 90, "symbol": "X", "ok": 1}),
            (ReportSentV1, {"run_id": -5, "report_id": 1, "subject": "x", "dry_run": False}),
        ],
    )
    def test_invalid_values_are_rejected(self, model, data):
        with pytest.raises(ValidationError):
            model.model_validate(data)

    def test_run_options_defaults(self):
        request = ScreeningRunRequestedV1(run_id=1, trigger="manual")
        assert request.options == RunOptionsV1(force_refresh=False, dry_run=False, notify=True)


class TestRunContext:
    """Trigger und Optionen reisen mit: notification muss Dry-Run, notify und den
    Healthcheck (nur bei scheduled) allein aus den Events entscheiden koennen."""

    def _scoring(self, **update: Any) -> dict[str, Any]:
        return {**_examples()[SCORING_RUN_COMPLETED.type].model_dump(), **update}

    def test_rescore_has_no_run(self):
        rescore = self._scoring(run_id=None, trigger="rescore")
        assert ScoringRunCompletedV1.model_validate(rescore).run_id is None

    def test_rescore_with_run_is_rejected(self):
        with pytest.raises(ValidationError):
            ScoringRunCompletedV1.model_validate(self._scoring(trigger="rescore"))

    def test_regular_run_needs_a_run_id(self):
        with pytest.raises(ValidationError):
            ScoringRunCompletedV1.model_validate(self._scoring(run_id=None))

    def test_failed_rescore_is_reportable(self):
        failed = RunFailedV1(
            run_id=None,
            trigger="rescore",
            options=RunOptionsV1(notify=False),
            stage="scoring",
            reason="no_data",
            scoring_run_id=5,
        )
        assert failed.run_id is None

    def test_ranking_must_not_be_empty(self):
        """Keine bewertbaren Daten ist ein run.failed mit reason=no_data, kein leeres Ranking."""
        with pytest.raises(ValidationError):
            ScoringRunCompletedV1.model_validate(self._scoring(ranking=[]))


def _label(member: UniverseMemberV1) -> str:
    """Wie main._ticker_label - Darstellung ist Sache von notification, nicht des Contracts."""
    return f"{member.name} ({member.symbol}, {member.index})"


class TestReportFromEvents:
    """notification rendert die Mail allein aus scoring.run.completed (Ziel von P1.6/P1.8)."""

    def test_golden_subject_is_reproducible(self):
        """8 Titel, 7 nach dem Groessenfilter: Der Betreff muss partial 7/8 melden."""
        scored, rows = _scored()
        event = ScoringRunCompletedV1(
            run_id=1,
            trigger="scheduled",
            options=RunOptionsV1(),
            scoring_run_id=1,
            fetch_run_id=1,
            as_of=date(2026, 9, 26),
            universe=UNIVERSE,
            value_weight=0.6,
            quality_weight=0.4,
            ranking=rows,
        )
        frame = pd.DataFrame([row.to_flat() for row in event.ranking])
        from_event = build_report(
            frame,
            value_weight=event.value_weight,
            quality_weight=event.quality_weight,
            universe_size=event.universe.size,
            universe_source=event.universe.source,
            universe_as_of=event.universe.as_of,
            universe_added=[_label(m) for m in event.universe.added],
            universe_removed=[_label(m) for m in event.universe.removed],
            now=datetime(2026, 9, 26, 7, 30),
        )
        direct = build_report(
            scored,
            universe_size=8,
            universe_source="iShares",
            universe_as_of=date(2026, 9, 29),
            universe_added=["Neu AG (NEU.DE, MDAX)"],
            universe_removed=["Alt AG (ALT.DE, DAX)"],
            now=datetime(2026, 9, 26, 7, 30),
        )
        assert "[partial 7/8]" in from_event.subject
        assert from_event.subject == direct.subject
        assert from_event.html == direct.html


class TestEnvelope:
    def test_new_envelope_fills_the_cloudevents_fields(self):
        payload = _examples()[SCORING_RUN_COMPLETED.type]
        assert isinstance(payload, ScoringRunCompletedV1)
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
        assert env.dataschema == "urn:va-contracts:scoring.run.completed:v1"
        assert env.time.tzinfo is not None
        assert (env.source, env.correlationid, env.causationid) == ("va/scoring", "42", cause)
        assert env.data is payload

    def test_round_trip_as_json(self):
        payload = _examples()[SNAPSHOT_COMPLETED.type]
        assert isinstance(payload, SnapshotCompletedV1)
        env = new_envelope(SNAPSHOT_COMPLETED, payload, source="va/market-data")
        restored = Envelope[SnapshotCompletedV1].model_validate_json(env.model_dump_json())
        assert restored == env

    def test_ids_are_time_ordered(self):
        payload = _examples()[RUN_FAILED.type]
        assert isinstance(payload, RunFailedV1)
        first = new_envelope(RUN_FAILED, payload, source="va/web-api")
        second = new_envelope(RUN_FAILED, payload, source="va/web-api")
        assert second.id > first.id

    def test_payload_must_match_the_event(self):
        with pytest.raises(TypeError):
            new_envelope(RUN_FAILED, _examples()[REPORT_SENT.type], source="va/notification")  # type: ignore[arg-type]

    def test_type_must_match_the_payload(self):
        env = new_envelope(RUN_FAILED, _examples()[RUN_FAILED.type], source="va/web-api")  # type: ignore[arg-type]
        data = {**env.model_dump(), "type": "scoring.run.completed"}
        with pytest.raises(ValidationError):
            Envelope[RunFailedV1].model_validate(data)


class TestReceivingSide:
    """Ein Empfaenger bekommt rohes JSON und waehlt das Modell ueber den Katalog."""

    @pytest.mark.parametrize("event_type", sorted(EVENTS))
    def test_raw_json_becomes_the_typed_event(self, event_type):
        spec = EVENTS[event_type]
        payload = _examples()[event_type]
        sent = new_envelope(spec, payload, source="va/test", correlationid="42")  # type: ignore[arg-type]
        received = parse_envelope(sent.model_dump_json())
        assert isinstance(received.data, spec.model)
        assert received == sent

    def test_unknown_event_is_rejected(self):
        sent = new_envelope(RUN_FAILED, _examples()[RUN_FAILED.type], source="va/web-api")  # type: ignore[arg-type]
        raw = json.loads(sent.model_dump_json())
        raw["dataschema"] = "urn:va-contracts:screening.run.failed:v9"
        with pytest.raises(UnknownEventError):
            parse_envelope(json.dumps(raw))


class TestJsonSchemas:
    """Jede Aenderung an einem Contract wird im Diff sichtbar (tests/golden/contracts/v1)."""

    @pytest.mark.parametrize("event_type", sorted(EVENTS))
    def test_payload_schema(self, golden, event_type):
        schema = EVENTS[event_type].model.model_json_schema()
        golden(f"contracts/v1/{event_type}.schema.json", _schema_bytes(schema))

    def test_envelope_schema(self, golden):
        schema = Envelope[dict[str, Any]].model_json_schema()
        golden("contracts/v1/envelope.schema.json", _schema_bytes(schema))

    def test_no_stale_schema_files(self):
        expected = {f"{t}.schema.json" for t in EVENTS} | {"envelope.schema.json"}
        actual = {p.name for p in (GOLDEN_DIR / "contracts" / "v1").iterdir()}
        assert actual == expected, f"Unerwartet: {actual - expected}, fehlt: {expected - actual}"


def _schema_bytes(schema: dict[str, Any]) -> bytes:
    return (json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode()
