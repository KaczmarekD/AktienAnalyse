"""Konsens-Snapshots (ADR-0010, Paket F1.1): Umwandlung und Fehlertoleranz ohne Netz.

Die Fixtures unter ``tests/fixtures/consensus/`` sind echte yfinance-Antworten
(aufgezeichnet am 30.09.2026 mit yfinance 0.2.66).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

from src.consensus import CONSENSUS_KINDS, ConsensusEntry, collect_consensus, to_payload

FIXTURES = Path(__file__).parent / "fixtures" / "consensus"


def recorded(symbol: str) -> dict[str, Any]:
    """Aufgezeichnete Antworten wieder in DataFrames bzw. Dicts verwandeln."""
    doc = json.loads((FIXTURES / f"{symbol}.json").read_text(encoding="utf-8"))
    out: dict[str, Any] = {}
    for kind, resp in doc["responses"].items():
        if resp["type"] == "frame":
            out[kind] = pd.DataFrame(resp["data"], index=resp["index"], columns=resp["columns"])
        else:
            out[kind] = resp["value"]
    return out


class TestToPayload:
    def test_frame_becomes_rows_by_period(self):
        payload = to_payload(recorded("KGX.DE")["eps_trend"])
        assert set(payload) == {"0q", "+1q", "0y", "+1y"}
        assert payload["+1y"]["current"] == pytest.approx(4.548)
        assert payload["+1y"]["90daysAgo"] == pytest.approx(4.71843)

    def test_missing_values_become_null(self):
        payload = to_payload(recorded("KGX.DE")["growth_estimates"])
        assert payload["LTG"]["stockTrend"] is None
        assert payload["LTG"]["indexTrend"] == pytest.approx(0.122)

    @pytest.mark.parametrize("symbol", ["SAP.DE", "KGX.DE"])
    def test_every_recorded_kind_is_plain_json(self, symbol):
        responses = recorded(symbol)
        assert set(responses) == set(CONSENSUS_KINDS)
        for kind in CONSENSUS_KINDS:
            payload = to_payload(responses[kind])
            assert payload, kind
            json.dumps(payload, allow_nan=False)  # NaN oder numpy-Typen wuerden hier scheitern

    def test_numpy_scalars_in_dict_become_python(self):
        payload = to_payload({"mean": np.float64(57.9), "high": np.nan, "n": np.int64(15)})
        assert payload == {"mean": 57.9, "high": None, "n": 15}
        assert type(payload["n"]) is int

    @pytest.mark.parametrize("empty", [None, pd.DataFrame(), {}])
    def test_empty_response_has_no_payload(self, empty):
        assert to_payload(empty) is None

    def test_duplicate_row_labels_keep_all_rows(self):
        frame = pd.DataFrame({"avg": [1.0, 2.0]}, index=["0y", "0y"])
        assert to_payload(frame) == {
            "index": ["0y", "0y"],
            "columns": ["avg"],
            "data": [[1.0], [2.0]],
        }


class TestCollectConsensus:
    def test_recorded_responses_are_ok(self):
        responses = recorded("SAP.DE")
        entries = collect_consensus({k: (lambda v=v: v) for k, v in responses.items()})
        assert set(entries) == set(CONSENSUS_KINDS)
        assert all(e.status == "ok" and e.error is None for e in entries.values())
        assert entries["analyst_price_targets"].payload["mean"] > 0

    def test_empty_response_is_recorded_as_empty(self):
        entries = collect_consensus({"eps_trend": pd.DataFrame})
        assert entries["eps_trend"] == ConsensusEntry(status="empty", payload=None, error=None)

    def test_failure_is_recorded_not_raised(self):
        def rate_limited() -> Any:
            msg = "Too Many Requests"
            raise RuntimeError(msg)

        entries = collect_consensus(
            {"eps_trend": rate_limited, "analyst_price_targets": lambda: {"mean": 1.0}}
        )
        failed = entries["eps_trend"]
        assert failed.status == "error"
        assert failed.payload is None
        assert failed.error is not None
        assert "RuntimeError" in failed.error
        assert "Too Many Requests" in failed.error
        assert entries["analyst_price_targets"].status == "ok"

    def test_long_error_text_is_shortened(self):
        def noisy() -> Any:
            raise ValueError("x" * 5_000)

        error = collect_consensus({"eps_trend": noisy})["eps_trend"].error
        assert error is not None
        assert len(error) <= 500
