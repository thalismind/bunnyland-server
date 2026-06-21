"""Tests for the OpenTelemetry wiring.

The disabled-path tests always run and prove the engine seams are free no-ops without the
extra or with the gate off. The enabled-path tests are marked ``otel`` and skipped unless
``opentelemetry.sdk`` is importable; they inject in-memory exporters so no collector is
needed.
"""

from __future__ import annotations

import json

import pytest
from conftest import build_scenario

from bunnyland import telemetry
from bunnyland.core import CommandCost, Lane, OnInsufficientPoints, build_submitted_command
from bunnyland.engine import GameLoop
from bunnyland.llm_agents import ControllerDispatch, ScriptedAgent, ToolCall
from bunnyland.llm_agents.agent import _ollama_token_usage, _openrouter_token_usage
from bunnyland.prompts.builder import PromptBuilder


def _command(scenario, command_type="move", **kwargs):
    payload = kwargs.pop("payload", None)
    if payload is None and command_type == "move":
        payload = {"direction": "north"}
    return build_submitted_command(
        character_id=str(scenario.character),
        controller_id=str(scenario.controller),
        controller_generation=scenario.generation,
        command_type=command_type,
        cost=kwargs.pop("cost", CommandCost(action=0)),
        lane=Lane.WORLD,
        payload=payload,
        on_insufficient_points=OnInsufficientPoints.QUEUE,
        submitted_at_epoch=0,
        command_id=kwargs.pop("command_id", None),
    )


# -- disabled path (always runs) ---------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_telemetry():
    telemetry.reset_for_tests()
    yield
    telemetry.reset_for_tests()


def test_init_is_a_no_op_when_disabled(monkeypatch):
    monkeypatch.delenv("BUNNYLAND_OTEL_ENABLED", raising=False)
    assert telemetry.init_telemetry() is False
    assert telemetry.enabled() is False
    # A second init is idempotent and still a no-op.
    assert telemetry.init_telemetry() is False


def test_otel_import_failure_marks_unavailable_and_no_ops(monkeypatch):
    """Simulate the ``otel`` extra being absent: the module falls back to no-op state.

    Reloads ``telemetry`` with the ``opentelemetry`` packages shimmed to ``None`` in
    ``sys.modules`` (which makes the top-level imports raise ``ImportError``), exercising the
    ``except ImportError`` fallback, then restores the real extra for the rest of the suite.
    """
    import importlib
    import sys

    monkeypatch.setitem(sys.modules, "opentelemetry", None)
    monkeypatch.setitem(sys.modules, "opentelemetry.metrics", None)
    monkeypatch.setitem(sys.modules, "opentelemetry.trace", None)
    try:
        importlib.reload(telemetry)
        assert telemetry._OTEL_AVAILABLE is False
        assert telemetry._otel_trace is None
        assert telemetry._otel_metrics is None
        # With the extra absent, init is a hard no-op even when the gate is on.
        monkeypatch.setenv("BUNNYLAND_OTEL_ENABLED", "1")
        assert telemetry.init_telemetry() is False
        assert telemetry.enabled() is False
    finally:
        for name in ("opentelemetry", "opentelemetry.metrics", "opentelemetry.trace"):
            sys.modules.pop(name, None)
        importlib.reload(telemetry)
    assert telemetry._OTEL_AVAILABLE is True


