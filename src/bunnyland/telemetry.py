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
import math
import os
import time
from collections import Counter
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path
from socketserver import BaseServer
from threading import Thread
from typing import TYPE_CHECKING, Protocol

from relics import Entity, EntityId, World

if TYPE_CHECKING:
    from .core.world_actor import WorldActor
    from .engine import GameLoop
    from .llm_agents.dispatch import ControllerDispatch
    from .server.subscriptions import EventStream

try:
    from opentelemetry import context as _otel_context
    from opentelemetry import metrics as _otel_metrics
    from opentelemetry import trace as _otel_trace
    from opentelemetry.trace import Status as _OtelStatus
    from opentelemetry.trace import StatusCode as _OtelStatusCode

    _OTEL_AVAILABLE = True
except ImportError:  # the optional ``otel`` extra is not installed
    _otel_context = None
    _otel_metrics = None
    _otel_trace = None
    _OtelStatus = None
    _OtelStatusCode = None
    _OTEL_AVAILABLE = False


_TRACER_NAME = "bunnyland"
_METER_NAME = "bunnyland"


class _Span(Protocol):
    def set_attribute(self, key: str, value: object) -> object: ...

    def record_exception(self, exception: BaseException) -> object: ...

    def set_status(self, status: object) -> object: ...

    def add_event(self, name: str, attributes: Mapping[str, object]) -> object: ...

    def get_span_context(self) -> object: ...


class _SpanContextManager(Protocol):
    def __enter__(self) -> _Span: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: object | None,
    ) -> bool | None: ...


class _Tracer(Protocol):
    def start_as_current_span(
        self,
        name: str,
        *,
        context: object | None,
        attributes: Mapping[str, object],
        record_exception: bool,
        set_status_on_exception: bool,
    ) -> _SpanContextManager: ...


class _CounterInstrument(Protocol):
    def add(self, amount: int | float, attributes: Mapping[str, object]) -> None: ...


class _HistogramInstrument(Protocol):
    def record(self, amount: int | float, attributes: Mapping[str, object]) -> None: ...


class _Meter(Protocol):
    def create_counter(
        self, name: str, *, unit: str = "", description: str = ""
    ) -> _CounterInstrument: ...

    def create_histogram(
        self, name: str, *, unit: str = "", description: str = ""
    ) -> _HistogramInstrument: ...

    def create_observable_gauge(
        self,
        name: str,
        *,
        callbacks: Sequence[Callable[[object], Iterator[object]]],
        description: str = "",
    ) -> object: ...


class _TracerProvider(Protocol):
    def get_tracer(self, name: str) -> _Tracer: ...


class _MeterProvider(Protocol):
    def get_meter(self, name: str) -> _Meter: ...


# Module-level state. ``_ENABLED`` is the single hot-path gate.
_ENABLED = False
_initialized = False
_tracer: _Tracer | None = None
_meter: _Meter | None = None
_instruments: _Instruments | None = None
_gauges_actor: WorldActor | None = None
_gauges_dispatch: ControllerDispatch | None = None
_gauges_loop: GameLoop | None = None
_gauges_stream: EventStream | None = None
_world_gauges_registered = False
_runtime_gauges_registered = False
_stream_gauges_registered = False
_world_audit_enabled = False
_orphan_grace_seconds = 300.0
_orphan_candidates: dict[EntityId, float] = {}
_prometheus_server: BaseServer | None = None
_prometheus_thread: Thread | None = None


# -- no-op stubs (used when telemetry is disabled or the extra is absent) ----------------


class _NoOpSpan:
    """Stands in for an OTel span; every method is a no-op."""

    def set_attribute(self, *args: object, **kwargs: object) -> None:
        pass

    def record_exception(self, *args: object, **kwargs: object) -> None:
        pass

    def set_status(self, *args: object, **kwargs: object) -> None:
        pass

    def add_event(self, *args: object, **kwargs: object) -> None:
        pass

    def get_span_context(self) -> None:
        return None


