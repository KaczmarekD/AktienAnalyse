"""Ende-zu-Ende ueber den Bus: Der eingefrorene Golden-Datensatz ergibt die Golden-Mail (P1.8).

Universum, Abruf, Speicher, Versand und Heartbeat sind Fakes; Handler, Contracts und der Bus
sind echt: im Prozess und, mit ``TEST_NATS_URL``, ueber NATS JetStream (P4.3). Jede Stufe sieht nur die Events der vorherigen - die Daten
gehen also zweimal ueber JSON (Snapshot und Ranking).

Verglichen wird mit ``mail_deka.html``, weil der Fall ohne Zu- und Abgaenge auskommt (die
anderen Golden-Faelle tragen fertige Texte statt Titeln). Die CSV hat hier mehr Spalten als
``ranking.csv``: Der eingefrorene Datensatz kennt nicht alle Felder, das Event fuehrt sie
leer mit, wie es jeder echte Abruf ohnehin tut. Aus demselben Grund stehen ganzzahlige Kurse
des Datensatzes dort als Gleitkommazahl.
"""

from __future__ import annotations

import io
import json
from collections.abc import Callable, Iterator
from datetime import datetime

import pandas as pd
import pytest

from src.composition import Adapters, wire
from tests.conftest import GOLDEN_DIR
from va_contracts import new_envelope
from va_contracts.events.v1 import (
    REPORT_SENT,
    RUN_FAILED,
    RUN_REQUESTED,
    RunOptionsV1,
    ScreeningRunRequestedV1,
)
from va_market_data.domain.universe import Ticker, Universe
from va_platform.bus import EventBus, InProcessBus
from va_scoring.domain.profile import ProfileVersionRef

FIXED_NOW = datetime(2026, 10, 3, 7, 30)
RECORDS = json.loads((GOLDEN_DIR / "input_fundamentals.json").read_text(encoding="utf-8"))


class Store:
    """Alle Speicher-Ports zugleich, ohne Datenbank."""

    def instrument_ids(self, symbols):
        """P5.3: IDs der Titel fuer das Snapshot-Event."""
        return {s: i for i, s in enumerate(sorted(symbols), start=1)}

    def find_reusable_fetch(self, day, symbols):
        return None

    def start_fetch(self, tickers, source, as_of=None):
        return 10

    def history_state(self, symbols):
        return {}

    def record_fundamentals(self, fetch_run_id, fund):
        pass

    def finish_fetch(self, fetch_run_id, df):
        pass

    def load_snapshots(self, fetch_run_id, symbols):
        raise AssertionError("kein wiederverwendeter Abruf erwartet")

    def ensure_default_profile(self, params):
        return ProfileVersionRef(1, "Standard", 1, dict(params))

    def record_scoring(self, fetch_run_id, df_all, scored, cfg, profile=None, instrument_ids=None):
        return 20

    def record_report(self, run_id, scoring_run_id, report):
        return 30

    def record_delivery(self, **kwargs):
        pass

    def delivered_report(self, scoring_run_id):
        return None

    def start_run(self, **kwargs):
        return 1

    def finish_run(self, run_id, **kwargs):
        pass

    def record_logs(self, run_id, entries):
        pass


class Sender:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str, tuple[str, bytes] | None]] = []

    def send(self, subject, html_body, attachment=None):
        self.sent.append((subject, html_body, attachment))


class NoHeartbeat:
    def ping(self, success: bool, message: str | None = None) -> bool | None:
        return None


def _fetch(tickers, *, on_result, history):
    return pd.DataFrame(RECORDS)


@pytest.fixture(params=["in_process", "nats"])
def chain(request) -> Iterator[tuple[EventBus, Callable[[], None]]]:
    """Der Bus der Kette und wie man auf ihr Ende wartet (im Prozess: gar nicht)."""
    if request.param == "in_process":
        yield InProcessBus(max_deliver=1), lambda: None
        return
    from va_platform.nats import NatsBus

    bus = NatsBus(request.getfixturevalue("nats_url"), max_deliver=1)
    bus.start()
    try:
        yield bus, lambda: bus.settle(timeout=60)
    finally:
        bus.close()


def _run(settings, chain: tuple[EventBus, Callable[[], None]]) -> tuple[Sender, list[str]]:
    store, sender = Store(), Sender()
    adapters = Adapters(
        batch=store,
        market_data=store,
        scoring=store,
        reporting=store,
        load_universe=lambda: Universe(
            [Ticker(r["symbol"], r["name"], r["index"]) for r in RECORDS], source="Deka"
        ),
        fetch=_fetch,
        sender=sender,
        heartbeat=NoHeartbeat(),
        clock=lambda: FIXED_NOW,
    )
    bus, settle = chain
    settings = settings.model_copy(update={"top_n": 5, "bottom_n": 3})
    wire(bus, adapters, settings, version="0.0.0-golden")
    ends: list[str] = []
    bus.subscribe(REPORT_SENT, "probe-sent", lambda env: ends.append(env.type))
    bus.subscribe(RUN_FAILED, "probe-failed", lambda env: ends.append(env.data.reason))
    request = ScreeningRunRequestedV1(run_id=1, trigger="scheduled", options=RunOptionsV1())
    bus.publish(new_envelope(RUN_REQUESTED, request, source="va/test", correlationid="1"))
    settle()
    return sender, ends


def _csv(raw: bytes) -> pd.DataFrame:
    return pd.read_csv(io.BytesIO(raw), sep=";", decimal=",", encoding="utf-8-sig")


def test_golden_mail_through_the_bus(settings, chain):
    sender, ends = _run(settings, chain)
    assert ends == [REPORT_SENT.type]
    assert len(sender.sent) == 1
    subject, html, attachment = sender.sent[0]
    assert attachment is not None
    filename, csv_bytes = attachment

    assert html.encode("utf-8") == (GOLDEN_DIR / "mail_deka.html").read_bytes()
    meta = json.loads((GOLDEN_DIR / "mail_meta.json").read_text(encoding="utf-8"))
    assert (subject, filename) == (meta["subject"], meta["csv_filename"])

    golden = _csv((GOLDEN_DIR / "ranking.csv").read_bytes())
    actual = _csv(csv_bytes)
    assert list(golden.columns) == [c for c in actual.columns if c in golden.columns]
    extra = set(actual.columns) - set(golden.columns)
    assert extra, "erwartet: Felder, die der eingefrorene Datensatz nicht kennt"
    assert not extra & set().union(*RECORDS)
    assert actual[sorted(extra)].isna().all().all()
    pd.testing.assert_frame_equal(
        actual[golden.columns],
        golden,
        check_dtype=False,  # Kurse: im Datensatz ganzzahlig, im Contract float (42 -> 42,0)
        check_exact=False,
        rtol=1e-12,
        atol=0.0,
    )