def test_span_and_record_helpers_are_no_ops_when_disabled(monkeypatch):
    monkeypatch.delenv("BUNNYLAND_OTEL_ENABLED", raising=False)
    telemetry.init_telemetry()
    with telemetry.span("game.tick", {"a": 1}) as span:
        span.set_attribute("b", 2)
        span.record_exception(ValueError("x"))
        span.set_status("ok")
    telemetry.set_span_attributes({"k": "v"})  # no current span; still a no-op
    assert telemetry.attr_text("short") == "short"
    long = "x" * (telemetry.MAX_ATTRIBUTE_CHARS + 10)
    assert telemetry.attr_text(long).endswith("chars total)")
    assert telemetry.attr_text(123) == "123"
    with telemetry.record_duration(telemetry.record_tick, {"x": 1}):
        pass
    telemetry.record_command_submitted("move")
    telemetry.record_command_accepted("move")
    telemetry.record_command_rejected("move", "insufficient points")
    telemetry.record_tick(0.05)
    telemetry.record_handler(0.1, {"command_type": "move"})
    telemetry.record_llm_decision(0.2, {"provider": "local"})
    telemetry.record_llm_tokens("ollama", "m", 10, 5)
    telemetry.record_worldgen(0.3, {"generator": "empty"})
    telemetry.record_worldgen_request(0.1, {"provider": "ollama", "model": "m"})
    telemetry.record_persist(0.4, {"operation": "save", "format": "json"})
    telemetry.register_world_gauges(build_scenario().actor)  # no-op when disabled
    telemetry.instrument_fastapi(object())  # no-op when disabled


async def test_engine_seams_run_with_telemetry_disabled(monkeypatch):
    """Ticking with a queued accepted + rejected command exercises the disabled branches."""
    monkeypatch.delenv("BUNNYLAND_OTEL_ENABLED", raising=False)
    telemetry.init_telemetry()
    scenario = build_scenario()
    scenario.actor.submit_nowait(_command(scenario, "frobnicate", payload={}))
    scenario.actor.submit_nowait(_command(scenario))
    await scenario.actor.tick(0.0)
    assert scenario.actor.epoch == 0


@pytest.mark.parametrize(
    "reason,expected",
    [
        ("insufficient points", "insufficient_points"),
        ("stale controller generation", "stale_generation"),
        ("character is dead", "dead"),
        ("character is suspended", "suspended"),
        ("character is downed", "downed"),
        ("character is asleep", "asleep"),
        ("command expired", "expired"),
        ("no handler for move", "no_handler"),
        ("target is unreachable", "bad_target"),
        ("rejected by handler", "handler_rejected"),
        ("something else entirely", "other"),
        ("", "other"),
    ],
)
def test_reject_category_buckets_reasons(reason, expected):
    assert telemetry._reject_category(reason) == expected


def test_token_usage_helpers_are_defensive():
    assert _ollama_token_usage({"prompt_eval_count": 12, "eval_count": 7}) == (12, 7)
    assert _ollama_token_usage({}) == (0, 0)
    assert _ollama_token_usage("not a mapping") == (0, 0)

    import types

    usage = types.SimpleNamespace(prompt_tokens=3, completion_tokens=9)
    assert _openrouter_token_usage(types.SimpleNamespace(usage=usage)) == (3, 9)
    assert _openrouter_token_usage(types.SimpleNamespace()) == (0, 0)


# -- enabled path (requires the otel extra) ----------------------------------------------

pytest.importorskip("opentelemetry.sdk")
pytestmark_otel = pytest.mark.otel


@pytest.fixture
def otel_capture(monkeypatch):
    """Enable telemetry against in-memory exporters; yield (spans_exporter, metric_reader)."""
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import InMemoryMetricReader
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    monkeypatch.setenv("BUNNYLAND_OTEL_ENABLED", "1")
    resource = Resource.create({"service.name": "bunnyland-test"})
    span_exporter = InMemorySpanExporter()
    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(SimpleSpanProcessor(span_exporter))
    reader = InMemoryMetricReader()
    meter_provider = MeterProvider(resource=resource, metric_readers=[reader])

    telemetry.reset_for_tests()
    assert telemetry.init_telemetry(providers=(tracer_provider, meter_provider)) is True
    yield span_exporter, reader
    telemetry.reset_for_tests()


def _spans_by_name(span_exporter):
    return {span.name: span for span in span_exporter.get_finished_spans()}


