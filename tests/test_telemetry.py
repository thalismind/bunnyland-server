"""Tests for the OpenTelemetry wiring.

The disabled-path tests always run and prove the engine seams are free no-ops without the
extra or with the gate off. The enabled-path tests are marked ``otel`` and skipped unless
``opentelemetry.sdk`` is importable; they inject in-memory exporters so no collector is
needed.
"""

from __future__ import annotations

import pytest
from conftest import build_scenario

from bunnyland import telemetry
from bunnyland.core import CommandCost, Lane, OnInsufficientPoints, build_submitted_command
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


def test_span_and_record_helpers_are_no_ops_when_disabled(monkeypatch):
    monkeypatch.delenv("BUNNYLAND_OTEL_ENABLED", raising=False)
    telemetry.init_telemetry()
    with telemetry.span("game.tick", {"a": 1}) as span:
        span.set_attribute("b", 2)
        span.record_exception(ValueError("x"))
        span.set_status("ok")
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
async def test_tick_emits_spans_and_command_metrics(otel_capture):
    span_exporter, reader = otel_capture
    scenario = build_scenario()
    scenario.actor.submit_nowait(_command(scenario, "frobnicate", payload={}))
    scenario.actor.submit_nowait(_command(scenario))
    await scenario.actor.tick(0.0)

    spans = _spans_by_name(span_exporter)
    assert {"game.tick", "command.attempt", "handler.execute"} <= set(spans)
    # handler.execute is nested under a command.attempt, which is nested under game.tick.
    by_id = {span.context.span_id: span.name for span in span_exporter.get_finished_spans()}
    assert by_id[spans["handler.execute"].parent.span_id] == "command.attempt"
    assert by_id[spans["command.attempt"].parent.span_id] == "game.tick"
    assert spans["handler.execute"].attributes["handler.ok"] is True

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
    assert {"controller.run_once", "agent.decide"} <= set(spans)
    assert spans["agent.decide"].attributes["agent.kind"] == "ScriptedAgent"
    assert spans["agent.decide"].attributes["decision.tool"] == "move"

    points = _metric_points(reader)
    assert "bunnyland.llm.decision.duration" in points


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