class _NoOpSpanCM:
    """A reusable context manager yielding the shared no-op span (no allocation)."""

    def __enter__(self) -> _NoOpSpan:
        return _NOOP_SPAN

    def __exit__(self, *exc: object) -> bool:
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

    def __init__(self, meter: _Meter) -> None:
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
        self.loop_iteration_duration = meter.create_histogram(
            "bunnyland.loop.iteration.duration",
            unit="s",
            description="Complete game-loop iteration wall-clock duration.",
        )
        self.controller_turn_duration = meter.create_histogram(
            "bunnyland.controller.turn.duration",
            unit="s",
            description="Controller turn from prompt projection through final decision.",
        )
        self.prompt_build_duration = meter.create_histogram(
            "bunnyland.prompt.build.duration",
            unit="s",
            description="Prompt context construction wall-clock duration.",
        )
        self.prompt_filter_duration = meter.create_histogram(
            "bunnyland.prompt.filter.duration",
            unit="s",
            description="Prompt filtering wall-clock duration.",
        )
        self.prompt_characters = meter.create_histogram(
            "bunnyland.prompt.characters",
            unit="{character}",
            description="Rendered prompt character count.",
        )
        self.llm_requests = meter.create_counter(
            "bunnyland.llm.requests",
            description="LLM provider request attempts.",
        )
        self.llm_request_duration = meter.create_histogram(
            "bunnyland.llm.request.duration",
            unit="s",
            description="Single LLM provider request attempt wall-clock duration.",
        )
        self.websocket_connections = meter.create_counter(
            "bunnyland.websocket.connections",
            description="WebSocket subscriptions opened.",
        )
        self.websocket_connections_closed = meter.create_counter(
            "bunnyland.websocket.connections.closed",
            description="WebSocket subscriptions closed.",
        )
        self.websocket_frames_dropped = meter.create_counter(
            "bunnyland.websocket.frames.dropped",
            description="WebSocket frames dropped because a bounded queue was full.",
        )
        self.websocket_resyncs = meter.create_counter(
            "bunnyland.websocket.resyncs",
            description="WebSocket resynchronizations after frame loss.",
        )
        self.websocket_projection_duration = meter.create_histogram(
            "bunnyland.websocket.projection.duration",
            unit="s",
            description="WebSocket projection construction wall-clock duration.",
        )


# -- public surface ----------------------------------------------------------------------


def enabled() -> bool:
    """Return whether telemetry is active. The single hot-path gate."""
    return _ENABLED


def content_capture_enabled() -> bool:
    """Return whether operators explicitly opted into content-derived trace attributes."""
    value = (os.environ.get("BUNNYLAND_OTEL_CAPTURE_CONTENT") or "").strip().lower()
    return _ENABLED and value in {"1", "true", "yes", "on"}


def _enabled_from_env() -> bool:
    value = (os.environ.get("BUNNYLAND_OTEL_ENABLED") or "").strip().lower()
    return value in {"1", "true", "yes", "on"}


def _world_audit_config() -> tuple[bool, float]:
    value = (os.environ.get("BUNNYLAND_OTEL_WORLD_AUDIT_ENABLED") or "").strip().lower()
    audit_enabled = value in {"1", "true", "yes", "on"}
    if not audit_enabled:
        return False, 300.0
    raw_grace = (os.environ.get("BUNNYLAND_OTEL_ORPHAN_GRACE_SECONDS") or "300").strip()
    try:
        grace = float(raw_grace)
    except ValueError as exc:
        raise ValueError(
            "BUNNYLAND_OTEL_ORPHAN_GRACE_SECONDS must be a finite nonnegative number"
        ) from exc
    if not math.isfinite(grace) or grace < 0:
        raise ValueError(
            "BUNNYLAND_OTEL_ORPHAN_GRACE_SECONDS must be a finite nonnegative number"
        )
    return True, grace


def init_telemetry(
    *, providers: tuple[_TracerProvider, _MeterProvider] | None = None
) -> bool:
    """Set up tracing + metrics if enabled. Idempotent; returns whether telemetry is active.

    ``providers`` lets tests inject ``(TracerProvider, MeterProvider)`` wired to in-memory
    exporters instead of the real OTLP exporters. Production passes ``None``.
    """
    global _ENABLED, _initialized, _tracer, _meter, _instruments
    global _world_audit_enabled, _orphan_grace_seconds
    if _initialized:
        return _ENABLED
    _initialized = True
    if not _OTEL_AVAILABLE or not _enabled_from_env():
        return False

    _world_audit_enabled, _orphan_grace_seconds = _world_audit_config()

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