def _metric_points(reader):
    points: dict[str, list] = {}
    data = reader.get_metrics_data()
    for resource_metric in data.resource_metrics:
        for scope_metric in resource_metric.scope_metrics:
            for metric in scope_metric.metrics:
                points.setdefault(metric.name, []).extend(metric.data.data_points)
    return points


@pytestmark_otel
def test_trace_file_exporter_writes_jsonl(monkeypatch, tmp_path):
    trace_path = tmp_path / "release.trace.jsonl"
    monkeypatch.setenv("BUNNYLAND_OTEL_ENABLED", "1")
    monkeypatch.setenv("BUNNYLAND_OTEL_TRACE_FILE", str(trace_path))
    monkeypatch.setenv("OTEL_METRICS_EXPORTER", "none")
    monkeypatch.setenv("OTEL_SERVICE_NAME", "bunnyland-release-test")

    telemetry.reset_for_tests()
    assert telemetry.init_telemetry() is True
    with telemetry.span("release.multiclient", {"client.count": 3}):
        pass
    telemetry.reset_for_tests()

    rows = [json.loads(line) for line in trace_path.read_text().splitlines()]
    assert rows[0]["name"] == "release.multiclient"
    assert rows[0]["trace_id"]
    assert rows[0]["span_id"]
    assert rows[0]["attributes"]["client.count"] == 3
    assert rows[0]["resource"]["service.name"] == "bunnyland-release-test"


def test_jsonl_exporter_returns_failure_on_oserror(tmp_path):
    pytest.importorskip("opentelemetry.sdk.trace.export")
    from opentelemetry.sdk.trace.export import SpanExportResult

    exporter = telemetry._JsonlSpanExporter(tmp_path / "trace.jsonl")
    # Point the exporter at a directory so opening it for append raises OSError.
    exporter.path = tmp_path
    assert exporter.export([]) is SpanExportResult.FAILURE


def test_jsonl_exporter_shutdown_and_force_flush(tmp_path):
    pytest.importorskip("opentelemetry.sdk.trace.export")
    exporter = telemetry._JsonlSpanExporter(tmp_path / "trace.jsonl")
    assert exporter.shutdown() is None
    assert exporter.force_flush() is True
    assert exporter.force_flush(timeout_millis=5) is True


def test_observe_yields_nothing_without_registered_actor():
    telemetry.reset_for_tests()
    # No actor registered: _observe short-circuits and yields no observations.
    assert list(telemetry._observe(lambda world: 0)) == []


@pytestmark_otel
async def test_tick_emits_spans_and_command_metrics(otel_capture):
    span_exporter, reader = otel_capture
    scenario = build_scenario()
    scenario.actor.submit_nowait(_command(scenario, "frobnicate", payload={}))
    scenario.actor.submit_nowait(_command(scenario))
    await scenario.actor.tick(0.0)

    spans = _spans_by_name(span_exporter)
    assert {
        "game.tick",
        "tick.ingest",
        "tick.systems",
        "tick.commands",
        "tick.consequences",
        "tick.after_tick",
        "command.attempt",
        "handler.execute",
    } <= set(spans)
    # handler.execute is nested under a command.attempt, which is nested under game.tick,
    # and the tick phases are direct children of game.tick.
    by_id = {span.context.span_id: span.name for span in span_exporter.get_finished_spans()}
    assert by_id[spans["handler.execute"].parent.span_id] == "command.attempt"
    assert by_id[spans["command.attempt"].parent.span_id] == "tick.commands"
    assert by_id[spans["tick.commands"].parent.span_id] == "game.tick"
    assert spans["game.tick"].parent is None  # tick is a root when run outside the loop
    assert spans["game.tick"].attributes["tick.epoch"] == 0
    assert spans["handler.execute"].attributes["handler.ok"] is True
    assert spans["handler.execute"].attributes["handler.kind"] == "MoveHandler"

    # The accepted move and the rejected frobnicate both annotate their attempt spans.
    attempts = {
        s.attributes["command.type"]: s.attributes
        for s in span_exporter.get_finished_spans()
        if s.name == "command.attempt"
    }
    assert attempts["move"]["command.executed"] is True
    assert "command.id" in attempts["move"]
    assert attempts["frobnicate"]["command.executed"] is False
    assert attempts["frobnicate"]["command.outcome"] == "rejected"
    assert attempts["frobnicate"]["command.reject_reason"] == "no_handler"

    points = _metric_points(reader)
    assert "bunnyland.tick.duration" in points
    submitted = {
        p.attributes["command_type"]: p.value for p in points["bunnyland.commands.submitted"]
    }
    assert submitted == {"frobnicate": 1, "move": 1}
    accepted = {
        p.attributes["command_type"]: p.value for p in points["bunnyland.commands.accepted"]
    }
    assert accepted == {"move": 1}
    rejected = points["bunnyland.commands.rejected"]
    assert rejected[0].attributes["reject_reason"] == "no_handler"


