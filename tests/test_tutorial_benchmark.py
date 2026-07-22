"""Deterministic coverage for the Ollama tutorial-ladder benchmark."""

from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import dataclass
from types import ModuleType, SimpleNamespace

import pytest

from benchmarks.tutorials import (
    SCHEMA_VERSION,
    BenchmarkConfig,
    LiveArtifactWriter,
    ModelMetadata,
    ProviderBenchmarkError,
    SessionResult,
    TurnTrace,
    preflight_ollama_models,
    render_report,
    run_benchmark,
    run_session,
    summarize,
    tutorial_scenarios,
    write_artifacts,
)
from bunnyland.llm_agents import ScriptedAgent, ToolCall


def _apple_calls() -> tuple[ToolCall, ...]:
    return (
        ToolCall("look", {}),
        ToolCall("move", {"direction": "east"}),
        ToolCall("take", {"item_id": "red crossing apple"}),
        ToolCall("move", {"direction": "west"}),
        ToolCall("drop", {"item_id": "red crossing apple"}),
        *(ToolCall("wait", {}) for _ in range(10)),
    )


def _bell_calls() -> tuple[ToolCall, ...]:
    return (
        ToolCall("look", {}),
        ToolCall("inspect", {"target_id": "central notice board"}),
        ToolCall("inspect", {"target_id": "community mailbox"}),
        ToolCall("move", {"direction": "north"}),
        ToolCall("look", {}),
        ToolCall("inspect", {"target_id": "sorted letters"}),
        ToolCall("say", {"text": "Hello!", "intent": "greet"}),
        ToolCall("move", {"direction": "south"}),
        ToolCall("move", {"direction": "east"}),
        ToolCall("look", {}),
        ToolCall("take", {"item_id": "harvest basket"}),
        ToolCall("move", {"direction": "west"}),
        ToolCall("move", {"direction": "south"}),
        ToolCall("look", {}),
        ToolCall("move", {"direction": "north"}),
        ToolCall("move", {"direction": "east"}),
        ToolCall("move", {"direction": "south"}),
        ToolCall("move", {"direction": "east"}),
    )


def _clover_calls() -> tuple[ToolCall, ...]:
    return (
        ToolCall("look", {}),
        ToolCall("inspect", {"target_id": "daily bulletin"}),
        ToolCall("move", {"direction": "east"}),
        ToolCall("look", {}),
        ToolCall("inspect", {"target_id": "parcel locker"}),
        ToolCall("move", {"direction": "west"}),
        ToolCall("move", {"direction": "north"}),
        ToolCall("look", {}),
        ToolCall("move", {"direction": "south"}),
        ToolCall("move", {"direction": "south"}),
        ToolCall("look", {}),
        ToolCall("move", {"direction": "west"}),
        ToolCall("look", {}),
        ToolCall("move", {"direction": "east"}),
        ToolCall("move", {"direction": "east"}),
        ToolCall("look", {}),
        ToolCall("move", {"direction": "west"}),
        ToolCall("move", {"direction": "north"}),
        ToolCall("move", {"direction": "west"}),
        ToolCall("move", {"direction": "up"}),
        ToolCall("look", {}),
        ToolCall("move", {"direction": "down"}),
        ToolCall("move", {"direction": "east"}),
        ToolCall("move", {"direction": "southeast"}),
        ToolCall("look", {}),
        ToolCall("inspect", {"target_id": "incident log"}),
        ToolCall("move", {"direction": "northwest"}),
        ToolCall("move", {"direction": "out"}),
        ToolCall("look", {}),
        ToolCall("wait", {}),
        ToolCall("wait", {}),
        ToolCall("wait", {}),
    )


SUCCESS_CALLS = {
    "apple": _apple_calls(),
    "bell": _bell_calls(),
    "clover": _clover_calls(),
}


