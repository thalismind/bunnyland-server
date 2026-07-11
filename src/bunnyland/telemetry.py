"""OpenTelemetry wiring for the engine (metrics about the world, traces about actions).

Telemetry is **off by default** and is a hard no-op unless the optional ``otel`` extra is
installed *and* ``BUNNYLAND_OTEL_ENABLED`` is truthy. The hot paths (per-tick, per-command)
route through :func:`span` and the ``record_*`` helpers, which cost a single module-level
bool read and a shared singleton no-op context manager when disabled -- no allocation, no
clock reads, no provider lookups. There are three safe states:

1. extra absent -> ``_OTEL_AVAILABLE`` is ``False``; everything is a no-op.
2. extra present, gate off -> no providers are created; everything is a no-op.
3. extra present, gate on -> real providers + OTLP exporters; spans and metrics flow.

The exporter honours the standard ``OTEL_*`` environment variables (endpoint, protocol,
headers, service name, ...). We only default ``service.name`` to ``bunnyland`` when the
operator has not set ``OTEL_SERVICE_NAME``.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any

try:
    from opentelemetry import metrics as _otel_metrics
    from opentelemetry import trace as _otel_trace
    from opentelemetry.trace import Status as _OtelStatus
    from opentelemetry.trace import StatusCode as _OtelStatusCode

    _OTEL_AVAILABLE = True
except ImportError:  # the optional ``otel`` extra is not installed
    _otel_metrics = None
    _otel_trace = None
    _OtelStatus = None
    _OtelStatusCode = None
    _OTEL_AVAILABLE = False


_TRACER_NAME = "bunnyland"
_METER_NAME = "bunnyland"

# Module-level state. ``_ENABLED`` is the single hot-path gate.
_ENABLED = False
_initialized = False
_tracer: Any = None
_meter: Any = None
_instruments: _Instruments | None = None
_gauges_actor: Any = None


# -- no-op stubs (used when telemetry is disabled or the extra is absent) ----------------


class _NoOpSpan:
    """Stands in for an OTel span; every method is a no-op."""

    def set_attribute(self, *args: Any, **kwargs: Any) -> None:
        pass

    def record_exception(self, *args: Any, **kwargs: Any) -> None:
        pass

    def set_status(self, *args: Any, **kwargs: Any) -> None:
        pass


class _NoOpSpanCM:
    """A reusable context manager yielding the shared no-op span (no allocation)."""

    def __enter__(self) -> _NoOpSpan:
        return _NOOP_SPAN

    def __exit__(self, *exc: Any) -> bool:
        return False


_NOOP_SPAN = _NoOpSpan()
_NOOP_SPAN_CM = _NoOpSpanCM()


# -- instrument bundle -------------------------------------------------------------------

REJECT_CATEGORIES = (
    "insufficient_points",
    "stale_generation",
    "dead",
    "suspended",
    "downed",
    "asleep",
    "expired",
    "no_handler",
    "bad_target",
    "handler_rejected",
    "other",
)


def _reject_category(reason: str) -> str:
    """Bucket a free-text rejection reason into a fixed, low-cardinality category."""
    text = (reason or "").lower()
    if "insufficient" in text or "points" in text:
        return "insufficient_points"
    if "generation" in text:
        return "stale_generation"
    if "dead" in text:
        return "dead"
    if "suspend" in text:
        return "suspended"
    if "downed" in text:
        return "downed"
    if "asleep" in text or "sleeping" in text:
        return "asleep"
    if "expire" in text:
        return "expired"
    if "no handler" in text or "no_handler" in text:
        return "no_handler"
    if "unreachable" in text or "does not exist" in text or "not found" in text:
        return "bad_target"
    if "handler" in text or "rejected" in text:
        return "handler_rejected"
    return "other"


class _Instruments:
    """Concrete OTel instruments, built once when telemetry is enabled."""

    def __init__(self, meter: Any) -> None:
        self.tick_duration = meter.create_histogram(
            "bunnyland.tick.duration", unit="s", description="World tick wall-clock duration."
        )
        self.commands_submitted = meter.create_counter(
            "bunnyland.commands.submitted", description="Commands accepted into the queue."
        )
        self.commands_accepted = meter.create_counter(
            "bunnyland.commands.accepted", description="Commands that executed successfully."
        )
        self.commands_rejected = meter.create_counter(
            "bunnyland.commands.rejected", description="Commands rejected during a tick."
        )
        self.handler_duration = meter.create_histogram(
            "bunnyland.command.handler.duration",
            unit="s",
            description="Handler execution wall-clock duration.",
        )
        self.llm_decision_duration = meter.create_histogram(
            "bunnyland.llm.decision.duration",
            unit="s",
            description="Agent decision wall-clock duration.",
        )
        self.llm_tokens_prompt = meter.create_counter(
            "bunnyland.llm.tokens.prompt", description="Prompt tokens consumed by agents."
        )
        self.llm_tokens_completion = meter.create_counter(
            "bunnyland.llm.tokens.completion",
            description="Completion tokens produced by agents.",
        )
        self.llm_tokens_total = meter.create_counter(
            "bunnyland.llm.tokens.total",
            description="Total tokens consumed and produced by agents.",
        )
        self.llm_cost = meter.create_counter(
            "bunnyland.llm.cost",
            unit="USD",
            description="Provider-reported LLM cost.",
        )
        self.worldgen_duration = meter.create_histogram(
            "bunnyland.worldgen.duration",
            unit="s",
            description="World generation wall-clock duration.",
        )
        self.worldgen_request_duration = meter.create_histogram(
            "bunnyland.worldgen.request.duration",
            unit="s",
            description="Single worldgen LLM request wall-clock duration.",
        )
        self.persist_duration = meter.create_histogram(
            "bunnyland.world.persist.duration",
            unit="s",
            description="World save/load wall-clock duration.",
        )


# -- public surface ----------------------------------------------------------------------


def enabled() -> bool:
    """Return whether telemetry is active. The single hot-path gate."""
    return _ENABLED


def _enabled_from_env() -> bool:
    value = (os.environ.get("BUNNYLAND_OTEL_ENABLED") or "").strip().lower()
    return value in {"1", "true", "yes", "on"}


def init_telemetry(*, providers: tuple[Any, Any] | None = None) -> bool:
    """Set up tracing + metrics if enabled. Idempotent; returns whether telemetry is active.

    ``providers`` lets tests inject ``(TracerProvider, MeterProvider)`` wired to in-memory
    exporters instead of the real OTLP exporters. Production passes ``None``.
    """
    global _ENABLED, _initialized, _tracer, _meter, _instruments
    if _initialized:
        return _ENABLED
    _initialized = True
    if not _OTEL_AVAILABLE or not _enabled_from_env():
        return False

    if providers is None:
        tracer_provider, meter_provider = _build_otlp_providers()
        # Set the process-global providers so auto-instrumentation (FastAPI) shares them.
        _otel_trace.set_tracer_provider(tracer_provider)
        _otel_metrics.set_meter_provider(meter_provider)
    else:
        tracer_provider, meter_provider = providers

    # Read the tracer/meter straight from the providers (not the globals) so injected test
    # providers work without tripping OTel's set-global-provider-once guard.
    _tracer = tracer_provider.get_tracer(_TRACER_NAME)
    _meter = meter_provider.get_meter(_METER_NAME)
    _instruments = _Instruments(_meter)
    _ENABLED = True
    return True


def _build_otlp_providers() -> tuple[Any, Any]:
    from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor

    resource = Resource.create({"service.name": os.environ.get("OTEL_SERVICE_NAME", "bunnyland")})
    tracer_provider = TracerProvider(resource=resource)
    trace_file = (os.environ.get("BUNNYLAND_OTEL_TRACE_FILE") or "").strip()
    if trace_file:
        tracer_provider.add_span_processor(SimpleSpanProcessor(_JsonlSpanExporter(trace_file)))
    else:
        tracer_provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))

    # Honour the standard OTEL_METRICS_EXPORTER=none so a traces-only backend (e.g. Tempo)
    # is not flooded with metric exports it cannot store. Instruments still no-op safely.
    metrics_exporter = (os.environ.get("OTEL_METRICS_EXPORTER") or "").strip().lower()
    if metrics_exporter == "none" or (trace_file and not metrics_exporter):
        readers = []
    else:
        readers = [PeriodicExportingMetricReader(OTLPMetricExporter())]
    meter_provider = MeterProvider(resource=resource, metric_readers=readers)
    return tracer_provider, meter_provider


class _JsonlSpanExporter:
    """Write finished spans as newline-delimited JSON for release-test artifacts."""

    def __init__(self, path: str | Path) -> None:
        from opentelemetry.sdk.trace.export import SpanExportResult

        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._result_success = SpanExportResult.SUCCESS
        self._result_failure = SpanExportResult.FAILURE

    def export(self, spans: Any) -> Any:
        try:
            with self.path.open("a", encoding="utf-8") as handle:
                for span in spans:
                    handle.write(json.dumps(_span_to_json(span), default=str, sort_keys=True))
                    handle.write("\n")
            return self._result_success
        except OSError:
            return self._result_failure

    def shutdown(self) -> None:
        return None

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return True


def _hex_id(value: int, width: int) -> str:
    return f"{value:0{width}x}"


def _span_to_json(span: Any) -> dict[str, Any]:
    parent = getattr(span, "parent", None)
    context = span.context
    status = getattr(span, "status", None)
    return {
        "name": span.name,
        "trace_id": _hex_id(context.trace_id, 32),
        "span_id": _hex_id(context.span_id, 16),
        "parent_span_id": _hex_id(parent.span_id, 16) if parent else None,
        "start_time_unix_nano": span.start_time,
        "end_time_unix_nano": span.end_time,
        "attributes": dict(span.attributes or {}),
        "events": [
            {
                "name": event.name,
                "timestamp_unix_nano": event.timestamp,
                "attributes": dict(event.attributes or {}),
            }
            for event in span.events
        ],
        "status": {
            "code": str(getattr(status, "status_code", "")),
            "description": getattr(status, "description", None),
        },
        "resource": dict(getattr(span.resource, "attributes", {}) or {}),
    }


def register_world_gauges(actor: Any) -> None:
    """Register observable gauges that read live world counts on the export interval."""
    global _gauges_actor
    if not _ENABLED:
        return
    _gauges_actor = actor
    meter = _meter
    meter.create_observable_gauge(
        "bunnyland.world.entities",
        callbacks=[_observe_entities],
        description="Total ECS entities in the world.",
    )
    meter.create_observable_gauge(
        "bunnyland.world.characters",
        callbacks=[_observe_characters],
        description="Characters in the world.",
    )
    meter.create_observable_gauge(
        "bunnyland.world.rooms",
        callbacks=[_observe_rooms],
        description="Rooms in the world.",
    )


def _observe_entities(_options: Any) -> Iterator[Any]:
    yield from _observe(lambda world: len(list(world.query().execute_entities())))


def _observe_characters(_options: Any) -> Iterator[Any]:
    from .core.components import CharacterComponent

    yield from _observe(
        lambda world: len(list(world.query().with_all([CharacterComponent]).execute_entities()))
    )


def _observe_rooms(_options: Any) -> Iterator[Any]:
    from .core.components import RoomComponent

    yield from _observe(
        lambda world: len(list(world.query().with_all([RoomComponent]).execute_entities()))
    )


def _observe(count_fn: Any) -> Iterator[Any]:
    if _gauges_actor is None:
        return
    yield _otel_metrics.Observation(count_fn(_gauges_actor.world))


def span(name: str, attributes: dict[str, Any] | None = None) -> Any:
    """Return a span context manager. A shared singleton no-op when telemetry is disabled."""
    if not _ENABLED:
        return _NOOP_SPAN_CM
    return _tracer.start_as_current_span(name, attributes=attributes or {})


#: Upper bound on a single string span attribute (e.g. a rendered prompt). Keeps individual
#: spans from ballooning while still capturing enough to debug a decision.
MAX_ATTRIBUTE_CHARS = 8192


def attr_text(value: Any, *, limit: int = MAX_ATTRIBUTE_CHARS) -> str:
    """Coerce a value to a span-safe string, truncating very long text with a length hint."""
    text = value if isinstance(value, str) else str(value)
    if len(text) > limit:
        return f"{text[:limit]}... ({len(text)} chars total)"
    return text


def set_span_attributes(attributes: Mapping[str, Any]) -> None:
    """Set attributes on the currently active span. A no-op when telemetry is disabled.

    Lets nested code (e.g. command rejection deep inside ``_attempt``) annotate the enclosing
    span without threading the span object through every call.
    """
    if not _ENABLED:
        return
    current = _otel_trace.get_current_span()
    for key, value in attributes.items():
        current.set_attribute(key, value)


def mark_span_ok(span: Any | None = None) -> None:
    """Mark a span as successful. A no-op when telemetry is disabled."""
    if not _ENABLED:
        return
    target = span if span is not None else _otel_trace.get_current_span()
    target.set_status(_OtelStatus(_OtelStatusCode.OK))


def mark_span_error(description: str = "", span: Any | None = None) -> None:
    """Mark a span as failed. A no-op when telemetry is disabled."""
    if not _ENABLED:
        return
    target = span if span is not None else _otel_trace.get_current_span()
    target.set_status(_OtelStatus(_OtelStatusCode.ERROR, description or None))


@contextmanager
def record_duration(record: Any, attributes: dict[str, Any] | None = None) -> Iterator[None]:
    """Time the wrapped block and feed the elapsed seconds to ``record`` (a histogram).

    A no-op (no clock read) when telemetry is disabled.
    """
    if not _ENABLED:
        yield
        return
    start = time.perf_counter()
    try:
        yield
    finally:
        record(time.perf_counter() - start, attributes)


def record_command_submitted(command_type: str) -> None:
    if not _ENABLED:
        return
    _instruments.commands_submitted.add(1, {"command_type": command_type})


def record_command_accepted(command_type: str) -> None:
    if not _ENABLED:
        return
    _instruments.commands_accepted.add(1, {"command_type": command_type})


def record_command_rejected(command_type: str, reason: str) -> None:
    if not _ENABLED:
        return
    _instruments.commands_rejected.add(
        1, {"command_type": command_type, "reject_reason": _reject_category(reason)}
    )


def record_tick(duration: float, attributes: dict[str, Any] | None = None) -> None:
    if not _ENABLED:
        return
    _instruments.tick_duration.record(duration, attributes or {})


def record_handler(duration: float, attributes: dict[str, Any] | None = None) -> None:
    if not _ENABLED:
        return
    _instruments.handler_duration.record(duration, attributes or {})


def record_llm_decision(duration: float, attributes: dict[str, Any] | None = None) -> None:
    if not _ENABLED:
        return
    _instruments.llm_decision_duration.record(duration, attributes or {})


def record_llm_tokens(
    provider: str | None, model: str | None, prompt_tokens: int, completion_tokens: int
) -> None:
    record_llm_usage(provider, model, prompt_tokens, completion_tokens)


def record_llm_usage(
    provider: str | None,
    model: str | None,
    prompt_tokens: int,
    completion_tokens: int,
    *,
    total_tokens: int = 0,
    cost: float = 0.0,
) -> None:
    if not _ENABLED:
        return
    attributes = {"provider": provider or "unknown", "model": model or "unknown"}
    if prompt_tokens:
        _instruments.llm_tokens_prompt.add(prompt_tokens, attributes)
    if completion_tokens:
        _instruments.llm_tokens_completion.add(completion_tokens, attributes)
    if total_tokens:
        _instruments.llm_tokens_total.add(total_tokens, attributes)
    if cost:
        _instruments.llm_cost.add(cost, attributes)


def record_worldgen(duration: float, attributes: dict[str, Any] | None = None) -> None:
    if not _ENABLED:
        return
    _instruments.worldgen_duration.record(duration, attributes or {})


def record_worldgen_request(duration: float, attributes: dict[str, Any] | None = None) -> None:
    if not _ENABLED:
        return
    _instruments.worldgen_request_duration.record(duration, attributes or {})


def record_persist(duration: float, attributes: dict[str, Any] | None = None) -> None:
    if not _ENABLED:
        return
    _instruments.persist_duration.record(duration, attributes or {})


def instrument_fastapi(app: Any) -> None:
    """Attach FastAPI request auto-instrumentation when telemetry is enabled."""
    if not _ENABLED:
        return
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

    FastAPIInstrumentor.instrument_app(app)


def reset_for_tests() -> None:
    """Reset module state so tests can re-init with injected providers."""
    global _ENABLED, _initialized, _tracer, _meter, _instruments, _gauges_actor
    _ENABLED = False
    _initialized = False
    _tracer = None
    _meter = None
    _instruments = None
    _gauges_actor = None


__all__ = [
    "MAX_ATTRIBUTE_CHARS",
    "attr_text",
    "enabled",
    "init_telemetry",
    "instrument_fastapi",
    "mark_span_error",
    "mark_span_ok",
    "record_command_accepted",
    "record_command_rejected",
    "record_command_submitted",
    "record_duration",
    "record_handler",
    "record_llm_decision",
    "record_llm_tokens",
    "record_persist",
    "record_tick",
    "record_worldgen",
    "record_worldgen_request",
    "register_world_gauges",
    "reset_for_tests",
    "set_span_attributes",
    "span",
]
