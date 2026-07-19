"""Tests for the OpenTelemetry wiring.

The disabled-path tests always run and prove the engine seams are free no-ops without the
extra or with the gate off. The enabled-path tests are marked ``otel`` and skipped unless
``opentelemetry.sdk`` is importable; they inject in-memory exporters so no collector is
needed.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import sys
import types

import httpx
import pytest
from conftest import build_scenario

from bunnyland import telemetry
from bunnyland.core import (
    ActionDefinition,
    CommandCost,
    Lane,
    OnInsufficientPoints,
    build_submitted_command,
    spawn_entity,
)
from bunnyland.core.controllers import BehaviorControllerComponent
from bunnyland.engine import GameLoop
from bunnyland.foundation.prompt_filters.mechanics import (
    BUILTIN_PROMPT_FILTERS,
    PromptFilterBinding,
    RedactedPromptFilterComponent,
)
from bunnyland.llm_agents import ControllerDispatch, ScriptedAgent, ToolCall
from bunnyland.llm_agents.agent import (
    CHARACTER_SYSTEM_PROMPT,
    ChatAgentReply,
    OllamaAgent,
    _ollama_token_usage,
    _ollama_usage,
    _openrouter_token_usage,
    _openrouter_usage,
)
from bunnyland.prompts import PromptFilterDefinition, PromptFilterRuntime
from bunnyland.prompts.builder import PromptBuilder
from bunnyland.server.auth import WORLD_ADMIN_SCOPE, TokenPrincipal
from bunnyland.server.character_chat import CharacterChatService, _trace_json
from bunnyland.server.models import CharacterChatRequest


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
    assert telemetry.capture_context() is None
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
    ollama_usage = _ollama_usage({"prompt_eval_count": 12, "eval_count": 7})
    assert ollama_usage.total_tokens == 19
    assert ollama_usage.cost == 0.0
    assert ollama_usage.tokens_available is True
    assert ollama_usage.cost_available is False
    ollama_object_usage = _ollama_usage(types.SimpleNamespace(prompt_eval_count=8, eval_count=5))
    assert ollama_object_usage.prompt_tokens == 8
    assert ollama_object_usage.completion_tokens == 5
    assert ollama_object_usage.total_tokens == 13

    usage = types.SimpleNamespace(
        prompt_tokens=3, completion_tokens=9, total_tokens=12, total_cost=0.005
    )
    assert _openrouter_token_usage(types.SimpleNamespace(usage=usage)) == (3, 9)
    openrouter_usage = _openrouter_usage(types.SimpleNamespace(usage=usage))
    assert openrouter_usage.total_tokens == 12
    assert openrouter_usage.cost == 0.005
    assert openrouter_usage.tokens_available is True
    assert openrouter_usage.cost_available is True
    mapping_usage = _openrouter_usage(
        types.SimpleNamespace(usage={"prompt_tokens": 1, "completion_tokens": 2})
    )
    assert mapping_usage.total_tokens == 3
    assert mapping_usage.cost == 0.0
    assert mapping_usage.tokens_available is True
    assert mapping_usage.cost_available is False
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


class _FakeTelemetryChatAgent:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    async def chat(self, messages, *, character_id, model=None, provider=None, tools=None):
        self.calls.append(
            {
                "messages": messages,
                "character_id": character_id,
                "model": model,
                "provider": provider,
                "tools": tools or [],
            }
        )
        if not self.replies:
            return ChatAgentReply(content="done")
        return self.replies.pop(0)


def _span_status_name(span) -> str:
    return span.status.status_code.name


def _chat_service(scenario, agent, *, timeout=0.01):
    return CharacterChatService(
        scenario.actor,
        PromptBuilder(scenario.actor.world),
        agent,
        result_timeout_seconds=timeout,
    )


def test_character_chat_trace_json_falls_back_for_unserializable_value():
    assert _trace_json({"bad": object()}).startswith('"')


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
async def test_command_submit_marks_unexpected_exception_error(otel_capture, monkeypatch):
    span_exporter, _reader = otel_capture
    scenario = build_scenario()

    def explode(_command):
        raise RuntimeError("validation exploded")

    monkeypatch.setattr(scenario.actor, "_validate_submission", explode)
    with pytest.raises(RuntimeError, match="validation exploded"):
        await scenario.actor.submit(_command(scenario))

    submit = _spans_by_name(span_exporter)["command.submit"]
    assert _span_status_name(submit) == "ERROR"
    assert submit.status.description == "operation failed"
    assert "error.description_sha256" in submit.attributes


@pytestmark_otel
def test_mark_span_error_without_description_uses_generic_status(otel_capture):
    span_exporter, _reader = otel_capture

    with telemetry.span("generic.error") as span:
        telemetry.mark_span_error(span=span)

    exported = _spans_by_name(span_exporter)["generic.error"]
    assert _span_status_name(exported) == "ERROR"
    assert exported.status.description == "operation failed"
    assert "error.description_sha256" not in exported.attributes


@pytestmark_otel
def test_trace_attributes_and_exceptions_never_export_private_values(otel_capture):
    span_exporter, _reader = otel_capture
    private = "claim-secret-memory-text"

    with telemetry.span(
        "redaction.check",
        {"chat.input": private, "claim_secret": private, "safe.id": "entity_123"},
    ) as span:
        span.set_attribute("decision.arguments", {"text": private})
        span.record_exception(RuntimeError(private))

    exported = _spans_by_name(span_exporter)["redaction.check"]
    serialized = str(
        {
            "attributes": dict(exported.attributes),
            "events": [dict(event.attributes) for event in exported.events],
        }
    )
    assert private not in serialized
    assert exported.attributes["safe.id"] == "entity_123"
    assert exported.attributes["chat.input"].startswith("[REDACTED sha256:")


@pytestmark_otel
async def test_prompt_filter_invocations_emit_redacted_child_spans(otel_capture):
    span_exporter, _reader = otel_capture
    scenario = build_scenario()
    character = scenario.actor.world.get_entity(scenario.character)
    filter_entity = spawn_entity(
        scenario.actor.world,
        [RedactedPromptFilterComponent(strength=1.0, targets=("private",))],
    )
    character.add_relationship(PromptFilterBinding(order=7), filter_entity.id)
    prompt = PromptBuilder(scenario.actor.world).build(scenario.character)
    private_input = "private prompt payload"

    private_failure = "private provider failure"

    async def failing_filter(text, context, component):
        del text, context, component
        raise RuntimeError(private_failure)

    with telemetry.span("agent.prompt.filter"):
        filtered = await PromptFilterRuntime(scenario.actor, BUILTIN_PROMPT_FILTERS).apply(
            private_input,
            character=character,
            prompt=prompt,
        )
        assert filtered == "- prompt payload"

        failed = await PromptFilterRuntime(
            scenario.actor,
            (
                PromptFilterDefinition(
                    id="example.prompt_filter.failure",
                    component_type=RedactedPromptFilterComponent,
                    handler=failing_filter,
                ),
            ),
        ).apply(private_input, character=character, prompt=prompt)
        assert failed == private_input

    spans = [
        span for span in span_exporter.get_finished_spans() if span.name == "prompt.filter.apply"
    ]
    assert len(spans) == 2
    parent = _spans_by_name(span_exporter)["agent.prompt.filter"]
    assert all(span.parent.span_id == parent.context.span_id for span in spans)
    by_filter = {span.attributes["prompt.filter.id"]: span for span in spans}
    applied = by_filter["bunnyland.prompt_filters.redacted"]
    assert applied.attributes["character.id"] == str(scenario.character)
    assert applied.attributes["prompt.filter.component"] == "RedactedPromptFilterComponent"
    assert applied.attributes["prompt.filter.entity_id"] == str(filter_entity.id)
    assert applied.attributes["prompt.filter.order"] == 7
    assert applied.attributes["prompt.filter.input_chars"] == len(private_input)
    assert applied.attributes["prompt.filter.output_chars"] == len(filtered)
    assert applied.attributes["prompt.filter.changed"] is True
    assert applied.attributes["prompt.filter.status"] == "applied"
    assert _span_status_name(applied) == "OK"

    failure = by_filter["example.prompt_filter.failure"]
    assert failure.attributes["prompt.filter.changed"] is False
    assert failure.attributes["prompt.filter.output_chars"] == len(private_input)
    assert failure.attributes["prompt.filter.status"] == "failed"
    assert _span_status_name(failure) == "ERROR"
    serialized = str(
        [
            {
                "attributes": dict(span.attributes),
                "events": [dict(event.attributes) for event in span.events],
            }
            for span in spans
        ]
    )
    assert private_input not in serialized
    assert private_failure not in serialized


@pytestmark_otel
async def test_dispatch_emits_agent_spans_and_decision_metric(otel_capture):
    span_exporter, reader = otel_capture
    scenario = build_scenario()
    dispatch = ControllerDispatch(
        scenario.actor,
        PromptBuilder(scenario.actor.world),
        ScriptedAgent([ToolCall("move", {"direction": "north"})]),
    )
    assert await dispatch.run_once() == []
    decisions = await dispatch.await_pending()
    assert [d.tool for d in decisions] == ["move"]

    spans = _spans_by_name(span_exporter)
    assert {"controller.run_once", "agent.prompt.build", "agent.decide"} <= set(spans)
    decide = spans["agent.decide"]
    assert decide.attributes["agent.kind"] == "ScriptedAgent"
    assert decide.attributes["decision.tool"] == "move"
    assert decide.attributes["character.id"] == str(scenario.character)
    # The scenario character is LLM-controlled, so the rendered prompt is captured.
    assert decide.attributes["decision.prompted"] is True
    assert decide.attributes["decision.prompt"].startswith("[REDACTED sha256:")
    assert decide.attributes["decision.arguments"].startswith("[REDACTED sha256:")

    run_once = spans["controller.run_once"]
    assert run_once.attributes["dispatch.actable_count"] == 1
    assert run_once.attributes["dispatch.decision_count"] == 0
    by_id = {s.context.span_id: s.name for s in span_exporter.get_finished_spans()}
    assert by_id[spans["agent.decide"].parent.span_id] == "controller.run_once"
    assert by_id[spans["agent.prompt.build"].parent.span_id] == "controller.run_once"
    # The chosen command is submitted through the single chokepoint, tied to the same trace.
    assert "command.submit" in spans
    assert spans["command.submit"].attributes["command.type"] == "move"
    assert by_id[spans["command.submit"].parent.span_id] == "controller.run_once"

    points = _metric_points(reader)
    assert "bunnyland.llm.decision.duration" in points


@pytestmark_otel
async def test_terminal_command_receipt_is_traced_and_reconciles_decision(otel_capture):
    span_exporter, _reader = otel_capture
    scenario = build_scenario()
    dispatch = ControllerDispatch(
        scenario.actor,
        PromptBuilder(scenario.actor.world),
        ScriptedAgent([ToolCall("move", {"direction": "north"})]),
    )

    await dispatch.run_once()
    decision = (await dispatch.await_pending())[0]
    await scenario.actor.tick(0)
    receipt = scenario.actor.receipt_for(decision.command_id)
    resolved = decision.with_receipt(receipt)

    terminal = _spans_by_name(span_exporter)["command.receipt"]
    assert terminal.attributes["command.id"] == decision.command_id
    assert terminal.attributes["command.status"] == "committed"
    assert terminal.attributes["command.result_event_ids"]
    assert resolved.receipt_status == "committed"
    assert resolved.result_event_ids == receipt.event_ids


@pytestmark_otel
async def test_behavior_controller_traces_evaluated_tree_nodes(otel_capture):
    span_exporter, _reader = otel_capture
    scenario = build_scenario()
    controller = spawn_entity(
        scenario.actor.world, [BehaviorControllerComponent(behavior_name="forager")]
    )
    scenario.actor.assign_controller(scenario.character, controller.id)
    dispatch = ControllerDispatch(
        scenario.actor,
        PromptBuilder(scenario.actor.world),
        ScriptedAgent([]),
    )

    assert await dispatch.run_once() == []
    decisions = await dispatch.await_pending()

    assert [decision.tool for decision in decisions] == ["move"]
    spans = span_exporter.get_finished_spans()
    by_name = _spans_by_name(span_exporter)
    decide = by_name["agent.decide"]
    tree = by_name["behavior_tree.tick"]
    nodes = [span for span in spans if span.name == "behavior_tree.node"]
    by_id = {span.context.span_id: span for span in spans}

    assert decide.attributes["behavior_tree.name"] == "forager"
    assert tree.attributes["behavior_tree.name"] == "forager"
    assert tree.attributes["character.id"] == str(scenario.character)
    assert tree.attributes["decision.tool"] == "move"
    assert by_id[tree.parent.span_id].name == "agent.decide"

    root = next(span for span in nodes if span.attributes["behavior_tree.node.kind"] == "selector")
    sequence = next(
        span for span in nodes if span.attributes["behavior_tree.node.kind"] == "sequence"
    )
    condition = next(
        span
        for span in nodes
        if span.attributes.get("behavior_tree.node.name") == "_has_visible_objects"
    )
    move = next(
        span
        for span in nodes
        if span.attributes.get("behavior_tree.node.name") == "_move_first_exit"
    )
    assert len(nodes) == 4
    assert root.attributes["behavior_tree.node.status"] == "success"
    assert sequence.attributes["behavior_tree.node.status"] == "failure"
    assert condition.attributes["behavior_tree.node.status"] == "failure"
    assert move.attributes["behavior_tree.node.status"] == "success"
    assert move.attributes["decision.tool"] == "move"
    assert by_id[root.parent.span_id].name == "behavior_tree.tick"
    assert by_id[sequence.parent.span_id] is root
    assert by_id[condition.parent.span_id] is sequence
    assert by_id[move.parent.span_id] is root


@pytestmark_otel
async def test_ollama_character_agent_records_provider_attempt_span(otel_capture, monkeypatch):
    span_exporter, reader = otel_capture

    class _FakeOllamaClient:
        async def chat(self, *, model, messages, tools):
            assert messages[0] == {"role": "system", "content": CHARACTER_SYSTEM_PROMPT}
            assert tools == [{"type": "function", "function": {"name": "wait"}}]
            return {
                "message": {
                    "role": "assistant",
                    "content": "ok",
                    "tool_calls": [{"function": {"name": "wait", "arguments": {}}}],
                },
                "prompt_eval_count": 5,
                "eval_count": 3,
            }

    fake_module = types.ModuleType("ollama")
    fake_module.AsyncClient = _FakeOllamaClient
    monkeypatch.setitem(sys.modules, "ollama", fake_module)

    with telemetry.span("agent.decide"):
        agent = OllamaAgent(model="llama3")
        assert await agent.decide(
            "turn one",
            None,
            character_id="hazel",
            tools=[{"type": "function", "function": {"name": "wait"}}],
        ) == ToolCall("wait", {})

    attempts = [
        span for span in span_exporter.get_finished_spans() if span.name == "llm.provider.attempt"
    ]
    assert len(attempts) == 1
    attrs = attempts[0].attributes
    assert attrs["provider"] == "ollama"
    assert attrs["model"] == "deepseek-v4-flash"
    assert attrs["llm.request.kind"] == "character"
    assert attrs["llm.tools.count"] == 1
    assert attrs["llm.history.messages"] == 2
    assert attrs["llm.system_prompt_chars"] == len(CHARACTER_SYSTEM_PROMPT)

    points = _metric_points(reader)
    assert points["bunnyland.llm.tokens.total"][0].value == 8


class _AsyncMoveAgent:
    """Async agent whose decision is optionally gated, for background-path telemetry tests."""

    def __init__(self, gate=None) -> None:
        self._gate = gate

    async def decide(self, prompt, context, *, character_id, model=None, provider=None, tools=None):
        del prompt, context, character_id, model, provider, tools
        if self._gate is not None:
            await self._gate.wait()
        return ToolCall("move", {"direction": "north"})


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

    decide_spans = [s for s in span_exporter.get_finished_spans() if s.name == "agent.decide"]
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
def test_record_llm_usage_emits_total_tokens_and_cost(otel_capture):
    _span_exporter, reader = otel_capture
    telemetry.record_llm_usage(
        "openrouter",
        "openai/test",
        40,
        12,
        total_tokens=52,
        cost=0.004,
    )

    points = _metric_points(reader)
    total = points["bunnyland.llm.tokens.total"][0]
    cost = points["bunnyland.llm.cost"][0]
    assert total.value == 52
    assert total.attributes == {"provider": "openrouter", "model": "openai/test"}
    assert cost.value == 0.004
    assert cost.attributes == {"provider": "openrouter", "model": "openai/test"}


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
    from bunnyland.worldgen import RoomNodeProposal
    from bunnyland.worldgen.recursive_builder import OllamaWorldAgent

    class _FakeOllamaClient:
        async def chat(self, **kwargs):
            del kwargs
            return {
                "message": {"role": "assistant", "content": '{"title":"Moss Room"}'},
                "prompt_eval_count": 11,
                "eval_count": 7,
            }

    agent = OllamaWorldAgent(model="deepseek-test")
    agent._client = _FakeOllamaClient()
    response = await agent._ask("describe the starting room", RoomNodeProposal)
    assert response.title == "Moss Room"

    spans = _spans_by_name(span_exporter)
    assert "worldgen.llm.request" in spans
    request = spans["worldgen.llm.request"]
    assert request.attributes["provider"] == "ollama"
    assert request.attributes["model"] == "deepseek-test"
    assert request.attributes["llm.request.kind"] == "worldgen"
    assert request.attributes["llm.tools.count"] == 0
    assert request.attributes["llm.history.messages"] == 2
    assert request.attributes["llm.system_prompt_chars"] > 0
    assert request.attributes["instruction.chars"] > 0
    assert request.attributes["llm.tokens.prompt"] == 11
    assert request.attributes["llm.tokens.completion"] == 7
    assert request.attributes["llm.tokens.total"] == 18

    points = _metric_points(reader)
    assert "bunnyland.worldgen.request.duration" in points
    tokens = points["bunnyland.llm.tokens.prompt"][0]
    assert tokens.value == 11
    assert tokens.attributes == {"provider": "ollama", "model": "deepseek-test"}
    total = points["bunnyland.llm.tokens.total"][0]
    assert total.value == 18
    assert total.attributes == {"provider": "ollama", "model": "deepseek-test"}


@pytestmark_otel
async def test_openrouter_worldgen_llm_request_records_provider_cost(otel_capture, monkeypatch):
    span_exporter, reader = otel_capture
    from bunnyland.worldgen import RoomNodeProposal
    from bunnyland.worldgen.recursive_builder import OpenRouterWorldAgent

    class _FakeOpenRouterChat:
        async def send_async(self, **kwargs):
            del kwargs
            message = types.SimpleNamespace(
                role="assistant",
                content='{"title":"Moss Room"}',
                model_dump=lambda **_: {
                    "role": "assistant",
                    "content": '{"title":"Moss Room"}',
                },
            )
            usage = types.SimpleNamespace(
                prompt_tokens=6,
                completion_tokens=4,
                total_tokens=10,
                cost=0.002,
            )
            return types.SimpleNamespace(
                choices=[types.SimpleNamespace(message=message)], usage=usage
            )

    class _FakeOpenRouterClient:
        def __init__(self, **kwargs):
            del kwargs
            self.chat = _FakeOpenRouterChat()

    fake_module = types.ModuleType("openrouter")
    fake_module.OpenRouter = _FakeOpenRouterClient
    monkeypatch.setitem(sys.modules, "openrouter", fake_module)

    agent = OpenRouterWorldAgent(model="openai/test", api_key="key")
    response = await agent._ask("describe the starting room", RoomNodeProposal)
    assert response.title == "Moss Room"

    request = _spans_by_name(span_exporter)["worldgen.llm.request"]
    assert request.attributes["provider"] == "openrouter"
    assert request.attributes["llm.tokens.total"] == 10
    assert request.attributes["llm.cost"] == 0.002

    points = _metric_points(reader)
    cost = points["bunnyland.llm.cost"][0]
    assert cost.value == 0.002
    assert cost.attributes == {"provider": "openrouter", "model": "openai/test"}


@pytestmark_otel
async def test_save_and_load_emit_persistence_spans_and_metrics(otel_capture, tmp_path):
    from bunnyland.core import WorldActor
    from bunnyland.persistence import WorldMeta, load_world, save_world
    from bunnyland.plugins import PluginRegistry, apply_plugins, bunnyland_plugins
    from bunnyland.worldgen import StubWorldBuilder, instantiate

    span_exporter, reader = otel_capture
    actor = WorldActor()
    apply_plugins(bunnyland_plugins(), actor)
    await instantiate(actor, await StubWorldBuilder().propose("a quiet marsh"))

    path = tmp_path / "world.json"
    save_world(actor, path, meta=WorldMeta(seed="a quiet marsh", generator="stub"))
    load_world(path, registry=PluginRegistry(bunnyland_plugins()))

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
async def test_save_world_marks_span_error_on_write_failure(otel_capture, tmp_path):
    from bunnyland.core import WorldActor
    from bunnyland.persistence import WorldMeta, save_world

    span_exporter, _reader = otel_capture
    actor = WorldActor()
    blocked_parent = tmp_path / "not-a-directory"
    blocked_parent.write_text("file")

    with pytest.raises(OSError):
        save_world(actor, blocked_parent / "world.json", meta=WorldMeta(seed="broken"))

    save_span = _spans_by_name(span_exporter)["world.save"]
    assert _span_status_name(save_span) == "ERROR"
    assert save_span.status.description


@pytestmark_otel
async def test_mcp_save_world_admin_traces_status(otel_capture, monkeypatch, tmp_path):
    from bunnyland.mcp.server import create_bunnyland_mcp_app
    from bunnyland.persistence import WorldMeta

    span_exporter, _reader = otel_capture
    scenario = build_scenario()
    registered_tools = {}

    class FakeLowServer:
        def __init__(self):
            self.get_capabilities = lambda _n, _e: types.SimpleNamespace(resources=None)

        def subscribe_resource(self):
            return lambda func: func

        def unsubscribe_resource(self):
            return lambda func: func

    class FakeFastMCP:
        def __init__(self, *_args, **_kwargs):
            self._mcp_server = FakeLowServer()

        def tool(self):
            def decorate(func):
                registered_tools[func.__name__] = func
                return func

            return decorate

        def resource(self, _uri, **_kwargs):
            return lambda func: func

        def get_context(self):
            principal = TokenPrincipal(
                token_id="test-token",
                subject="test-admin",
                scopes=frozenset({WORLD_ADMIN_SCOPE}),
                created_at=1,
                rotate_after=None,
                expires_at=2**31,
                automatic_rotation=False,
                family_id="test-family",
            )
            return types.SimpleNamespace(
                request_context=types.SimpleNamespace(
                    request=types.SimpleNamespace(
                        headers={},
                        state=types.SimpleNamespace(auth_principal=principal),
                    )
                )
            )

        def streamable_http_app(self):
            return types.SimpleNamespace()

    fastmcp_module = types.ModuleType("mcp.server.fastmcp")
    exceptions_module = types.ModuleType("mcp.server.fastmcp.exceptions")
    fastmcp_module.FastMCP = FakeFastMCP
    exceptions_module.ToolError = RuntimeError
    monkeypatch.setitem(sys.modules, "mcp", types.ModuleType("mcp"))
    monkeypatch.setitem(sys.modules, "mcp.server", types.ModuleType("mcp.server"))
    monkeypatch.setitem(sys.modules, "mcp.server.fastmcp", fastmcp_module)
    monkeypatch.setitem(sys.modules, "mcp.server.fastmcp.exceptions", exceptions_module)

    async def unused(*_args, **_kwargs):
        raise AssertionError("not used by save_world_admin")

    path = tmp_path / "world.json"
    create_bunnyland_mcp_app(
        actor=scenario.actor,
        meta=WorldMeta(seed="moss"),
        loop=None,
        save_path=path,
        patch_world=unused,
        generate_world=unused,
        generation_status=unused,
        generate_room=unused,
        generate_character=unused,
        generate_item=unused,
        generate_event=unused,
    )

    saved = await registered_tools["admin_save_world"]()

    assert saved["path"] == str(path)
    assert path.exists()
    spans = _spans_by_name(span_exporter)
    assert _span_status_name(spans["mcp.admin_save_world"]) == "OK"
    assert _span_status_name(spans["world.save"]) == "OK"
    assert spans["world.save"].attributes["path"] == str(path)


@pytestmark_otel
async def test_rest_snapshot_emits_child_span_under_request(otel_capture):
    pytest.importorskip("fastapi")

    from bunnyland.core import WorldActor
    from bunnyland.persistence import WorldMeta
    from bunnyland.server.app import create_app

    span_exporter, _reader = otel_capture
    actor = WorldActor()
    app = create_app(
        actor,
        meta=WorldMeta(seed="s", generator="stub"),
        allow_unauthenticated_embedding=True,
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get(
            "/v1/admin/world/snapshot",
            headers={"X-Bunnyland-Client-Id": "admin-client"},
        )
        assert response.status_code == 200

    assert "world.snapshot" in _spans_by_name(span_exporter)


@pytestmark_otel
async def test_character_chat_traces_input_reply_and_status(otel_capture):
    span_exporter, _reader = otel_capture
    scenario = build_scenario()
    agent = _FakeTelemetryChatAgent([ChatAgentReply(content="I hear the tunnel.")])
    service = _chat_service(scenario, agent)

    with telemetry.span("character.chat", {"character.id": str(scenario.character)}) as span:
        response = await service.chat(
            str(scenario.character),
            CharacterChatRequest(client_id="trace-client", message="what do you hear?"),
        )
        telemetry.mark_span_ok(span)

    assert response.reply == "I hear the tunnel."
    spans = _spans_by_name(span_exporter)
    assert {
        "character.chat",
        "character.chat.validate",
        "character.chat.prompt",
        "character.chat.llm",
    } <= set(spans)
    for name in (
        "character.chat",
        "character.chat.validate",
        "character.chat.prompt",
        "character.chat.llm",
    ):
        assert _span_status_name(spans[name]) == "OK"

    chat = spans["character.chat"]
    assert chat.attributes["chat.client_id"] == "trace-client"
    assert chat.attributes["chat.input"].startswith("[REDACTED sha256:")
    assert chat.attributes["chat.input_chars"] == len("what do you hear?")
    assert chat.attributes["chat.final_reply"].startswith("[REDACTED sha256:")
    assert chat.attributes["chat.action.status"] == "none"
    prompt = spans["character.chat.prompt"]
    assert prompt.attributes["chat.prompt"].startswith("[REDACTED sha256:")
    assert prompt.attributes["chat.prompt_chars"] > 0
    llm = spans["character.chat.llm"]
    assert llm.attributes["chat.phase"] == "initial"
    assert llm.attributes["llm.input"].startswith("[REDACTED sha256:")
    assert llm.attributes["chat.reply"].startswith("[REDACTED sha256:")
    assert llm.attributes["chat.tool.called"] is False


@pytestmark_otel
async def test_character_chat_traces_tool_usage_and_command_submit_status(otel_capture):
    span_exporter, _reader = otel_capture
    scenario = build_scenario()
    scenario.actor.register_action_definition(ActionDefinition("wait", tool_name="wait"))
    agent = _FakeTelemetryChatAgent(
        [
            ChatAgentReply(content="", tool_call=ToolCall("wait", {})),
            ChatAgentReply(content="I wait for a moment."),
        ]
    )
    service = _chat_service(scenario, agent)

    with telemetry.span("character.chat", {"character.id": str(scenario.character)}) as span:
        response = await service.chat(
            str(scenario.character),
            CharacterChatRequest(client_id="trace-client", message="wait here"),
        )
        telemetry.mark_span_ok(span)

    assert response.action.status == "rejected"
    spans = span_exporter.get_finished_spans()
    by_name = _spans_by_name(span_exporter)
    llm_spans = [span for span in spans if span.name == "character.chat.llm"]
    assert len(llm_spans) == 2
    assert {span.attributes["chat.phase"] for span in llm_spans} == {"initial", "followup"}
    for span in llm_spans:
        assert _span_status_name(span) == "OK"

    tool = by_name["character.chat.tool"]
    assert _span_status_name(tool) == "OK"
    assert tool.attributes["chat.tool.name"] == "wait"
    assert tool.attributes["chat.tool.arguments"].startswith("[REDACTED sha256:")
    assert tool.attributes["chat.action.status"] == "rejected"
    assert tool.attributes["chat.action.reason"] == "no handler for wait"

    submit = by_name["command.submit"]
    assert _span_status_name(submit) == "ERROR"
    assert submit.attributes["command.type"] == "wait"
    assert submit.attributes["command.accepted"] is False
    assert submit.attributes["command.reject_reason_text"].startswith("[REDACTED sha256:")
    chat = by_name["character.chat"]
    assert chat.attributes["chat.initial.tool_called"] is True
    assert chat.attributes["chat.initial.tool_name"] == "wait"
    assert chat.attributes["chat.followup.reply"].startswith("[REDACTED sha256:")
    assert chat.attributes["chat.action.status"] == "rejected"


@pytestmark_otel
async def test_controller_assign_endpoint_is_traced(otel_capture):
    pytest.importorskip("fastapi")
    from bunnyland.server.app import create_app
    from bunnyland.server.v1_models import ControllerAssignment

    span_exporter, _reader = otel_capture
    scenario = build_scenario()
    app = create_app(scenario.actor, allow_unauthenticated_embedding=True)
    route = next(
        route
        for route in app.routes
        if getattr(route, "path", None) == "/v1/admin/characters/{character_id}/controller"
    )
    await route.endpoint(
        str(scenario.character),
        ControllerAssignment(controller_id=str(scenario.controller)),
    )

    span = _spans_by_name(span_exporter)["controller.assign"]
    assert span.attributes["character.id"] == str(scenario.character)
    assert span.attributes["controller.id"] == str(scenario.controller)


@pytestmark_otel
async def test_web_controller_claim_endpoint_reports_client_id_in_trace(otel_capture):
    pytest.importorskip("fastapi")
    from bunnyland.server.app import create_app

    span_exporter, _reader = otel_capture
    scenario = build_scenario()
    app = create_app(scenario.actor, allow_unauthenticated_embedding=True)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(
            "/v1/play/claims",
            headers={"X-Bunnyland-Client-Id": "client-a"},
            json={
                "character_id": str(scenario.character),
                "label": "toon",
            },
        )
    assert response.status_code == 201
    body = response.json()

    span = _spans_by_name(span_exporter)["controller.web_claim"]
    assert span.attributes["character.id"] == str(scenario.character)
    assert span.attributes["client.id"] == "client-a"
    assert span.attributes["client.label"] == "toon"
    assert span.attributes["controller.id"] == body["controller_id"]
    assert span.attributes["controller.generation"] == body["controller_generation"]


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


# -- high-signal background and integration boundaries ---------------------------------


def _serialized_spans(span_exporter) -> str:
    return str(
        [
            {
                "name": span.name,
                "attributes": dict(span.attributes),
                "events": [dict(event.attributes) for event in span.events],
            }
            for span in span_exporter.get_finished_spans()
        ]
    )


@pytestmark_otel
def test_captured_context_can_parent_later_work(otel_capture):
    span_exporter, _reader = otel_capture

    with telemetry.span("submit.root") as root_span:
        context = telemetry.capture_context()
        root_span_id = root_span.get_span_context().span_id
    with telemetry.span("background.work", parent_context=context):
        pass

    background = _spans_by_name(span_exporter)["background.work"]
    assert background.parent.span_id == root_span_id


class _TelemetryImageGenerator:
    name = "telemetry-image"

    def __init__(self, *, error: Exception | None = None, gate: asyncio.Event | None = None):
        self.error = error
        self.gate = gate
        self.started = asyncio.Event()

    def resolve_profile(self, purpose, profile_name=""):
        from bunnyland.imagegen.generators import ImageGeneratorProfile

        if profile_name and profile_name != purpose.value:
            raise ValueError("unknown telemetry image profile")
        return ImageGeneratorProfile(
            name=purpose.value,
            purpose=purpose,
            width=8,
            height=6,
        )

    async def generate(self, request):
        del request
        self.started.set()
        if self.gate is not None:
            await self.gate.wait()
        if self.error is not None:
            raise self.error
        return b"private-image-bytes"


def _telemetry_image_service(actor, tmp_path, generator, *, enhancer=None, alpha=None):
    from bunnyland.imagegen.config import ImageGenConfig
    from bunnyland.imagegen.media import MediaStore
    from bunnyland.imagegen.prompt import CatalogExampleSource, StubPromptEnhancer
    from bunnyland.imagegen.service import ImageGenService
    from bunnyland.imagegen.spec import ImagePurpose

    return ImageGenService(
        actor,
        ImageGenConfig(),
        generators={purpose: generator for purpose in ImagePurpose},
        enhancer=enhancer or StubPromptEnhancer(),
        examples=CatalogExampleSource(),
        media=MediaStore(tmp_path),
        alpha=alpha,
    )


@pytestmark_otel
async def test_image_jobs_keep_each_submitting_trace_and_emit_child_spans(
    otel_capture, tmp_path, monkeypatch
):
    from bunnyland.core.components import CharacterComponent, IdentityComponent
    from bunnyland.imagegen.spec import ImagePurpose

    span_exporter, _reader = otel_capture

    async def run_inline(function, *args):
        return function(*args)

    monkeypatch.setattr(asyncio, "to_thread", run_inline)
    scenario = build_scenario()
    second = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="Clover", kind="character"), CharacterComponent()],
    )
    generator = _TelemetryImageGenerator()
    service = _telemetry_image_service(
        scenario.actor, tmp_path, generator, alpha=lambda _data: b"alpha-bytes"
    )

    with telemetry.span("submit.one"):
        first = await service.start(str(scenario.character), ImagePurpose.PORTRAIT, alpha=True)
    with telemetry.span("submit.two"):
        second_job = await service.start(str(second.id), ImagePurpose.PORTRAIT)
    await service.wait_idle()
    await service.aclose()

    spans = span_exporter.get_finished_spans()
    roots = {span.name: span for span in spans if span.name.startswith("submit.")}
    enqueues = {
        span.attributes["image.job_id"]: span
        for span in spans
        if span.name == "image.generate.enqueue"
    }
    generations = {
        span.attributes["image.job_id"]: span for span in spans if span.name == "image.generate"
    }
    assert generations[first.job_id].context.trace_id == roots["submit.one"].context.trace_id
    assert generations[second_job.job_id].context.trace_id == roots["submit.two"].context.trace_id
    assert generations[first.job_id].parent.span_id == enqueues[first.job_id].context.span_id
    assert (
        generations[second_job.job_id].parent.span_id == enqueues[second_job.job_id].context.span_id
    )
    assert enqueues[first.job_id].parent.span_id == roots["submit.one"].context.span_id
    assert enqueues[second_job.job_id].parent.span_id == roots["submit.two"].context.span_id

    children = [
        span
        for span in spans
        if span.parent is not None
        and span.parent.span_id == generations[first.job_id].context.span_id
    ]
    assert {span.name for span in children} == {
        "image.prompt.enhance",
        "image.provider.generate",
        "image.postprocess",
    }
    assert generations[first.job_id].attributes["image.width"] == 8
    assert generations[first.job_id].attributes["image.height"] == 6
    assert generations[first.job_id].attributes["image.outcome"] == "succeeded"
    postprocess = next(span for span in children if span.name == "image.postprocess")
    assert postprocess.attributes["image.alpha.applied"] is True
    assert postprocess.attributes["image.alpha.output.bytes"] == len(b"alpha-bytes")
    assert _span_status_name(generations[first.job_id]) == "OK"


@pytestmark_otel
async def test_image_enqueue_records_duplicate_skipped_and_rejected(otel_capture, tmp_path):
    from bunnyland.imagegen.spec import ImagePurpose

    span_exporter, _reader = otel_capture
    scenario = build_scenario()
    gate = asyncio.Event()
    generator = _TelemetryImageGenerator(gate=gate)
    service = _telemetry_image_service(scenario.actor, tmp_path, generator)

    queued = await service.start(str(scenario.character), ImagePurpose.PORTRAIT)
    await generator.started.wait()
    duplicate = await service.start(str(scenario.character), ImagePurpose.PORTRAIT)
    rejected = await service.start("not-an-entity", ImagePurpose.PORTRAIT)
    gate.set()
    await service.wait_idle()
    skipped = await service.start(str(scenario.character), ImagePurpose.PORTRAIT)
    await service.aclose()

    assert [queued.status, duplicate.status, rejected.status, skipped.status] == [
        "succeeded",
        "duplicate",
        "failed",
        "skipped",
    ]
    outcomes = [
        span.attributes["image.outcome"]
        for span in span_exporter.get_finished_spans()
        if span.name == "image.generate.enqueue"
    ]
    assert outcomes == ["queued", "duplicate", "rejected", "skipped"]


@pytestmark_otel
async def test_image_provider_and_enhancer_failures_are_error_spans_and_redacted(
    otel_capture, tmp_path
):
    from bunnyland.imagegen.spec import ImagePurpose

    private = "private image prompt and provider payload"
    span_exporter, _reader = otel_capture
    scenario = build_scenario()
    provider_service = _telemetry_image_service(
        scenario.actor,
        tmp_path / "provider",
        _TelemetryImageGenerator(error=RuntimeError(private)),
    )
    provider_job = await provider_service.start(str(scenario.character), ImagePurpose.PORTRAIT)
    await provider_service.wait_idle()
    await provider_service.aclose()

    class _FailingEnhancer:
        name = "failing"

        async def enhance(self, request, *, examples=()):
            del request, examples
            raise RuntimeError(private)

    enhancer_service = _telemetry_image_service(
        scenario.actor,
        tmp_path / "enhancer",
        _TelemetryImageGenerator(),
        enhancer=_FailingEnhancer(),
    )
    enhancer_job = await enhancer_service.start(
        str(scenario.character), ImagePurpose.PORTRAIT, force=True
    )
    await enhancer_service.wait_idle()
    await enhancer_service.aclose()

    assert provider_job.status == enhancer_job.status == "failed"
    spans = span_exporter.get_finished_spans()
    provider_span = next(span for span in spans if span.name == "image.provider.generate")
    enhance_spans = [span for span in spans if span.name == "image.prompt.enhance"]
    generation_spans = [span for span in spans if span.name == "image.generate"]
    assert _span_status_name(provider_span) == "ERROR"
    assert any(_span_status_name(span) == "ERROR" for span in enhance_spans)
    assert all(_span_status_name(span) == "ERROR" for span in generation_spans)
    assert private not in _serialized_spans(span_exporter)


@pytestmark_otel
async def test_ollama_image_prompt_attempt_records_usage_under_enhancement(otel_capture):
    from bunnyland.imagegen.prompt import ImagePromptRequest, LLMPromptEnhancer
    from bunnyland.imagegen.spec import ImagePurpose, PromptStyle

    span_exporter, reader = otel_capture

    class _Client:
        async def chat(self, **kwargs):
            assert kwargs["messages"][1]["content"]
            return {
                "message": {"content": '{"prompt":"painted rabbit"}'},
                "prompt_eval_count": 4,
                "eval_count": 2,
            }

    enhancer = LLMPromptEnhancer.__new__(LLMPromptEnhancer)
    enhancer._client = _Client()
    enhancer._model = "image-model"
    request = ImagePromptRequest(
        subject="private subject text",
        style=PromptStyle.NATURAL,
        purpose=ImagePurpose.PORTRAIT,
    )
    with telemetry.span("image.prompt.enhance") as enhancement:
        result = await enhancer.enhance(request)
        telemetry.mark_span_ok(enhancement)

    assert result.prompt == "painted rabbit"
    spans = _spans_by_name(span_exporter)
    attempt = spans["llm.provider.attempt"]
    assert attempt.parent.span_id == spans["image.prompt.enhance"].context.span_id
    assert attempt.attributes["provider"] == "ollama"
    assert attempt.attributes["llm.request.kind"] == "image_prompt"
    assert attempt.attributes["llm.tokens.prompt"] == 4
    assert attempt.attributes["llm.tokens.completion"] == 2
    assert "private subject text" not in _serialized_spans(span_exporter)
    points = _metric_points(reader)
    assert points["bunnyland.llm.tokens.total"][0].value == 6


@pytestmark_otel
async def test_ollama_image_prompt_attempt_marks_provider_failure(otel_capture):
    from bunnyland.imagegen.prompt import ImagePromptRequest, LLMPromptEnhancer
    from bunnyland.imagegen.spec import ImagePurpose, PromptStyle

    private = "private provider credential detail"
    span_exporter, _reader = otel_capture

    class _Client:
        async def chat(self, **kwargs):
            del kwargs
            raise RuntimeError(private)

    enhancer = LLMPromptEnhancer.__new__(LLMPromptEnhancer)
    enhancer._client = _Client()
    enhancer._model = "image-model"
    with pytest.raises(RuntimeError, match="private provider"):
        await enhancer.enhance(
            ImagePromptRequest(
                subject="subject",
                style=PromptStyle.TAG,
                purpose=ImagePurpose.SPRITE,
            )
        )

    attempt = _spans_by_name(span_exporter)["llm.provider.attempt"]
    assert _span_status_name(attempt) == "ERROR"
    assert private not in _serialized_spans(span_exporter)


@pytestmark_otel
async def test_one_shot_ollama_worldgen_records_usage_and_redacts_seed(otel_capture):
    from bunnyland.worldgen.ollama_builder import OllamaWorldBuilder

    private_seed = "private world seed narration"
    span_exporter, reader = otel_capture

    class _Client:
        async def chat(self, **kwargs):
            del kwargs
            return {
                "message": {
                    "content": json.dumps(
                        {
                            "seed": "ignored",
                            "rooms": [{"key": "moss", "title": "Moss Room"}],
                        }
                    )
                },
                "prompt_eval_count": 9,
                "eval_count": 3,
            }

    builder = OllamaWorldBuilder.__new__(OllamaWorldBuilder)
    builder._client = _Client()
    builder._model = "world-model"
    proposal = await builder.propose(private_seed)

    assert proposal.seed == private_seed
    request = _spans_by_name(span_exporter)["worldgen.llm.request"]
    assert _span_status_name(request) == "OK"
    assert request.attributes["provider"] == "ollama"
    assert request.attributes["llm.tokens.total"] == 12
    assert request.attributes["worldgen.seed.chars"] == len(private_seed)
    assert private_seed not in _serialized_spans(span_exporter)
    points = _metric_points(reader)
    assert points["bunnyland.worldgen.request.duration"][0].attributes["provider"] == "ollama"


@pytestmark_otel
async def test_one_shot_ollama_worldgen_marks_invalid_response_error(otel_capture):
    from bunnyland.worldgen.ollama_builder import OllamaWorldBuilder

    span_exporter, _reader = otel_capture

    class _Client:
        async def chat(self, **kwargs):
            del kwargs
            return {"message": {"content": "private invalid proposal"}}

    builder = OllamaWorldBuilder.__new__(OllamaWorldBuilder)
    builder._client = _Client()
    builder._model = "world-model"
    with pytest.raises(ValueError):
        await builder.propose("seed")

    request = _spans_by_name(span_exporter)["worldgen.llm.request"]
    assert _span_status_name(request) == "ERROR"
    assert "private invalid proposal" not in _serialized_spans(span_exporter)


@pytestmark_otel
async def test_narration_render_traces_success_timeout_and_exception_fallbacks(otel_capture):
    from bunnyland.narration.projection import NarrationProjection, SceneInput

    private = "private narration renderer failure"
    span_exporter, _reader = otel_capture
    scenario = build_scenario()
    scene = SceneInput(
        viewer_id=str(scenario.character),
        room_id=str(scenario.room_a),
        location_title="Moss Room",
        room_summary="private scene narration",
    )
    projection = NarrationProjection(world=scenario.actor.world, fallback_renderer=lambda _: "safe")

    projection.renderer = lambda _scene: "rendered"
    await projection._deliver(scene.viewer_id, 1, scene)

    async def slow(_scene):
        await asyncio.sleep(0.02)
        return "late"

    projection.renderer = slow
    projection.render_timeout_seconds = 0.001
    await projection._deliver(scene.viewer_id, 2, scene)

    def fail(_scene):
        raise RuntimeError(private)

    projection.renderer = fail
    await projection._deliver(scene.viewer_id, 3, scene)

    renders = [
        span for span in span_exporter.get_finished_spans() if span.name == "narration.render"
    ]
    assert [span.attributes["narration.outcome"] for span in renders] == [
        "succeeded",
        "timeout_fallback",
        "exception_fallback",
    ]
    assert [_span_status_name(span) for span in renders] == ["OK", "ERROR", "ERROR"]
    assert projection.latest(scene.viewer_id).epoch == 3
    assert projection.latest(scene.viewer_id).text == "safe"
    assert private not in _serialized_spans(span_exporter)
    assert "private scene narration" not in _serialized_spans(span_exporter)


class _TelemetryChromaCollection:
    def __init__(self):
        self.rows: list[tuple[str, str, dict]] = []

    def add(self, *, ids, documents, metadatas):
        self.rows.extend(zip(ids, documents, metadatas, strict=False))

    def get(self, ids=None, include=None):
        del include
        selected = set(ids or [row[0] for row in self.rows])
        rows = [row for row in self.rows if row[0] in selected]
        return {
            "ids": [row[0] for row in rows],
            "documents": [row[1] for row in rows],
            "metadatas": [row[2] for row in rows],
        }

    def query(self, *, query_texts, n_results):
        del query_texts
        got = self.get()
        return {key: [values[:n_results]] for key, values in got.items()}

    def update(self, *, ids, documents, metadatas):
        selected = set(ids)
        self.rows = [
            (
                row[0],
                documents[0] if row[0] in selected else row[1],
                metadatas[0] if row[0] in selected else row[2],
            )
            for row in self.rows
        ]

    def delete(self, *, ids):
        selected = set(ids)
        self.rows = [row for row in self.rows if row[0] not in selected]


class _TelemetryChromaClient:
    def __init__(self):
        self.collection = _TelemetryChromaCollection()

    def get_or_create_collection(self, *, name, **kwargs):
        del name, kwargs
        return self.collection


@pytestmark_otel
def test_json_and_chroma_memory_backend_spans_are_content_free(otel_capture, tmp_path):
    from bunnyland.memory.chroma import ChromaMemoryStore
    from bunnyland.memory.jsonfile import JsonMemoryStore

    private = "private remembered document content"
    span_exporter, _reader = otel_capture
    path = tmp_path / "memory.json"
    json_store = JsonMemoryStore(path)
    json_store.add("private-collection", text=private, created_at_epoch=1)
    JsonMemoryStore(path)

    chroma = ChromaMemoryStore(client=_TelemetryChromaClient())
    entry = chroma.add("private-collection", text=private, created_at_epoch=1)
    assert chroma.search("private-collection", query=private, mode="vector")
    document = chroma.create_document(
        "private-collection", document=private, metadata={"tags": "private"}
    )
    assert chroma.list_documents("private-collection")
    assert (
        chroma.update_document("private-collection", document.id, document=private, metadata={})
        is not None
    )
    assert (
        chroma.update_document("private-collection", "missing", document=private, metadata={})
        is None
    )
    assert chroma.delete("private-collection", entry.id) is True
    assert chroma.delete("private-collection", entry.id) is False

    spans = [span for span in span_exporter.get_finished_spans() if span.name == "memory.backend"]
    assert {span.attributes["memory.backend"] for span in spans} == {"json", "chroma"}
    assert {span.attributes["memory.operation"] for span in spans} >= {
        "load",
        "save",
        "add",
        "search",
        "create",
        "list",
        "update",
        "delete",
    }
    assert all(_span_status_name(span) == "OK" for span in spans)
    assert private not in _serialized_spans(span_exporter)
    assert "private-collection" not in _serialized_spans(span_exporter)


@pytestmark_otel
def test_memory_backend_failure_marks_error_and_redacts_content(otel_capture, tmp_path):
    from bunnyland.memory.chroma import ChromaMemoryStore
    from bunnyland.memory.jsonfile import JsonMemoryStore

    private = "private corrupt memory payload"
    span_exporter, _reader = otel_capture
    invalid = tmp_path / "invalid.json"
    invalid.write_text(private)
    with pytest.raises(json.JSONDecodeError):
        JsonMemoryStore(invalid)

    class _FailingClient:
        def get_or_create_collection(self, **kwargs):
            del kwargs
            raise RuntimeError(private)

    with pytest.raises(RuntimeError, match="private corrupt"):
        ChromaMemoryStore(client=_FailingClient()).search("collection")

    failures = [
        span
        for span in span_exporter.get_finished_spans()
        if span.name == "memory.backend" and _span_status_name(span) == "ERROR"
    ]
    assert len(failures) == 2
    assert private not in _serialized_spans(span_exporter)


@pytestmark_otel
def test_auth_store_initialization_and_mutations_are_traced_without_subjects(
    otel_capture, tmp_path
):
    from bunnyland.server.auth import HUMAN_ROTATE_AFTER_SECONDS, TokenStore

    private_subject = "private-token-subject"
    span_exporter, _reader = otel_capture
    store = TokenStore(tmp_path / "tokens.sqlite3")
    token, principal = store.issue(
        private_subject,
        [WORLD_ADMIN_SCOPE],
        automatic_rotation=True,
        now=0,
    )
    store.rotate(token, now=HUMAN_ROTATE_AFTER_SECONDS)
    store.import_digest(
        "0123456789abcdef",
        "a" * 64,
        private_subject,
        [WORLD_ADMIN_SCOPE],
        expires_at=999999,
        created_at=1,
    )
    store.replace(principal.token_id, now=HUMAN_ROTATE_AFTER_SECONDS + 1)
    store.revoke_token("0123456789abcdef", now=2)
    store.revoke_subject(private_subject, now=3)
    with pytest.raises(PermissionError):
        store.rotate("private-invalid-token", now=4)
    store.close()

    spans = span_exporter.get_finished_spans()
    initialize = next(span for span in spans if span.name == "auth.token_store.initialize")
    mutations = [span for span in spans if span.name == "auth.token.mutate"]
    assert _span_status_name(initialize) == "OK"
    assert {span.attributes["auth.operation"] for span in mutations} >= {
        "issue",
        "import",
        "rotate",
        "replace",
        "revoke",
    }
    assert any(_span_status_name(span) == "ERROR" for span in mutations)
    assert private_subject not in _serialized_spans(span_exporter)
    assert token not in _serialized_spans(span_exporter)


@pytestmark_otel
def test_auth_store_initialization_failure_marks_error(otel_capture, tmp_path):
    from bunnyland.server.auth import TokenStore

    span_exporter, _reader = otel_capture
    with pytest.raises(sqlite3.OperationalError):
        TokenStore(tmp_path)
    initialize = _spans_by_name(span_exporter)["auth.token_store.initialize"]
    assert _span_status_name(initialize) == "ERROR"


@pytestmark_otel
def test_plugin_apply_and_integrate_trace_success_and_failure(otel_capture):
    from bunnyland.core import WorldActor
    from bunnyland.plugins import Plugin, RuntimeContribution, apply_plugin, apply_plugins

    private = "private plugin integration failure"
    span_exporter, _reader = otel_capture

    def integrate(_actor):
        return None

    plugin = Plugin(
        id="test.telemetry",
        name="Telemetry",
        runtime=RuntimeContribution(integration_factories=(integrate,)),
    )
    apply_plugins([plugin], WorldActor())

    def fail(_actor):
        raise RuntimeError(private)

    failing = Plugin(
        id="test.failure",
        name="Failure",
        runtime=RuntimeContribution(service_factories=(fail,)),
    )
    with pytest.raises(RuntimeError, match="private plugin"):
        apply_plugin(failing, WorldActor())

    apply_spans = [
        span for span in span_exporter.get_finished_spans() if span.name == "plugin.apply"
    ]
    integrate_span = _spans_by_name(span_exporter)["plugin.integrate"]
    assert [_span_status_name(span) for span in apply_spans] == ["OK", "ERROR"]
    assert _span_status_name(integrate_span) == "OK"
    assert integrate_span.attributes["plugin.factories.count"] == 1
    assert private not in _serialized_spans(span_exporter)


@pytestmark_otel
async def test_discord_command_and_delivery_spans_capture_outcomes_without_messages(
    otel_capture, monkeypatch
):
    import bunnyland.discord.bot as bot_module
    from bunnyland.discord.bot import DiscordBot, DiscordCommandCooldown

    private = "private discord message body"
    span_exporter, _reader = otel_capture
    scenario = build_scenario()
    bot = object.__new__(DiscordBot)
    bot.actor = scenario.actor
    bot.command_cooldown = DiscordCommandCooldown()

    class _Context:
        def __init__(self):
            self.author = types.SimpleNamespace(id=123, mention="<@123>")
            self.channel = types.SimpleNamespace(id=456)
            self.message = types.SimpleNamespace()
            self.replies = []

        async def reply(self, body, mention_author=False):
            self.replies.append((body, mention_author))

    submitted = []

    async def submit_action(_ctx, action):
        submitted.append(action)
        return "submitted"

    bot._submit_action = submit_action
    ctx = _Context()
    await bot.handle_text_command(ctx, "unknown " + private)
    await bot.handle_text_command(ctx, "move north")

    class _Channel:
        def __init__(self):
            self.messages = []

        async def send(self, message):
            self.messages.append(message)

    channel = _Channel()

    class _Client:
        user = "bot"

        def get_channel(self, channel_id):
            return channel if channel_id == 1 else None

        async def fetch_channel(self, channel_id):
            raise RuntimeError(f"private delivery failure {channel_id}")

    bot.client = _Client()
    await bot._send_room_feed_message(1, private)
    await bot._send_room_feed_message(2, private)

    bot._world_paused = False
    bot._paused_reactions = {}
    monkeypatch.setattr(bot_module, "discord_broadcast_channel_ids", lambda _actor: (1, 2))
    await bot._post_pause_status(types.SimpleNamespace(paused=True, message=private))

    commands = [
        span for span in span_exporter.get_finished_spans() if span.name == "discord.command"
    ]
    deliveries = [
        span for span in span_exporter.get_finished_spans() if span.name == "discord.delivery"
    ]
    assert [span.attributes["discord.command.outcome"] for span in commands] == [
        "rejected",
        "submitted",
    ]
    assert submitted[0].command_type == "move"
    assert {span.attributes["discord.delivery.kind"] for span in deliveries} == {
        "room_feed",
        "pause_status",
    }
    assert {_span_status_name(span) for span in deliveries} == {"OK", "ERROR"}
    assert private not in _serialized_spans(span_exporter)


@pytestmark_otel
async def test_discord_image_delivery_records_success_and_external_failure(
    otel_capture, monkeypatch
):
    import bunnyland.discord.bot as bot_module
    from bunnyland.discord.bot import DELIVER_EMOJI, DiscordBot

    private = "private image delivery failure"
    span_exporter, _reader = otel_capture
    bot = object.__new__(DiscordBot)

    class _Media:
        def read(self, namespace, name):
            assert (namespace, name) == ("events", "scene.png")
            return b"image-bytes"

    bot.imagegen = types.SimpleNamespace(media=_Media())

    class _Message:
        def __init__(self, *, fail=False):
            self.fail = fail
            self.reactions = []

        async def reply(self, **kwargs):
            del kwargs
            if self.fail:
                raise RuntimeError(private)

        async def add_reaction(self, reaction):
            self.reactions.append(reaction)

    monkeypatch.setattr(
        bot_module,
        "_require_discord",
        lambda: (types.SimpleNamespace(File=lambda *_args, **_kwargs: object()), object()),
    )
    success = _Message()
    failure = _Message(fail=True)
    bot._image_messages = {"record-1": success, "record-2": failure}

    def event(entity_id):
        return types.SimpleNamespace(
            entity_id=entity_id,
            purpose="event",
            url="/v1/public/media/events/scene.png",
        )

    await bot._deliver_image(event("record-1"))
    with pytest.raises(RuntimeError, match="private image"):
        await bot._deliver_image(event("record-2"))

    spans = [span for span in span_exporter.get_finished_spans() if span.name == "discord.delivery"]
    assert [_span_status_name(span) for span in spans] == ["OK", "ERROR"]
    assert spans[0].attributes["discord.delivery.bytes"] == len(b"image-bytes")
    assert success.reactions == [DELIVER_EMOJI]
    assert private not in _serialized_spans(span_exporter)
