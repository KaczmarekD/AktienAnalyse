"""Tracing (P5.5): Ein Run ergibt einen zusammenhaengenden Trace ueber Publish und Consume.

Der Trace-Kontext reist als ``traceparent`` in der Huelle (CloudEvents-Erweiterung fuer verteiltes
Tracing), durch den Bus im Prozess, ueber NATS und durch die Outbox. Jedes Verarbeiten eines
Events ist ein Span mit Consumer, Event-Typ und Run-ID; sein Vorgaenger ist der Span, in dem das
Event entstand. Geprueft mit dem In-Memory-Exporter von OpenTelemetry. Die NATS-Variante braucht
``TEST_NATS_URL``.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING, Any

import pytest
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from pydantic import SecretStr

from tests import test_main as base
from tests.test_main_nats import TICKERS
from va_contracts import new_envelope, parse_envelope
from va_contracts.events.v1 import RUN_REQUESTED, RunOptionsV1, ScreeningRunRequestedV1
from va_platform import tracing
from va_platform.service import ServiceSettings
from va_web_api.settings import WebApiSettings

if TYPE_CHECKING:
    from opentelemetry.trace import SpanContext

CHAIN = [
    ("market-data", "screening.run.requested"),
    ("scoring", "marketdata.snapshot.completed"),
    ("notification", "scoring.run.completed"),
]


@pytest.fixture
def spans() -> Iterator[InMemorySpanExporter]:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracing.set_provider(provider)
    try:
        yield exporter
    finally:
        tracing.set_provider(None)


def _run(settings: Any, mock_universe_df: Any) -> int:
    rc, _, _ = base._run_with(
        settings, base.FakeRecorder(), TICKERS, {"return_value": mock_universe_df}
    )
    return rc


def _consumed(spans: list[ReadableSpan]) -> dict[tuple[str, str], ReadableSpan]:
    return {
        (str(s.attributes["va.consumer"]), str(s.attributes["va.event_type"])): s
        for s in spans
        if s.attributes and "va.consumer" in s.attributes
    }


def _assert_one_trace(spans: list[ReadableSpan]) -> None:
    consumed = _consumed(spans)
    for key in CHAIN:
        assert key in consumed, f"kein Span fuer {key}"
    [root] = [s for s in spans if s.name == "run"]
    assert root.attributes is not None
    run_id = root.attributes["va.run_id"]
    # Ein Trace fuer den ganzen Lauf, jeder Span mit der Run-ID
    assert {_context(s).trace_id for s in spans} == {_context(root).trace_id}
    for key in CHAIN:
        assert consumed[key].attributes["va.run_id"] == run_id  # type: ignore[index]
    # Die Kette: Jede Stufe haengt an der, die ihr Event veroeffentlicht hat
    previous = root
    for key in CHAIN:
        span = consumed[key]
        assert span.parent is not None
        assert span.parent.span_id == _context(previous).span_id, key
        previous = span


def _context(span: ReadableSpan) -> SpanContext:
    assert span.context is not None
    return span.context


def test_a_run_in_process_is_one_trace(spans, settings, mock_universe_df):
    assert _run(settings, mock_universe_df) == 0
    _assert_one_trace(list(spans.get_finished_spans()))


def test_a_run_over_nats_is_one_trace(spans, settings, nats_url, mock_universe_df):
    nats = settings.model_copy(
        update={"event_bus": "nats", "nats_url": nats_url, "run_timeout_minutes": 1.0}
    )
    assert _run(nats, mock_universe_df) == 0
    _assert_one_trace(list(spans.get_finished_spans()))


def test_the_trace_context_travels_in_the_envelope(spans):
    data = ScreeningRunRequestedV1(run_id=1, trigger="manual", options=RunOptionsV1())
    with tracing.run_span(1):
        env = tracing.stamp(new_envelope(RUN_REQUESTED, data, source="va/test"))
    assert env.traceparent is not None
    assert env.traceparent.startswith("00-")
    again = parse_envelope(env.model_dump_json().encode())
    assert again.traceparent == env.traceparent


def test_without_tracing_nothing_changes():
    """Ohne Provider (Tests, Werkzeuge) bleibt die Huelle unveraendert."""
    data = ScreeningRunRequestedV1(run_id=1, trigger="manual", options=RunOptionsV1())
    env = new_envelope(RUN_REQUESTED, data, source="va/test")
    with tracing.run_span(1):
        assert tracing.stamp(env).traceparent is None


def test_tracing_is_off_by_default(monkeypatch):
    """Standard ``none``: kein Provider. ``console`` richtet einen ein, je Prozess einmal."""
    url = SecretStr("postgresql+psycopg://x@y/z")
    monkeypatch.delenv("OTEL_TRACES_EXPORTER", raising=False)
    assert WebApiSettings(database_url=url).otel_traces_exporter == "none"
    monkeypatch.setenv("OTEL_TRACES_EXPORTER", "console")
    assert ServiceSettings(database_url=url).otel_traces_exporter == "console"
    try:
        tracing.configure("va-test", "none")
        assert tracing._provider is None
        tracing.configure("va-test", "console")
        first = tracing._provider
        assert first is not None
        tracing.configure("va-test", "console")
        assert tracing._provider is first
    finally:
        tracing.set_provider(None)
