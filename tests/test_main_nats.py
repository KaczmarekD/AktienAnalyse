"""Der Batch mit ``EVENT_BUS=nats`` (P4.3): dieselbe Kette, nur ueber NATS JetStream.

Die Fakes und Helfer kommen aus ``tests/test_main.py``. Ueber NATS kehrt ``publish`` sofort
zurueck, der Batch wartet deshalb auf das Ergebnis des ``RunTracker``. Ohne ``TEST_NATS_URL``
uebersprungen.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from tests import test_main as base
from va_market_data.domain.universe import Ticker
from va_notification.domain.errors import ERROR_SUBJECT

TICKERS = [
    Ticker("VAL.DE", "Value Co", "DAX"),
    Ticker("QUAL.DE", "Quality Co", "DAX"),
    Ticker("TRAP.DE", "Trap Co", "MDAX"),
    Ticker("MID.DE", "Mid Co", "MDAX"),
    Ticker("OK.DE", "OK Co", "DAX"),
    Ticker("LEV.DE", "Leverage Co", "MDAX"),
    Ticker("LOSS.DE", "Loss Co", "MDAX"),
]


@pytest.fixture
def nats_settings(settings, nats_url):
    return settings.model_copy(
        update={"event_bus": "nats", "nats_url": nats_url, "run_timeout_minutes": 1.0}
    )


def _run(settings, mock_universe_df, **kwargs: Any):
    recorder = base.FakeRecorder()
    rc, adapters, _ = base._run_with(
        settings, recorder, TICKERS, {"return_value": mock_universe_df}, **kwargs
    )
    return rc, recorder, adapters


def test_same_result_as_in_process(settings, nats_settings, mock_universe_df):
    rc_local, local, local_adapters = _run(settings, mock_universe_df)
    rc_nats, remote, remote_adapters = _run(nats_settings, mock_universe_df)

    assert rc_nats == rc_local == 0
    assert remote.get("finish_run") == local.get("finish_run")
    assert remote.get("finish_run")[0]["status"] in {"success", "partial"}
    mails = base._mails(remote_adapters)
    assert len(mails) == 1  # genau eine Mail, keine Fehlermail
    assert mails[0].args[0] == base._mails(local_adapters)[0].args[0]
    assert base._pings(remote_adapters)[-1].args[0] is True


def test_dead_letter_fails_the_run_with_alarm(nats_settings, mock_universe_df):
    with patch(
        "va_scoring.entrypoints.handlers.SnapshotCompletedHandler.__call__",
        side_effect=RuntimeError("Bug im Handler"),
    ):
        rc, recorder, adapters = _run(nats_settings, mock_universe_df)
    assert rc == 1
    finish = recorder.get("finish_run")[0]
    assert finish["status"] == "failed"
    assert "scoring" in finish["error"]
    assert "Bug im Handler" in finish["error"]
    assert base._pings(adapters)[-1].args[0] is False
    assert len(base._mails(adapters, ERROR_SUBJECT)) == 1


def test_no_outcome_within_the_timeout(nats_settings, mock_universe_df):
    quick = nats_settings.model_copy(update={"run_timeout_minutes": 0.02})
    with patch("src.main.wire"):  # niemand reagiert auf den Start
        rc, recorder, adapters = _run(quick, mock_universe_df)
    assert rc == 1
    finish = recorder.get("finish_run")[0]
    assert (finish["status"], finish["error"]) == ("failed", "Lauf ohne Ergebnis")
    assert len(base._mails(adapters, ERROR_SUBJECT)) == 1