def _prometheus_bind() -> tuple[str, int]:
    host = (os.environ.get("OTEL_EXPORTER_PROMETHEUS_HOST") or "127.0.0.1").strip()
    raw_port = (os.environ.get("OTEL_EXPORTER_PROMETHEUS_PORT") or "9464").strip()
    if not host:
        raise ValueError("OTEL_EXPORTER_PROMETHEUS_HOST must not be empty")
    try:
        port = int(raw_port)
    except ValueError as exc:
        raise ValueError("OTEL_EXPORTER_PROMETHEUS_PORT must be an integer") from exc
    if not 1 <= port <= 65535:
        raise ValueError("OTEL_EXPORTER_PROMETHEUS_PORT must be between 1 and 65535")
    return host, port


def _build_metric_readers() -> list[object]:
    global _prometheus_server, _prometheus_thread

    exporter = (os.environ.get("OTEL_METRICS_EXPORTER") or "otlp").strip().lower()
    if exporter == "none":
        return []
    if exporter == "prometheus":
        from opentelemetry.exporter.prometheus import PrometheusMetricReader
        from prometheus_client import start_http_server

        host, port = _prometheus_bind()
        reader = PrometheusMetricReader()
        _prometheus_server, _prometheus_thread = start_http_server(port, addr=host)
        return [reader]
    if exporter not in {"", "otlp"}:
        raise ValueError(
            "OTEL_METRICS_EXPORTER must be one of 'otlp', 'prometheus', or 'none'"
        )

    from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
    from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader

    return [PeriodicExportingMetricReader(OTLPMetricExporter())]


def _build_otlp_providers() -> tuple[_TracerProvider, _MeterProvider]:
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.metrics import MeterProvider
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
    if trace_file and not metrics_exporter:
        readers = []
    else:
        readers = _build_metric_readers()
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

    def export(self, spans: Sequence[object]) -> object:
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


def _span_to_json(span: object) -> dict[str, object]:
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
        "attributes": _redacted_attributes(span.attributes or {}),
        "events": [
            {
                "name": event.name,
                "timestamp_unix_nano": event.timestamp,
                "attributes": _redacted_attributes(event.attributes or {}),
            }
            for event in span.events
        ],
        "status": {
            "code": str(getattr(status, "status_code", "")),
            "description": getattr(status, "description", None),
        },
        "resource": dict(getattr(span.resource, "attributes", {}) or {}),
    }


_CONTROLLER_KINDS = (
    "discord",
    "llm",
    "mcp",
    "behavior",
    "scripted",
    "web",
    "suspended",
    "unknown",
)


def register_world_gauges(actor: WorldActor) -> None:
    """Register observable gauges that read live world counts on the export interval."""
    global _gauges_actor, _world_gauges_registered
    if not _ENABLED:
        return
    if _gauges_actor is not actor:
        _orphan_candidates.clear()
    _gauges_actor = actor
    if _world_gauges_registered:
        return
    _world_gauges_registered = True
    assert _meter is not None
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
    meter.create_observable_gauge(
        "bunnyland.world.characters.active",
        callbacks=[_observe_active_characters],
        description="Lifecycle-active characters grouped by their assigned controller kind.",
    )
    if _world_audit_enabled:
        meter.create_observable_gauge(
            "bunnyland.world.entities.orphaned",
            callbacks=[_observe_orphaned_entities],
            description="Mature ECS entities with no components or live relationships.",
        )


def register_runtime_gauges(
    actor: WorldActor, dispatch: ControllerDispatch, loop: GameLoop
) -> None:
    """Register live queue, controller, and loop gauges once."""
    global _gauges_actor, _gauges_dispatch, _gauges_loop, _runtime_gauges_registered
    if not _ENABLED:
        return
    _gauges_actor = actor
    _gauges_dispatch = dispatch
    _gauges_loop = loop
    if _runtime_gauges_registered:
        return
    _runtime_gauges_registered = True
    assert _meter is not None
    _meter.create_observable_gauge(
        "bunnyland.command.queue.depth",
        callbacks=[_observe_command_queue_depth],
        description="Commands waiting in the actor inbox or execution lanes.",
    )
    _meter.create_observable_gauge(
        "bunnyland.controller.decisions.inflight",
        callbacks=[_observe_inflight_decisions],
        description="Controller decisions currently executing.",
    )
    _meter.create_observable_gauge(
        "bunnyland.loop.running",
        callbacks=[_observe_loop_running],
        description="Whether the game loop is running.",
    )
    _meter.create_observable_gauge(
        "bunnyland.loop.paused",
        callbacks=[_observe_loop_paused],
        description="Whether the game loop is paused.",
    )