@pytest.mark.parametrize("tutorial", ("apple", "bell", "clover"))
async def test_scenarios_score_success_stall_rejection_and_recovery(tutorial):
    scenario = tutorial_scenarios()[tutorial]
    successful, traces = await run_session(
        scenario,
        model="deterministic",
        provider="ollama-local",
        run=1,
        timeout_seconds=5,
        turn_limit=50,
        agent=ScriptedAgent(SUCCESS_CALLS[tutorial]),
    )
    assert successful.passed is True
    assert all(passed for _name, passed in successful.milestone_results)
    assert traces[-1].result_events

    stalled, _traces = await run_session(
        scenario,
        model="deterministic",
        provider="ollama-local",
        run=2,
        timeout_seconds=5,
        turn_limit=3,
        agent=ScriptedAgent(()),
    )
    assert stalled.status == "turn_limit"
    assert stalled.passed is False
    assert stalled.repeated_blockers[0][0] == "wait_without_milestone_progress"
    assert stalled.repeated_blockers[0][1] >= 2

    rejecting, _traces = await run_session(
        scenario,
        model="deterministic",
        provider="ollama-local",
        run=3,
        timeout_seconds=5,
        turn_limit=3,
        agent=ScriptedAgent((ToolCall("move", {"direction": "nowhere"}),), loop=True),
    )
    assert rejecting.rejected_actions == 3
    assert rejecting.first_confusion_signal == "no matching exit"
    assert rejecting.repeated_blockers == (("no matching exit", 3),)

    recovering, _traces = await run_session(
        scenario,
        model="deterministic",
        provider="ollama-local",
        run=4,
        timeout_seconds=5,
        turn_limit=55,
        agent=ScriptedAgent(
            (ToolCall("move", {"direction": "nowhere"}), *SUCCESS_CALLS[tutorial])
        ),
    )
    assert recovering.passed is True
    assert recovering.rejected_actions == 1
    assert recovering.recovered_rejections == 1


class _SlowAgent:
    async def decide(self, prompt, context, **kwargs):
        del prompt, context, kwargs
        await asyncio.sleep(0.1)
        return None


async def test_session_timeout_is_configurable_and_distinct_from_turn_limit():
    result, traces = await run_session(
        tutorial_scenarios()["bell"],
        model="slow",
        provider="ollama-local",
        run=1,
        timeout_seconds=0.01,
        turn_limit=60,
        agent=_SlowAgent(),
    )
    assert result.status == "timeout"
    assert result.passed is False
    assert result.turns == 0
    assert traces == ()


async def test_repeat_command_guard_warns_at_five_and_ends_at_ten():
    result, traces = await run_session(
        tutorial_scenarios()["bell"],
        model="repeating",
        provider="ollama-local",
        run=1,
        timeout_seconds=5,
        turn_limit=60,
        agent=ScriptedAgent(()),
        repeat_command_guard=True,
    )

    assert result.status == "repeat_limit"
    assert result.turns == 10
    assert traces[4].consecutive_repeat_count == 5
    assert traces[4].repeat_guard_warning is True
    assert "Benchmark safety warning" in traces[5].prompt
    assert traces[-1].consecutive_repeat_count == 10


class _FailingAgent:
    async def decide(self, prompt, context, **kwargs):
        del prompt, context, kwargs
        raise OSError("provider unavailable")


async def test_provider_failure_is_in_durable_trace_callback():
    recorded: list[TurnTrace] = []
    with pytest.raises(ProviderBenchmarkError, match="provider unavailable"):
        await run_session(
            tutorial_scenarios()["apple"],
            model="failing",
            provider="ollama-local",
            run=1,
            timeout_seconds=5,
            turn_limit=1,
            agent=_FailingAgent(),
            on_trace_recorded=recorded.append,
        )
    assert len(recorded) == 1
    assert recorded[0].provider_error == "provider unavailable"


@dataclass
class _FreshAgent(ScriptedAgent):
    prompts_seen: int = 0

    def __init__(self) -> None:
        super().__init__(_apple_calls())
        self.prompts_seen = 0

    async def decide(self, prompt, context, **kwargs):
        assert self.prompts_seen or "Previous result:" not in prompt
        self.prompts_seen += 1
        return await super().decide(prompt, context, **kwargs)