@pytestmark_otel
async def test_dispatch_emits_agent_spans_and_decision_metric(otel_capture):
    span_exporter, reader = otel_capture
    scenario = build_scenario()
    dispatch = ControllerDispatch(
        scenario.actor,
        PromptBuilder(scenario.actor.world),
        ScriptedAgent([ToolCall("move", {"direction": "north"})]),
    )
    decisions = await dispatch.run_once()
    assert [d.tool for d in decisions] == ["move"]

    spans = _spans_by_name(span_exporter)
    assert {"controller.run_once", "agent.prompt.build", "agent.decide"} <= set(spans)
    decide = spans["agent.decide"]
    assert decide.attributes["agent.kind"] == "ScriptedAgent"
    assert decide.attributes["decision.tool"] == "move"
    assert decide.attributes["character.id"] == str(scenario.character)
    # The scenario character is LLM-controlled, so the rendered prompt is captured.
    assert decide.attributes["decision.prompted"] is True
    assert "decision.prompt" in decide.attributes
    assert '"direction"' in decide.attributes["decision.arguments"]

    run_once = spans["controller.run_once"]
    assert run_once.attributes["dispatch.actable_count"] == 1
    assert run_once.attributes["dispatch.decision_count"] == 1
    by_id = {s.context.span_id: s.name for s in span_exporter.get_finished_spans()}
    assert by_id[spans["agent.decide"].parent.span_id] == "controller.run_once"
    assert by_id[spans["agent.prompt.build"].parent.span_id] == "controller.run_once"
    # The chosen command is submitted through the single chokepoint, tied to the same trace.
    assert "command.submit" in spans
    assert spans["command.submit"].attributes["command.type"] == "move"
    assert by_id[spans["command.submit"].parent.span_id] == "controller.run_once"

    points = _metric_points(reader)
    assert "bunnyland.llm.decision.duration" in points


class _AsyncMoveAgent:
    """Async agent whose decision is optionally gated, for background-path telemetry tests."""

    def __init__(self, gate=None) -> None:
        self._gate = gate

    def decide(self, prompt, context, *, character_id, model=None, provider=None, tools=None):
        del prompt, context, character_id, model, provider, tools
        gate = self._gate

        async def _decide():
            if gate is not None:
                await gate.wait()
            return ToolCall("move", {"direction": "north"})

        return _decide()