def register_event_stream(stream: EventStream) -> None:
    """Register the active WebSocket stream and its live gauges once."""
    global _gauges_stream, _stream_gauges_registered
    if not _ENABLED:
        return
    _gauges_stream = stream
    if _stream_gauges_registered:
        return
    _stream_gauges_registered = True
    assert _meter is not None
    _meter.create_observable_gauge(
        "bunnyland.websocket.connections.active",
        callbacks=[_observe_websocket_connections],
        description="Active WebSocket subscriptions.",
    )
    _meter.create_observable_gauge(
        "bunnyland.websocket.queue.depth",
        callbacks=[_observe_websocket_queue_depth],
        description="Frames buffered across active WebSocket subscriptions.",
    )


def _observation(value: int | float, attributes: Mapping[str, object] | None = None) -> object:
    assert _otel_metrics is not None
    return _otel_metrics.Observation(value, attributes=attributes or {})


def _observe_entities(_options: object) -> Iterator[object]:
    yield from _observe(lambda world: len(list(world.query().execute_entities())))


def _observe_characters(_options: object) -> Iterator[object]:
    from .core.components import CharacterComponent

    yield from _observe(
        lambda world: len(list(world.query().with_all([CharacterComponent]).execute_entities()))
    )


def _observe_rooms(_options: object) -> Iterator[object]:
    from .core.components import RoomComponent

    yield from _observe(
        lambda world: len(list(world.query().with_all([RoomComponent]).execute_entities()))
    )


def _entity_is_empty_and_disconnected(
    world: World, entity_id: EntityId, live_ids: set[EntityId]
) -> bool:
    """Return whether a live entity has no state or live graph connections.

    Relics does not currently expose relationship-type enumeration publicly. Keep the
    private-index access isolated here, and inspect the nested edge dictionaries because
    removal can leave empty type buckets behind.
    """
    if world._entities.get(entity_id):
        return False
    outgoing = world._relationships.get(entity_id, {})
    if any(target_id in live_ids for edges in outgoing.values() for target_id in edges):
        return False
    incoming = world._incoming_relationships.get(entity_id, {})
    return not any(source_id in live_ids for edges in incoming.values() for source_id in edges)


def _orphaned_entity_count(world: World, *, now: float | None = None) -> int:
    observed_at = time.monotonic() if now is None else now
    live_ids = set(world._entities)
    for entity_id in tuple(_orphan_candidates):
        if entity_id not in live_ids:
            del _orphan_candidates[entity_id]
    mature = 0
    for entity_id in live_ids:
        if not _entity_is_empty_and_disconnected(world, entity_id, live_ids):
            _orphan_candidates.pop(entity_id, None)
            continue
        first_observed = _orphan_candidates.setdefault(entity_id, observed_at)
        if observed_at - first_observed >= _orphan_grace_seconds:
            mature += 1
    return mature


def _observe_orphaned_entities(_options: object) -> Iterator[object]:
    if _gauges_actor is not None:
        yield _observation(_orphaned_entity_count(_gauges_actor.world))


def _observe(count_fn: Callable[[World], int]) -> Iterator[object]:
    if _gauges_actor is None:
        return
    yield _observation(count_fn(_gauges_actor.world))


def _controller_kind(world: World, character: Entity) -> str:
    from .core.controllers import (
        BehaviorControllerComponent,
        DiscordControllerComponent,
        LLMControllerComponent,
        MCPControllerComponent,
        ScriptedControllerComponent,
        SuspendedControllerComponent,
        WebControllerComponent,
    )
    from .core.edges import ControlledBy

    component_kinds = (
        (DiscordControllerComponent, "discord"),
        (LLMControllerComponent, "llm"),
        (MCPControllerComponent, "mcp"),
        (BehaviorControllerComponent, "behavior"),
        (ScriptedControllerComponent, "scripted"),
        (WebControllerComponent, "web"),
        (SuspendedControllerComponent, "suspended"),
    )
    relationships = character.get_relationships(ControlledBy)
    if not relationships:
        return "unknown"
    _edge, controller_id = relationships[0]
    if not world.has_entity(controller_id):
        return "unknown"
    controller = world.get_entity(controller_id)
    for component_type, kind in component_kinds:
        if controller.has_component(component_type):
            return kind
    return "unknown"