async def test_benchmark_builds_fresh_world_agent_and_history_per_session():
    agents: list[_FreshAgent] = []

    def factory(model, host, api_key):
        del model, host, api_key
        agent = _FreshAgent()
        agents.append(agent)
        return agent

    async def preflight(models, host, api_key):
        del host, api_key
        return tuple(ModelMetadata(model=model, parameter_count=1_000_000_000) for model in models)

    summary, sessions, traces, responses, _metadata = await run_benchmark(
        BenchmarkConfig(models=("tiny",), tutorials=("apple",), sessions=2, turn_limit=20),
        agent_factory=factory,
        preflight=preflight,
    )
    assert len(agents) == 2
    assert len({session.world_seed for session in sessions}) == 2
    assert all(session.passed for session in sessions)
    assert {trace.session_id for trace in traces} == {session.session_id for session in sessions}
    assert responses == ()
    ranking = summary["tutorial_rankings"]
    assert isinstance(ranking, dict)
    assert ranking["apple"][0]["completed_within_session_limit"] == 2


def _session(model: str, tutorial: str, run: int, *, passed: bool) -> SessionResult:
    return SessionResult(
        schema_version=SCHEMA_VERSION,
        session_id=f"{tutorial}-{model}-{run}",
        model=model,
        tutorial=tutorial,
        run=run,
        world_seed=f"seed-{run}",
        status="completed" if passed else "turn_limit",
        passed=passed,
        elapsed_seconds=10.0 + run,
        turns=run,
        milestone_results=(("done", passed),),
        valid_actions=run,
        rejected_actions=0,
        recovered_rejections=0,
        first_confusion_signal=None,
        repeated_blockers=(),
    )


def test_summary_ranks_each_tutorial_full_ladder_and_parameter_threshold():
    metadata = (
        ModelMetadata("small", parameter_count=2_000_000_000),
        ModelMetadata("large", parameter_count=8_000_000_000),
    )
    results = tuple(
        _session(model, tutorial, run, passed=model == "large" or run <= 8)
        for model in ("small", "large")
        for tutorial in ("apple", "bell", "clover")
        for run in range(1, 11)
    )
    summary = summarize(results, metadata, ("apple", "bell", "clover"))
    tutorial_rankings = summary["tutorial_rankings"]
    assert isinstance(tutorial_rankings, dict)
    assert tutorial_rankings["apple"][0]["model"] == "large"
    assert summary["full_ladder_ranking"][0]["model"] == "large"
    assert summary["smallest_model_reaching_8_of_10"] == {
        "apple": "small",
        "bell": "small",
        "clover": "small",
        "full_ladder": "small",
    }

    report = render_report(
        BenchmarkConfig(models=("small", "large")), summary, metadata
    )
    assert "## Full ladder" in report
    assert "## Smallest model reaching 8/10" in report
    assert "- Apple: `small`" in report
    assert "- Full ladder: `small`" in report


async def test_ollama_preflight_uses_show_without_pull_and_extracts_metadata(monkeypatch):
    calls: list[tuple[str, str]] = []

    class FakeClient:
        def __init__(self, *, host, headers):
            calls.append((host, headers["Authorization"]))

        async def show(self, model):
            calls.append(("show", model))
            return SimpleNamespace(
                details=SimpleNamespace(
                    parameter_size="7.6B",
                    family="qwen3",
                    quantization_level="Q4_K_M",
                )
            )

    fake = ModuleType("ollama")
    fake.AsyncClient = FakeClient
    monkeypatch.setitem(sys.modules, "ollama", fake)
    result = await preflight_ollama_models(
        ("reasoner",), "https://ollama.example", "cloud-secret"
    )
    assert calls == [
        ("https://ollama.example", "Bearer cloud-secret"),
        ("show", "reasoner"),
    ]
    assert result == (
        ModelMetadata(
            "reasoner",
            parameter_count=7_600_000_000,
            parameter_size="7.6B",
            family="qwen3",
            quantization="Q4_K_M",
        ),
    )
    assert not hasattr(FakeClient, "pull")