@pytestmark_otel
async def test_background_llm_decision_stays_in_the_run_once_trace(otel_capture):
    """A decision that runs in a background task still emits a parented, traced span.

    Regression: when async (LLM) decisions moved off the dispatch path into background
    tasks, the ``agent.decide`` span and the decision-latency metric must still be produced,
    and the span must remain in the trace of the ``run_once`` that scheduled it (asyncio
    copies the OTel context into the task), even though it finishes after run_once returns.
    """
    span_exporter, reader = otel_capture
    scenario = build_scenario()
    dispatch = ControllerDispatch(
        scenario.actor, PromptBuilder(scenario.actor.world), _AsyncMoveAgent()
    )

    # First pass schedules the background task; the decision is not finished yet.
    assert await dispatch.run_once() == []
    decisions = await dispatch.await_pending()
    assert [d.tool for d in decisions] == ["move"]

    spans = _spans_by_name(span_exporter)
    assert {
        "controller.run_once",
        "agent.prompt.build",
        "agent.decide",
        "command.submit",
    } <= set(spans)

    decide = spans["agent.decide"]
    assert decide.attributes["agent.kind"] == "_AsyncMoveAgent"
    assert decide.attributes["decision.tool"] == "move"
    assert decide.attributes["character.id"] == str(scenario.character)

    run_once = spans["controller.run_once"]
    by_id = {s.context.span_id: s.name for s in span_exporter.get_finished_spans()}
    # The background decide and the inline build both hang off the scheduling run_once span,
    # and everything shares one trace id.
    assert by_id[decide.parent.span_id] == "controller.run_once"
    assert by_id[spans["agent.prompt.build"].parent.span_id] == "controller.run_once"
    assert decide.context.trace_id == run_once.context.trace_id
    assert spans["command.submit"].context.trace_id == run_once.context.trace_id
    assert by_id[spans["command.submit"].parent.span_id] == "controller.run_once"

    # The decision-latency histogram is still recorded from inside the background task.
    points = _metric_points(reader)
    assert "bunnyland.llm.decision.duration" in points


@pytestmark_otel
async def test_serialized_background_decisions_each_emit_a_non_overlapping_span(otel_capture):
    """Two characters' background decisions are serialized but each is fully traced.

    Regression for decision locking/sync: with the provider lock, the two ``agent.decide``
    spans must not overlap in time, yet both must still be emitted with their own correct
    attributes and decision metrics.
    """
    import asyncio

    from bunnyland.core import (
        ActionPointsComponent,
        CharacterComponent,
        ContainmentMode,
        Contains,
        FocusPointsComponent,
        IdentityComponent,
        InitiativeComponent,
        LLMControllerComponent,
        spawn_entity,
    )

    span_exporter, reader = otel_capture
    scenario = build_scenario()
    world = scenario.actor.world
    other = spawn_entity(
        world,
        [
            IdentityComponent(name="Bramble", kind="character"),
            CharacterComponent(species="bunny"),
            ActionPointsComponent(current=5.0, maximum=5.0, regen_per_hour=1.0),
            FocusPointsComponent(current=3.0, maximum=3.0, regen_per_hour=0.5),
            InitiativeComponent(score=1.0),
        ],
    )
    world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), other.id
    )
    controller = spawn_entity(
        world, [LLMControllerComponent(profile_name="default", model="claude")]
    )
    scenario.actor.assign_controller(other.id, controller.id)

    dispatch = ControllerDispatch(
        scenario.actor, PromptBuilder(world), _AsyncMoveAgent(asyncio.Event())
    )
    assert await dispatch.run_once() == []
    dispatch.agent._gate.set()  # release both gated provider calls
    decisions = await dispatch.await_pending()
    assert sorted(d.tool for d in decisions) == ["move", "move"]

    decide_spans = [
        s for s in span_exporter.get_finished_spans() if s.name == "agent.decide"
    ]
    assert len(decide_spans) == 2
    # The provider lock serializes the calls: the two decide spans do not overlap in time.
    decide_spans.sort(key=lambda s: s.start_time)
    assert decide_spans[0].end_time <= decide_spans[1].start_time
    assert {s.attributes["decision.tool"] for s in decide_spans} == {"move"}

    points = _metric_points(reader)
    decision_points = points["bunnyland.llm.decision.duration"]
    assert sum(p.count for p in decision_points) == 2