def _active_character_counts(world: World) -> Counter[str]:
    from .core.components import (
        CharacterComponent,
        DeadComponent,
        DownedComponent,
        SleepingComponent,
        SuspendedComponent,
    )

    counts = Counter({kind: 0 for kind in _CONTROLLER_KINDS})
    query = world.query().with_all([CharacterComponent]).with_none(
        [DeadComponent, DownedComponent, SleepingComponent, SuspendedComponent]
    )
    for character in query.execute_entities():
        kind = _controller_kind(world, character)
        if kind != "suspended":
            counts[kind] += 1
    return counts


def _observe_active_characters(_options: object) -> Iterator[object]:
    if _gauges_actor is None:
        return
    for kind, count in _active_character_counts(_gauges_actor.world).items():
        yield _observation(count, {"controller_kind": kind})


def _observe_command_queue_depth(_options: object) -> Iterator[object]:
    if _gauges_actor is None:
        return
    for stage, depth in _gauges_actor.command_queue_depths().items():
        yield _observation(depth, {"stage": stage})


def _observe_inflight_decisions(_options: object) -> Iterator[object]:
    if _gauges_dispatch is None:
        return
    counts = _gauges_dispatch.inflight_decision_counts()
    for kind in ("llm", "behavior", "scripted", "unknown"):
        yield _observation(counts.get(kind, 0), {"controller_kind": kind})


def _observe_loop_running(_options: object) -> Iterator[object]:
    if _gauges_loop is not None:
        yield _observation(int(_gauges_loop.running))


def _observe_loop_paused(_options: object) -> Iterator[object]:
    if _gauges_loop is not None:
        yield _observation(int(_gauges_loop.paused))


def _observe_websocket_connections(_options: object) -> Iterator[object]:
    if _gauges_stream is not None:
        yield _observation(_gauges_stream.active_connections)


def _observe_websocket_queue_depth(_options: object) -> Iterator[object]:
    if _gauges_stream is not None:
        yield _observation(_gauges_stream.queue_depth)


class _RedactingSpan:
    """Small proxy that prevents sensitive values from reaching any trace exporter."""

    def __init__(self, span: _Span) -> None:
        self._span = span

    def set_attribute(self, key: str, value: object) -> None:
        self._span.set_attribute(key, _redact_attribute(key, value))

    def record_exception(
        self, exception: BaseException, *args: object, **kwargs: object
    ) -> None:
        del args, kwargs
        self._span.add_event(
            "exception",
            {
                "exception.type": type(exception).__name__,
                "exception.message": _redaction_marker(str(exception)),
            },
        )

    def set_status(self, status: object) -> object:
        return self._span.set_status(status)

    def add_event(self, name: str, attributes: Mapping[str, object]) -> object:
        return self._span.add_event(name, attributes)

    def get_span_context(self) -> object:
        return self._span.get_span_context()


def capture_context() -> object | None:
    """Capture the active trace context for later background work.

    The return value is deliberately opaque.  Disabled telemetry returns the shared
    ``None`` singleton without consulting an OTel provider or allocating a context.
    """
    if not _ENABLED:
        return None
    assert _otel_context is not None
    return _otel_context.get_current()


@contextmanager
def span(
    name: str,
    attributes: dict[str, object] | None = None,
    *,
    parent_context: object | None = None,
) -> Iterator[_Span]:
    """Return a span context manager. A shared singleton no-op when telemetry is disabled."""
    if not _ENABLED:
        with _NOOP_SPAN_CM as noop:
            yield noop
        return
    assert _tracer is not None
    with _tracer.start_as_current_span(
        name,
        context=parent_context,
        attributes=_redacted_attributes(attributes or {}),
        record_exception=False,
        set_status_on_exception=False,
    ) as raw_span:
        safe_span = _RedactingSpan(raw_span)
        try:
            yield safe_span
        except Exception as exc:
            safe_span.record_exception(exc)
            mark_span_error(str(exc), safe_span)
            raise


