"""Tracing mit OpenTelemetry (P5.5): ein Trace je Run, ueber Publish und Consume hinweg.

- ``run_span``: der Wurzel-Span eines Runs, wo er entsteht (web-api, Batch).
- ``stamp``: setzt den Trace-Kontext des aktuellen Spans als ``traceparent`` in die Huelle.
  Die Busse und die Outbox rufen es beim Senden auf.
- ``consuming``: ein Span je verarbeitetem Event, Vorgaenger ist der ``traceparent`` der Huelle.
  Attribute: Consumer, Event-Typ, Event-ID und Run-ID (``correlationid``).

Ohne Provider sind alle Spans leer und die Huelle bleibt unveraendert. ``configure`` richtet
ihn je Prozess ein, wenn ``OTEL_TRACES_EXPORTER`` (Settings) nicht ``none`` ist: Mit ``console``
gehen die Spans als JSON ins Log des Containers. Die run_id steht als ``va.run_id`` an jedem Span.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, Literal

from opentelemetry import trace
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

if TYPE_CHECKING:
    from collections.abc import Iterator

    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.trace import Span

    from va_contracts import Envelope

type Exporter = Literal["none", "console"]

_PROPAGATOR = TraceContextTextMapPropagator()
_provider: TracerProvider | None = None


def set_provider(provider: TracerProvider | None) -> None:
    """Der Provider dieses Prozesses (Tests setzen einen mit In-Memory-Exporter)."""
    global _provider  # noqa: PLW0603 - einer je Prozess
    _provider = provider


def configure(service: str, exporter: Exporter) -> None:
    """Richtet Tracing fuer ``service`` ein; mit ``none`` oder schon gesetztem Provider nicht."""
    if exporter == "none" or _provider is not None:
        return
    from opentelemetry.sdk.resources import Resource  # noqa: PLC0415 - nur beim Start
    from opentelemetry.sdk.trace import TracerProvider  # noqa: PLC0415
    from opentelemetry.sdk.trace.export import (  # noqa: PLC0415
        BatchSpanProcessor,
        ConsoleSpanExporter,
    )

    provider = TracerProvider(resource=Resource.create({"service.name": service}))
    provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
    set_provider(provider)


def _tracer() -> trace.Tracer:
    return trace.get_tracer("va", tracer_provider=_provider or trace.NoOpTracerProvider())


@contextmanager
def run_span(run_id: int) -> Iterator[Span]:
    """Wurzel-Span eines Runs: beginnt immer einen neuen Trace, auch in einem anderen Span."""
    root = trace.set_span_in_context(trace.INVALID_SPAN)
    with _tracer().start_as_current_span("run", context=root) as span:
        span.set_attribute("va.run_id", str(run_id))
        yield span


def stamp[E: Envelope[Any]](envelope: E) -> E:
    """Die Huelle mit dem Trace-Kontext des aktuellen Spans; ohne Span unveraendert."""
    if envelope.traceparent is not None:
        return envelope
    carrier: dict[str, str] = {}
    _PROPAGATOR.inject(carrier)
    traceparent = carrier.get("traceparent")
    if traceparent is None:
        return envelope
    return envelope.model_copy(update={"traceparent": traceparent})


@contextmanager
def consuming(envelope: Envelope[Any], consumer: str) -> Iterator[Span]:
    """Ein Span fuer das Verarbeiten von ``envelope`` durch ``consumer``."""
    carrier = {"traceparent": envelope.traceparent} if envelope.traceparent else {}
    parent = _PROPAGATOR.extract(carrier)
    attributes = {
        "va.consumer": consumer,
        "va.event_type": envelope.type,
        "va.event_id": str(envelope.id),
    }
    if envelope.correlationid:
        attributes["va.run_id"] = envelope.correlationid
    with _tracer().start_as_current_span(
        f"{consumer} {envelope.type}",
        context=parent,
        kind=trace.SpanKind.CONSUMER,
        attributes=attributes,
    ) as span:
        yield span