@pytestmark_otel
async def test_game_loop_iteration_is_the_trace_root(otel_capture):
    span_exporter, _reader = otel_capture
    scenario = build_scenario()
    dispatch = ControllerDispatch(
        scenario.actor,
        PromptBuilder(scenario.actor.world),
        ScriptedAgent([ToolCall("move", {"direction": "north"})]),
    )
    loop = GameLoop(scenario.actor, dispatch, time_scale=1.0)
    await loop.run(max_ticks=1)

    spans = _spans_by_name(span_exporter)
    assert "game.loop.iteration" in spans
    iteration = spans["game.loop.iteration"]
    assert iteration.parent is None  # the loop iteration is the trace root
    assert iteration.attributes["loop.tick_index"] == 0
    by_id = {s.context.span_id: s.name for s in span_exporter.get_finished_spans()}
    # Both the world tick and the dispatch turn hang off the one iteration root.
    assert by_id[spans["game.tick"].parent.span_id] == "game.loop.iteration"
    assert by_id[spans["controller.run_once"].parent.span_id] == "game.loop.iteration"


@pytestmark_otel
def test_world_gauges_report_live_counts(otel_capture):
    _span_exporter, reader = otel_capture
    scenario = build_scenario()
    telemetry.register_world_gauges(scenario.actor)

    points = _metric_points(reader)
    characters = points["bunnyland.world.characters"][0].value
    rooms = points["bunnyland.world.rooms"][0].value
    assert characters == 1
    assert rooms == 2


@pytestmark_otel
def test_record_llm_tokens_emits_counters(otel_capture):
    _span_exporter, reader = otel_capture
    telemetry.record_llm_tokens("ollama", "deepseek", 40, 12)
    telemetry.record_llm_tokens("ollama", "deepseek", 0, 0)  # zero counts add nothing

    points = _metric_points(reader)
    prompt = points["bunnyland.llm.tokens.prompt"][0]
    completion = points["bunnyland.llm.tokens.completion"][0]
    assert prompt.value == 40
    assert prompt.attributes == {"provider": "ollama", "model": "deepseek"}
    assert completion.value == 12


@pytestmark_otel
async def test_traced_generate_emits_world_generate_span_and_metric(otel_capture):
    span_exporter, reader = otel_capture
    from bunnyland.core import WorldActor
    from bunnyland.worldgen import GenOptions, WorldGenerator, traced_generate
    from bunnyland.worldgen.generators import empty_generator

    generator = WorldGenerator(name="empty", generate=empty_generator)
    await traced_generate(generator, WorldActor(), "a quiet marsh", GenOptions())

    spans = _spans_by_name(span_exporter)
    assert "world.generate" in spans
    generate = spans["world.generate"]
    assert generate.attributes["generator"] == "empty"
    assert generate.attributes["llm"] is False
    assert generate.attributes["worldgen.seed"] == "a quiet marsh"

    points = _metric_points(reader)
    assert "bunnyland.worldgen.duration" in points
    assert points["bunnyland.worldgen.duration"][0].attributes["generator"] == "empty"


@pytestmark_otel
async def test_worldgen_llm_request_is_traced(otel_capture):
    pytest.importorskip("ollama")
    span_exporter, reader = otel_capture
    from bunnyland.worldgen.recursive_builder import OllamaWorldAgent

    class _FakeOllamaClient:
        async def chat(self, **kwargs):
            del kwargs
            return {
                "message": {"role": "assistant", "content": "{}"},
                "prompt_eval_count": 11,
                "eval_count": 7,
            }

    agent = OllamaWorldAgent(model="deepseek-test")
    agent._client = _FakeOllamaClient()
    assert await agent._ask("describe the starting room") == {}

    spans = _spans_by_name(span_exporter)
    assert "worldgen.llm.request" in spans
    request = spans["worldgen.llm.request"]
    assert request.attributes["provider"] == "ollama"
    assert request.attributes["model"] == "deepseek-test"
    assert request.attributes["instruction.chars"] > 0
    assert request.attributes["llm.tokens.prompt"] == 11
    assert request.attributes["llm.tokens.completion"] == 7

    points = _metric_points(reader)
    assert "bunnyland.worldgen.request.duration" in points
    tokens = points["bunnyland.llm.tokens.prompt"][0]
    assert tokens.value == 11
    assert tokens.attributes == {"provider": "ollama", "model": "deepseek-test"}