#: Upper bound on a single string span attribute (e.g. a rendered prompt). Keeps individual
#: spans from ballooning while still capturing enough to debug a decision.
MAX_ATTRIBUTE_CHARS = 8192

_SENSITIVE_ATTRIBUTE_NAMES = frozenset(
    {
        "arguments",
        "authorization",
        "content",
        "input",
        "message",
        "password",
        "prompt",
        "reply",
        "secret",
        "text",
    }
)


def _redaction_marker(value: object) -> str:
    text = value if isinstance(value, str) else json.dumps(value, default=str, sort_keys=True)
    digest = sha256(text.encode("utf-8")).hexdigest()[:16]
    return f"[REDACTED sha256:{digest} chars:{len(text)}]"


def _attribute_is_sensitive(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    final = normalized.rsplit(".", 1)[-1]
    return (
        final in _SENSITIVE_ATTRIBUTE_NAMES
        or any(final.endswith(f"_{name}") for name in _SENSITIVE_ATTRIBUTE_NAMES)
        or any(
            token in normalized
            for token in (
                "api_key",
                "claim_secret",
                "access_token",
                "refresh_token",
                "bearer_token",
            )
        )
    )


def _redact_attribute(key: str, value: object) -> object:
    if isinstance(value, (bool, int, float)) or value is None:
        return value
    return _redaction_marker(value) if _attribute_is_sensitive(key) else value


def _redacted_attributes(attributes: Mapping[str, object]) -> dict[str, object]:
    return {key: _redact_attribute(key, value) for key, value in attributes.items()}


def attr_text(value: object, *, limit: int = MAX_ATTRIBUTE_CHARS) -> str:
    """Coerce a value to a span-safe string, truncating very long text with a length hint."""
    text = value if isinstance(value, str) else str(value)
    if len(text) > limit:
        return f"{text[:limit]}... ({len(text)} chars total)"
    return text


def set_span_attributes(attributes: Mapping[str, object]) -> None:
    """Set attributes on the currently active span. A no-op when telemetry is disabled.

    Lets nested code (e.g. command rejection deep inside ``_attempt``) annotate the enclosing
    span without threading the span object through every call.
    """
    if not _ENABLED:
        return
    current = _otel_trace.get_current_span()
    for key, value in attributes.items():
        current.set_attribute(key, _redact_attribute(key, value))


def mark_span_ok(span: _Span | None = None) -> None:
    """Mark a span as successful. A no-op when telemetry is disabled."""
    if not _ENABLED:
        return
    target = span if span is not None else _otel_trace.get_current_span()
    target.set_status(_OtelStatus(_OtelStatusCode.OK))


def mark_span_error(description: str = "", span: _Span | None = None) -> None:
    """Mark a span as failed. A no-op when telemetry is disabled."""
    if not _ENABLED:
        return
    target = span if span is not None else _otel_trace.get_current_span()
    if description:
        target.set_attribute("error.description_sha256", sha256(description.encode()).hexdigest())
    target.set_status(_OtelStatus(_OtelStatusCode.ERROR, "operation failed"))


@contextmanager
def record_duration(
    record: Callable[[float, dict[str, object] | None], None],
    attributes: dict[str, object] | None = None,
) -> Iterator[None]:
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


def record_tick(duration: float, attributes: dict[str, object] | None = None) -> None:
    if not _ENABLED:
        return
    _instruments.tick_duration.record(duration, attributes or {})


def record_handler(duration: float, attributes: dict[str, object] | None = None) -> None:
    if not _ENABLED:
        return
    _instruments.handler_duration.record(duration, attributes or {})


def record_llm_decision(duration: float, attributes: dict[str, object] | None = None) -> None:
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


def record_worldgen(duration: float, attributes: dict[str, object] | None = None) -> None:
    if not _ENABLED:
        return
    _instruments.worldgen_duration.record(duration, attributes or {})


def record_worldgen_request(
    duration: float, attributes: dict[str, object] | None = None
) -> None:
    if not _ENABLED:
        return
    _instruments.worldgen_request_duration.record(duration, attributes or {})


def record_persist(duration: float, attributes: dict[str, object] | None = None) -> None:
    if not _ENABLED:
        return
    _instruments.persist_duration.record(duration, attributes or {})


def record_loop_iteration(
    duration: float, attributes: dict[str, object] | None = None
) -> None:
    if not _ENABLED:
        return
    assert _instruments is not None
    _instruments.loop_iteration_duration.record(duration, attributes or {})


def record_controller_turn(
    duration: float, attributes: dict[str, object] | None = None
) -> None:
    if not _ENABLED:
        return
    assert _instruments is not None
    _instruments.controller_turn_duration.record(duration, attributes or {})


def record_prompt_build(
    duration: float, attributes: dict[str, object] | None = None
) -> None:
    if not _ENABLED:
        return
    assert _instruments is not None
    _instruments.prompt_build_duration.record(duration, attributes or {})


def record_prompt_filter(
    duration: float, attributes: dict[str, object] | None = None
) -> None:
    if not _ENABLED:
        return
    assert _instruments is not None
    _instruments.prompt_filter_duration.record(duration, attributes or {})


def record_prompt_characters(count: int, attributes: dict[str, object] | None = None) -> None:
    if not _ENABLED:
        return
    assert _instruments is not None
    _instruments.prompt_characters.record(count, attributes or {})


def record_llm_request(
    duration: float,
    *,
    provider: str,
    model: str,
    outcome: str,
) -> None:
    if not _ENABLED:
        return
    assert _instruments is not None
    attributes = {"provider": provider, "model": model, "outcome": outcome}
    _instruments.llm_requests.add(1, attributes)
    _instruments.llm_request_duration.record(duration, attributes)


def record_websocket_connected() -> None:
    if _ENABLED:
        assert _instruments is not None
        _instruments.websocket_connections.add(1, {})


def record_websocket_closed() -> None:
    if _ENABLED:
        assert _instruments is not None
        _instruments.websocket_connections_closed.add(1, {})


def record_websocket_frame_dropped() -> None:
    if _ENABLED:
        assert _instruments is not None
        _instruments.websocket_frames_dropped.add(1, {})


def record_websocket_resync() -> None:
    if _ENABLED:
        assert _instruments is not None
        _instruments.websocket_resyncs.add(1, {})


def record_websocket_projection(duration: float) -> None:
    if _ENABLED:
        assert _instruments is not None
        _instruments.websocket_projection_duration.record(duration, {})


def instrument_fastapi(app: object) -> None:
    """Attach FastAPI request auto-instrumentation when telemetry is enabled."""
    if not _ENABLED:
        return
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

    FastAPIInstrumentor.instrument_app(app)


def reset_for_tests() -> None:
    """Reset module state so tests can re-init with injected providers."""
    global _ENABLED, _initialized, _tracer, _meter, _instruments
    global _gauges_actor, _gauges_dispatch, _gauges_loop, _gauges_stream
    global _world_gauges_registered, _runtime_gauges_registered, _stream_gauges_registered
    global _world_audit_enabled, _orphan_grace_seconds
    global _prometheus_server, _prometheus_thread
    if _prometheus_server is not None:
        _prometheus_server.shutdown()
        _prometheus_server.server_close()
    _ENABLED = False
    _initialized = False
    _tracer = None
    _meter = None
    _instruments = None
    _gauges_actor = None
    _gauges_dispatch = None
    _gauges_loop = None
    _gauges_stream = None
    _world_gauges_registered = False
    _runtime_gauges_registered = False
    _stream_gauges_registered = False
    _world_audit_enabled = False
    _orphan_grace_seconds = 300.0
    _orphan_candidates.clear()
    _prometheus_server = None
    _prometheus_thread = None


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
    "record_llm_request",
    "record_llm_tokens",
    "record_loop_iteration",
    "record_persist",
    "record_prompt_build",
    "record_prompt_characters",
    "record_prompt_filter",
    "record_tick",
    "record_controller_turn",
    "record_websocket_closed",
    "record_websocket_connected",
    "record_websocket_frame_dropped",
    "record_websocket_projection",
    "record_websocket_resync",
    "record_worldgen",
    "record_worldgen_request",
    "register_event_stream",
    "register_runtime_gauges",
    "register_world_gauges",
    "reset_for_tests",
    "set_span_attributes",
    "span",
]