async def test_preflight_failure_is_provider_error(monkeypatch):
    class FakeClient:
        def __init__(self, *, host, headers):
            del host, headers

        async def show(self, model):
            raise OSError(f"missing {model}")

    fake = ModuleType("ollama")
    fake.AsyncClient = FakeClient
    monkeypatch.setitem(sys.modules, "ollama", fake)
    with pytest.raises(ProviderBenchmarkError, match="preflight failed"):
        await preflight_ollama_models(("missing",), "http://local", None)


def test_artifacts_have_stable_schemas_and_never_record_credentials(tmp_path):
    config = BenchmarkConfig(
        models=("model",),
        tutorials=("apple",),
        sessions=1,
        timeout_seconds=3600,
        output=tmp_path,
        provider="ollama-cloud",
        host="https://user:host-secret@ollama.example/api?token=query-secret",
        api_key="never-write-this-secret",
    )
    result = _session("model", "apple", 1, passed=True)
    metadata = (ModelMetadata("model", parameter_count=1_000_000_000),)
    summary = summarize((result,), metadata, ("apple",))
    write_artifacts(config, summary, (result,), (), (), metadata)

    expected = {
        "benchmark.log",
        "manifest.json",
        "summary.json",
        "sessions.jsonl",
        "traces.jsonl",
        "report.md",
        "responses.jsonl",
    }
    assert {path.name for path in tmp_path.iterdir()} == expected
    combined = "".join(path.read_text(encoding="utf-8") for path in tmp_path.iterdir())
    assert "never-write-this-secret" not in combined
    assert "host-secret" not in combined
    assert "query-secret" not in combined
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["schema_version"] == SCHEMA_VERSION
    assert manifest["session_timeout_seconds"] == 3600
    assert manifest["host"] == "https://ollama.example/api"
    session = json.loads((tmp_path / "sessions.jsonl").read_text(encoding="utf-8"))
    assert session["schema_version"] == SCHEMA_VERSION
    assert (tmp_path / "traces.jsonl").read_text(encoding="utf-8") == ""
    assert (tmp_path / "responses.jsonl").read_text(encoding="utf-8") == ""
    report = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert "Ollama tutorial-ladder comparison" in report
    assert "Adding models" in report


def test_live_artifacts_checkpoint_each_trace_and_session(tmp_path):
    config = BenchmarkConfig(models=("model",), tutorials=("apple",), output=tmp_path)
    writer = LiveArtifactWriter(config)
    writer.start()
    writer.record_preflight((ModelMetadata("model", parameter_count=1_000_000_000),))
    trace = TurnTrace(
        schema_version=SCHEMA_VERSION,
        session_id="apple-model-01",
        turn=1,
        prompt="full prompt",
        selected_tool="look",
        arguments={},
        decision_latency_seconds=1.0,
        candidate_actions=("look",),
        command_id="command-1",
        submission_accepted=True,
        submission_reason="",
        receipt_status="committed",
        receipt_reason="",
        decision_summary="look {}",
        policy_rejections=(),
        provider_error="",
        consecutive_repeat_count=1,
        repeat_guard_warning=False,
        result_events=(),
        milestones=("looked",),
    )
    writer.record_trace(trace)
    writer.record_session(_session("model", "apple", 1, passed=True))

    saved_trace = json.loads((tmp_path / "traces.jsonl").read_text(encoding="utf-8"))
    saved_session = json.loads((tmp_path / "sessions.jsonl").read_text(encoding="utf-8"))
    assert saved_trace["prompt"] == "full prompt"
    assert saved_trace["receipt_status"] == "committed"
    assert saved_session["session_id"] == "apple-model-1"
    assert (tmp_path / "summary.json").exists()
    assert (tmp_path / "report.md").exists()