@pytestmark_otel
async def test_save_and_load_emit_persistence_spans_and_metrics(otel_capture, tmp_path):
    from bunnyland.core import WorldActor
    from bunnyland.persistence import WorldMeta, load_world, save_world
    from bunnyland.plugins import apply_plugins, bunnyland_plugins
    from bunnyland.worldgen import StubWorldBuilder, instantiate

    span_exporter, reader = otel_capture
    actor = WorldActor()
    apply_plugins(bunnyland_plugins(), actor)
    await instantiate(actor, await StubWorldBuilder().propose("a quiet marsh"))

    path = tmp_path / "world.json"
    save_world(actor, path, meta=WorldMeta(seed="a quiet marsh", generator="stub"))
    load_world(path, plugins=bunnyland_plugins())

    spans = _spans_by_name(span_exporter)
    assert spans["world.save"].attributes["operation"] == "save"
    assert spans["world.save"].attributes["format"] == "json"
    assert spans["world.save"].attributes["entity.count"] > 0
    assert spans["world.load"].attributes["operation"] == "load"
    assert spans["world.load"].attributes["entity.count"] > 0

    points = _metric_points(reader)
    operations = {p.attributes["operation"] for p in points["bunnyland.world.persist.duration"]}
    assert operations == {"save", "load"}


@pytestmark_otel
async def test_rest_snapshot_emits_child_span_under_request(otel_capture):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from bunnyland.core import WorldActor
    from bunnyland.persistence import WorldMeta
    from bunnyland.server.app import create_app

    span_exporter, _reader = otel_capture
    actor = WorldActor()
    app = create_app(actor, meta=WorldMeta(seed="s", generator="stub"), admin_token="secret")
    with TestClient(app) as client:
        response = client.get(
            "/world/snapshot", headers={"X-Bunnyland-Admin-Token": "secret"}
        )
        assert response.status_code == 200

    assert "world.snapshot" in _spans_by_name(span_exporter)


@pytestmark_otel
async def test_controller_assign_endpoint_is_traced(otel_capture):
    pytest.importorskip("fastapi")
    from bunnyland.server.app import create_app
    from bunnyland.server.models import ControllerAssignmentRequest

    span_exporter, _reader = otel_capture
    scenario = build_scenario()
    app = create_app(scenario.actor)
    route = next(
        route for route in app.routes
        if getattr(route, "path", None) == "/admin/controllers/assign"
    )
    await route.endpoint(
        ControllerAssignmentRequest(
            character_id=str(scenario.character),
            controller_id=str(scenario.controller),
        )
    )

    span = _spans_by_name(span_exporter)["controller.assign"]
    assert span.attributes["character.id"] == str(scenario.character)
    assert span.attributes["controller.id"] == str(scenario.controller)


@pytestmark_otel
async def test_web_controller_claim_endpoint_reports_client_id_in_trace(otel_capture):
    pytest.importorskip("fastapi")
    from bunnyland.server.app import create_app
    from bunnyland.server.models import WebControllerClaimRequest

    span_exporter, _reader = otel_capture
    scenario = build_scenario()
    app = create_app(scenario.actor)
    route = next(
        route for route in app.routes
        if getattr(route, "path", None) == "/world/controllers/web/claim"
    )
    response = await route.endpoint(
        WebControllerClaimRequest(
            character_id=str(scenario.character),
            client_id="client-a",
            label="toon",
        )
    )

    span = _spans_by_name(span_exporter)["controller.web_claim"]
    assert span.attributes["character.id"] == str(scenario.character)
    assert span.attributes["client.id"] == "client-a"
    assert span.attributes["client.label"] == "toon"
    assert span.attributes["controller.id"] == response.controller_id
    assert span.attributes["controller.generation"] == response.controller_generation


@pytestmark_otel
def test_build_otlp_providers_wires_real_otlp_exporters(monkeypatch):
    """The production path (no trace file, metrics on) builds OTLP span + metric exporters.

    No collector is contacted: the providers are constructed and immediately shut down, so
    nothing is ever exported. This covers the real exporter wiring that production uses.
    """
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
    from opentelemetry.sdk.trace import TracerProvider

    monkeypatch.delenv("BUNNYLAND_OTEL_TRACE_FILE", raising=False)
    monkeypatch.delenv("OTEL_METRICS_EXPORTER", raising=False)
    monkeypatch.setenv("OTEL_SERVICE_NAME", "bunnyland-otlp-test")
    # Bound the (doomed) shutdown export so it fails fast instead of retrying for seconds.
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_TIMEOUT", "1")

    tracer_provider, meter_provider = telemetry._build_otlp_providers()
    try:
        assert isinstance(tracer_provider, TracerProvider)
        assert isinstance(meter_provider, MeterProvider)
        assert tracer_provider.resource.attributes["service.name"] == "bunnyland-otlp-test"
        # A BatchSpanProcessor over the OTLP span exporter is attached (no JSONL file path).
        assert tracer_provider._active_span_processor is not None
        # A periodic OTLP metric reader is attached when metrics are not disabled.
        readers = list(meter_provider._sdk_config.metric_readers)
        assert readers
        assert all(isinstance(reader, PeriodicExportingMetricReader) for reader in readers)
    finally:
        tracer_provider.shutdown()
        meter_provider.shutdown()


@pytestmark_otel
def test_build_otlp_providers_drops_metrics_when_exporter_is_none(monkeypatch):
    """``OTEL_METRICS_EXPORTER=none`` builds a meter provider with no readers (traces only)."""
    monkeypatch.delenv("BUNNYLAND_OTEL_TRACE_FILE", raising=False)
    monkeypatch.setenv("OTEL_METRICS_EXPORTER", "none")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_TIMEOUT", "1")

    tracer_provider, meter_provider = telemetry._build_otlp_providers()
    try:
        assert list(meter_provider._sdk_config.metric_readers) == []
    finally:
        tracer_provider.shutdown()
        meter_provider.shutdown()


@pytestmark_otel
def test_init_telemetry_builds_real_providers_and_sets_globals(monkeypatch):
    """With the gate on and no injected providers, init builds real OTLP wiring (providers=None).

    This drives ``init_telemetry`` down the production branch that constructs the OTLP
    exporters and publishes them as the process-global providers for auto-instrumentation.
    """
    monkeypatch.setenv("BUNNYLAND_OTEL_ENABLED", "1")
    monkeypatch.delenv("BUNNYLAND_OTEL_TRACE_FILE", raising=False)
    monkeypatch.setenv("OTEL_METRICS_EXPORTER", "none")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_TIMEOUT", "1")

    telemetry.reset_for_tests()
    try:
        assert telemetry.init_telemetry() is True
        assert telemetry.enabled() is True
        # A real span flows through the configured provider without raising.
        with telemetry.span("init.smoke", {"k": 1}):
            pass
    finally:
        telemetry.reset_for_tests()


@pytestmark_otel
def test_instrument_fastapi_attaches_when_enabled(otel_capture):
    pytest.importorskip("fastapi")
    pytest.importorskip("opentelemetry.instrumentation.fastapi")
    from fastapi import FastAPI
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

    app = FastAPI()
    telemetry.instrument_fastapi(app)
    assert getattr(app, "_is_instrumented_by_opentelemetry", False) is True
    # Leave no global instrumentation state behind for sibling tests.
    FastAPIInstrumentor.uninstrument_app(app)
