"""Deterministic coverage for the LLM tutorial-ladder benchmark."""

from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import dataclass, replace
from types import ModuleType, SimpleNamespace

import pytest

import benchmarks.tutorials as tutorial_benchmark_module
from benchmarks.tutorials import (
    HELPFUL_MEMORY_NOTES,
    SCHEMA_VERSION,
    BenchmarkConfig,
    BenchmarkConfigurationError,
    LiveArtifactWriter,
    ModelMetadata,
    ProviderBenchmarkError,
    SessionResult,
    TurnTrace,
    _build_session,
    preflight_ollama_models,
    preflight_openrouter_models,
    render_report,
    run_benchmark,
    run_session,
    summarize,
    tutorial_scenarios,
    write_artifacts,
)
from bunnyland.core import (
    ContainmentMode,
    Contains,
    IdentityComponent,
    RoomComponent,
)
from bunnyland.core.events import (
    ActorMovedEvent,
    EntityInspectedEvent,
    EventVisibility,
    RoomLookedEvent,
    SpeechSaidEvent,
    SpeechToldEvent,
    event_base,
)
from bunnyland.foundation.needs.mechanics import FoodEatenEvent
from bunnyland.llm_agents import InvalidAgentResponse, ScriptedAgent, ToolCall


def _apple_calls() -> tuple[ToolCall, ...]:
    return (
        ToolCall("move", {"direction": "east"}),
        ToolCall("take", {"item_id": "red crossing apple"}),
        ToolCall("move", {"direction": "west"}),
        ToolCall("drop", {"item_id": "red crossing apple"}),
        ToolCall("inspect", {"target_id": "Apple Crossing notice board"}),
        ToolCall("move", {"direction": "south"}),
        ToolCall("move", {"direction": "west"}),
        ToolCall("move", {"direction": "in"}),
        ToolCall("inspect", {"target_id": "delivery ledger"}),
    )


def _bell_calls() -> tuple[ToolCall, ...]:
    return (
        ToolCall("inspect", {"target_id": "central notice board"}),
        ToolCall("open", {"target_id": "community mailbox"}),
        ToolCall("move", {"direction": "north"}),
        ToolCall("inspect", {"target_id": "sorted letters"}),
        ToolCall("say", {"text": "Hello!", "intent": "greet"}),
        ToolCall("move", {"direction": "south"}),
        ToolCall("move", {"direction": "east"}),
        ToolCall("take", {"item_id": "harvest basket"}),
        ToolCall("move", {"direction": "west"}),
        ToolCall("move", {"direction": "south"}),
        ToolCall("move", {"direction": "north"}),
        ToolCall("move", {"direction": "east"}),
        ToolCall("move", {"direction": "south"}),
        ToolCall("move", {"direction": "east"}),
    )


def _clover_calls() -> tuple[ToolCall, ...]:
    return (
        ToolCall("inspect", {"target_id": "daily bulletin"}),
        ToolCall("move", {"direction": "east"}),
        ToolCall("open", {"target_id": "parcel locker"}),
        ToolCall("move", {"direction": "west"}),
        ToolCall("move", {"direction": "north"}),
        ToolCall("move", {"direction": "south"}),
        ToolCall("move", {"direction": "south"}),
        ToolCall("move", {"direction": "west"}),
        ToolCall("move", {"direction": "east"}),
        ToolCall("move", {"direction": "east"}),
        ToolCall("move", {"direction": "west"}),
        ToolCall("move", {"direction": "north"}),
        ToolCall("move", {"direction": "west"}),
        ToolCall("move", {"direction": "up"}),
        ToolCall("move", {"direction": "down"}),
        ToolCall("move", {"direction": "east"}),
        ToolCall("move", {"direction": "southeast"}),
        ToolCall("inspect", {"target_id": "incident log"}),
        ToolCall("move", {"direction": "northwest"}),
        ToolCall("move", {"direction": "out"}),
        ToolCall("inspect", {"target_id": "Street Stop timetable"}),
        ToolCall("inspect", {"target_id": "Rook Vale"}),
        ToolCall("say", {"text": "What is the posted route?", "intent": "ask"}),
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
    assert any(trace.result_events for trace in traces)
    assert all(trace.selected_tool != "wait" for trace in traces)
    if tutorial in {"apple", "clover"}:
        assert all(trace.selected_tool != "look" for trace in traces)

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


async def test_repeat_command_guard_ignores_controller_holds_while_sleeping():
    result, traces = await run_session(
        tutorial_scenarios()["bell"],
        model="sleeper",
        provider="ollama-local",
        run=1,
        timeout_seconds=5,
        turn_limit=6,
        agent=ScriptedAgent((ToolCall("sleep", {}),)),
        repeat_command_guard=True,
    )

    assert result.status == "turn_limit"
    assert traces[0].selected_tool == "sleep"
    assert traces[0].receipt_status == "committed"
    assert all(trace.selected_tool is None for trace in traces[1:])
    assert all(trace.decision_summary == "controller hold" for trace in traces[1:])
    assert all(trace.consecutive_repeat_count == 0 for trace in traces[1:])
    assert not any(trace.repeat_guard_warning for trace in traces)


async def test_invalid_provider_response_is_rejected_with_recovery_feedback():
    class InvalidThenWaitAgent:
        def __init__(self) -> None:
            self.prompts: list[str] = []

        async def decide(self, prompt, context, **kwargs):
            del context, kwargs
            self.prompts.append(prompt)
            if len(self.prompts) == 1:
                return InvalidAgentResponse(
                    reason="provider response contained no structured tool call",
                    feedback=(
                        "Invalid action response: assistant.tool_calls was empty. "
                        "Return exactly one structured tool call."
                    ),
                )
            return ToolCall("wait", {})

    agent = InvalidThenWaitAgent()
    result, traces = await run_session(
        tutorial_scenarios()["bell"],
        model="invalid-then-wait",
        provider="ollama-local",
        run=1,
        timeout_seconds=5,
        turn_limit=2,
        agent=agent,
    )

    assert result.rejected_actions == 1
    assert result.first_confusion_signal.startswith("invalid action response")
    assert traces[0].receipt_status == "policy_rejected"
    assert traces[0].policy_rejections == ("invalid_agent_response",)
    assert traces[0].decision_summary.startswith("invalid response")
    assert "assistant.tool_calls was empty" in traces[0].receipt_reason
    assert "Invalid action response" in agent.prompts[1]


async def test_exhausted_empty_provider_response_is_rejected_without_waiting():
    class EmptyResponseAgent:
        async def decide(self, prompt, context, **kwargs):
            del prompt, context, kwargs
            return InvalidAgentResponse(
                reason="provider returned empty response after retries",
                feedback=(
                    "Invalid action response: Ollama returned an empty assistant message "
                    "on 4 consecutive attempt(s), so no action was submitted."
                ),
            )

    result, traces = await run_session(
        tutorial_scenarios()["bell"],
        model="empty",
        provider="ollama-cloud",
        run=1,
        timeout_seconds=5,
        turn_limit=1,
        agent=EmptyResponseAgent(),
    )

    assert result.status == "turn_limit"
    assert result.rejected_actions == 1
    assert traces[0].selected_tool is None
    assert traces[0].receipt_status == "policy_rejected"
    assert traces[0].policy_rejections == ("invalid_agent_response",)
    assert traces[0].provider_error == ""
    assert "empty assistant message" in traces[0].receipt_reason


async def test_milestones_remain_achieved_after_authoritative_state_changes():
    calls = (
        ToolCall("move", {"direction": "east"}),
        ToolCall("take", {"item_id": "harvest basket"}),
        ToolCall("move", {"direction": "south"}),
        ToolCall("drop", {"item_id": "harvest basket"}),
    )
    result, traces = await run_session(
        tutorial_scenarios()["bell"],
        model="deterministic",
        provider="ollama-local",
        run=1,
        timeout_seconds=5,
        turn_limit=len(calls),
        agent=ScriptedAgent(calls),
    )

    assert "carried_item_between_rooms" in traces[2].milestones
    assert "carried_item_between_rooms" in traces[3].milestones
    assert dict(result.milestone_results)["carried_item_between_rooms"] is True


async def test_clover_orientation_excludes_systemic_story_obligations_from_prompt():
    result, traces = await run_session(
        tutorial_scenarios()["clover"],
        model="deterministic",
        provider="ollama-local",
        run=1,
        timeout_seconds=5,
        turn_limit=1,
        agent=ScriptedAgent(()),
    )

    assert result.turns == 1
    assert "owes you:" not in traces[0].prompt
    milestones = dict(result.milestone_results)
    assert milestones["oriented_in_clover_city_lobby"] is True
    assert milestones["observed_world_activity"] is False


async def test_starting_room_projection_counts_as_orientation_without_redundant_look():
    result, _traces = await run_session(
        tutorial_scenarios()["bell"],
        model="deterministic",
        provider="ollama-local",
        run=1,
        timeout_seconds=5,
        turn_limit=1,
        agent=ScriptedAgent(()),
    )

    assert dict(result.milestone_results)["oriented_in_bell_green"] is True


async def test_bell_goal_explicitly_requires_checking_local_mail():
    _result, traces = await run_session(
        tutorial_scenarios()["bell"],
        model="deterministic",
        provider="ollama-local",
        run=1,
        timeout_seconds=5,
        turn_limit=1,
        agent=ScriptedAgent(()),
    )

    assert "check how the town handles local mail" in traces[0].prompt


@pytest.mark.parametrize("tutorial", ("apple", "bell", "clover"))
async def test_optional_helpful_memory_seed_appears_in_initial_prompt(tutorial):
    _result, traces = await run_session(
        tutorial_scenarios()[tutorial],
        model="deterministic",
        provider="ollama-local",
        run=1,
        timeout_seconds=5,
        turn_limit=1,
        agent=ScriptedAgent(()),
        seed_helpful_memory=True,
    )

    assert all(note in traces[0].prompt for note in HELPFUL_MEMORY_NOTES[tutorial])


async def test_helpful_memory_seed_is_disabled_by_default():
    _result, traces = await run_session(
        tutorial_scenarios()["bell"],
        model="deterministic",
        provider="ollama-local",
        run=1,
        timeout_seconds=5,
        turn_limit=1,
        agent=ScriptedAgent(()),
    )

    assert all(note not in traces[0].prompt for note in HELPFUL_MEMORY_NOTES["bell"])


async def test_initial_projection_perceives_apple_scene_without_look():
    result, traces = await run_session(
        tutorial_scenarios()["apple"],
        model="deterministic",
        provider="ollama-local",
        run=1,
        timeout_seconds=5,
        turn_limit=1,
        agent=ScriptedAgent(()),
    )

    milestones = dict(result.milestone_results)
    assert milestones["oriented_in_apple_crossing"] is True
    assert milestones["perceived_courier_scene"] is True
    assert traces[0].selected_tool is None


@pytest.mark.parametrize(
    "handoff",
    (
        ToolCall("drop", {"item_id": "red crossing apple"}),
        ToolCall(
            "put",
            {
                "item_id": "red crossing apple",
                "target_container_id": "open courier basket",
            },
        ),
        ToolCall(
            "give_gift",
            {"item_id": "red crossing apple", "target_id": "Pip Thistle"},
        ),
    ),
    ids=("drop", "accessible-container", "gift"),
)
async def test_apple_food_handoffs_make_food_accessible(handoff):
    result, _traces = await run_session(
        tutorial_scenarios()["apple"],
        model="deterministic",
        provider="ollama-local",
        run=1,
        timeout_seconds=5,
        turn_limit=4,
        agent=ScriptedAgent(
            (
                ToolCall("move", {"direction": "east"}),
                ToolCall("take", {"item_id": "red crossing apple"}),
                ToolCall("move", {"direction": "west"}),
                handoff,
            )
        ),
    )

    assert dict(result.milestone_results)["made_food_accessible_to_pip"] is True


async def test_apple_food_in_player_inventory_is_not_accessible():
    result, _traces = await run_session(
        tutorial_scenarios()["apple"],
        model="deterministic",
        provider="ollama-local",
        run=1,
        timeout_seconds=5,
        turn_limit=5,
        agent=ScriptedAgent(
            (
                ToolCall("move", {"direction": "east"}),
                ToolCall("take", {"item_id": "red crossing apple"}),
                ToolCall("move", {"direction": "west"}),
                ToolCall("inspect", {"target_id": "Pip Thistle"}),
                ToolCall("inspect", {"target_id": "Apple Crossing notice board"}),
            )
        ),
    )

    milestones = dict(result.milestone_results)
    assert milestones["made_food_accessible_to_pip"] is False
    assert milestones["pip_ate_apple"] is False


async def test_eventual_consumption_is_authoritative_food_access():
    scenario = tutorial_scenarios()["apple"]
    state, _dispatch, _recording = await _build_session(
        scenario,
        model="deterministic",
        provider="ollama-local",
        seed="food-consumption-evidence",
        agent=ScriptedAgent(()),
    )
    state.events.append(
        FoodEatenEvent(
            **event_base(
                state.actor.epoch,
                visibility=EventVisibility.ROOM,
                actor_id=str(state.generated.characters["courier"]),
                room_id=str(state.generated.rooms["crossing"]),
                target_ids=(str(state.generated.objects["apple"]),),
            ),
            item_id=str(state.generated.objects["apple"]),
            satiety=55,
        )
    )
    milestone = next(
        item for item in scenario.milestones if item.name == "made_food_accessible_to_pip"
    )

    assert milestone.evaluate(state) is True


def _perception_event(
    source: str,
    *,
    state,
    room_key: str,
    character_key: str,
):
    room_id = str(state.generated.rooms[room_key])
    character_id = str(state.generated.characters[character_key])
    resident_name = state.actor.world.get_entity(
        state.generated.characters[character_key]
    ).get_component(IdentityComponent).name
    base = event_base(
        state.actor.epoch,
        visibility=EventVisibility.PRIVATE,
        actor_id=state.player_id,
        room_id=room_id,
        target_ids=(character_id,),
    )
    if source == "arrival":
        room_title = state.actor.world.get_entity(
            state.generated.rooms[room_key]
        ).get_component(RoomComponent).title
        return ActorMovedEvent(
            **base,
            from_room_id=str(state.generated.rooms["lobby"]),
            to_room_id=room_id,
            direction="test",
            arrival_summary=f"{room_title}\nHere: {resident_name}.",
        )
    if source == "look":
        room_title = state.actor.world.get_entity(
            state.generated.rooms[room_key]
        ).get_component(RoomComponent).title
        return RoomLookedEvent(**base, room_title=room_title, summary=resident_name)
    if source == "inspect":
        return EntityInspectedEvent(
            **base,
            entity_id=character_id,
            name=resident_name,
            kind="character",
        )
    assert source == "speech"
    return SpeechToldEvent(**base, text=f"Hello, {resident_name}.")


@pytest.mark.parametrize("source", ("arrival", "look", "inspect", "speech"))
async def test_clover_resident_perception_accepts_authoritative_sources(source):
    scenario = tutorial_scenarios()["clover"]
    state, _dispatch, _recording = await _build_session(
        scenario,
        model="deterministic",
        provider="ollama-local",
        seed=f"resident-{source}",
        agent=ScriptedAgent(()),
    )
    state.initial_room_title = ""
    state.initial_room_projection = ""
    state.events.extend(
        _perception_event(
            source,
            state=state,
            room_key=room_key,
            character_key=character_key,
        )
        for room_key, character_key in (
            ("mailroom", "pip"),
            ("laundry", "tavi"),
            ("kitchen", "wick"),
        )
    )
    milestone = next(
        item
        for item in scenario.milestones
        if item.name == "perceived_three_residents_across_facilities"
    )

    assert milestone.evaluate(state) is True


async def test_clover_repeated_observations_in_one_facility_do_not_count():
    scenario = tutorial_scenarios()["clover"]
    state, _dispatch, _recording = await _build_session(
        scenario,
        model="deterministic",
        provider="ollama-local",
        seed="resident-one-room",
        agent=ScriptedAgent(()),
    )
    state.initial_room_title = ""
    state.initial_room_projection = ""
    state.events.extend(
        _perception_event(
            "inspect",
            state=state,
            room_key="security",
            character_key=character_key,
        )
        for character_key in ("orla", "cress", "orla")
    )
    milestone = next(
        item
        for item in scenario.milestones
        if item.name == "perceived_three_residents_across_facilities"
    )

    assert milestone.evaluate(state) is False


async def test_rook_movement_and_route_report_each_count_as_world_activity():
    scenario = tutorial_scenarios()["clover"]
    movement_state, _dispatch, _recording = await _build_session(
        scenario,
        model="deterministic",
        provider="ollama-local",
        seed="rook-movement",
        agent=ScriptedAgent(()),
    )
    player = movement_state.actor.world.get_entity(
        movement_state.generated.characters["ada"]
    )
    lobby = movement_state.actor.world.get_entity(
        movement_state.generated.rooms["lobby"]
    )
    lobby.remove_relationship(Contains, player.id)
    movement_state.actor.world.get_entity(
        movement_state.generated.rooms["street"]
    ).add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), player.id)
    movement_state.events.append(
        ActorMovedEvent(
            **event_base(
                movement_state.actor.epoch,
                visibility=EventVisibility.ROOM,
                actor_id=str(movement_state.generated.characters["rook"]),
                room_id=str(movement_state.generated.rooms["store"]),
            ),
            from_room_id=str(movement_state.generated.rooms["street"]),
            to_room_id=str(movement_state.generated.rooms["store"]),
            direction="east",
        )
    )
    milestone = next(
        item for item in scenario.milestones if item.name == "observed_world_activity"
    )
    assert milestone.evaluate(movement_state) is True

    speech_state, _dispatch, _recording = await _build_session(
        scenario,
        model="deterministic",
        provider="ollama-local",
        seed="rook-speech",
        agent=ScriptedAgent(()),
    )
    speech_state.events.append(
        SpeechSaidEvent(
            **event_base(
                speech_state.actor.epoch,
                visibility=EventVisibility.ROOM,
                actor_id=str(speech_state.generated.characters["rook"]),
                room_id=str(speech_state.generated.rooms["street"]),
                target_ids=(speech_state.player_id,),
            ),
            text="Rook route report — Street Stop: next stop Corner Store.",
        )
    )
    assert milestone.evaluate(speech_state) is True


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


class _ExhaustedProviderAgent:
    async def decide(self, prompt, context, **kwargs):
        del prompt, context, kwargs
        return InvalidAgentResponse(
            reason="provider returned no response after retries",
            feedback="provider failed",
        )


async def test_benchmark_discards_and_retries_provider_failed_session():
    agents: list[object] = []

    def factory(model, host, api_key):
        del model, host, api_key
        agent: object
        if agents:
            agent = ScriptedAgent(_apple_calls())
        else:
            agent = _ExhaustedProviderAgent()
        agents.append(agent)
        return agent

    async def preflight(models, host, api_key):
        del host, api_key
        return tuple(ModelMetadata(model=model) for model in models)

    _summary, sessions, traces, responses, _metadata = await run_benchmark(
        BenchmarkConfig(
            models=("tiny",),
            tutorials=("apple",),
            sessions=1,
            turn_limit=20,
            provider_session_retries=1,
        ),
        agent_factory=factory,
        preflight=preflight,
    )

    assert len(agents) == 2
    assert len(sessions) == 1
    assert sessions[0].passed is True
    assert all(trace.provider_error == "" for trace in traces)
    assert responses == ()


async def test_benchmark_rejects_negative_provider_session_retries():
    with pytest.raises(
        BenchmarkConfigurationError,
        match="provider session retries cannot be negative",
    ):
        BenchmarkConfig(
            models=("tiny",),
            provider_session_retries=-1,
        ).validated()


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


async def test_benchmark_applies_session_timeout_to_ollama_requests(monkeypatch):
    request_timeouts: list[float] = []

    class TimeoutRecordingAgent(ScriptedAgent):
        def __init__(
            self,
            *,
            model,
            host,
            api_key,
            history_turns,
            think,
            temperature,
            max_output_tokens,
            request_timeout_seconds,
            response_observer,
            log_thinking,
        ) -> None:
            del (
                model,
                host,
                api_key,
                history_turns,
                think,
                temperature,
                max_output_tokens,
                response_observer,
                log_thinking,
            )
            super().__init__(_apple_calls())
            request_timeouts.append(request_timeout_seconds)

        async def close(self) -> None:
            pass

    async def preflight(models, host, api_key):
        del host, api_key
        return tuple(
            ModelMetadata(model=model, parameter_count=1_000_000_000)
            for model in models
        )

    monkeypatch.setattr(
        tutorial_benchmark_module,
        "OllamaAgent",
        TimeoutRecordingAgent,
    )
    _summary, sessions, _traces, _responses, _metadata = await run_benchmark(
        BenchmarkConfig(
            models=("tiny",),
            tutorials=("apple",),
            provider="ollama-cloud",
            api_key="cloud-secret",
            sessions=1,
            timeout_seconds=37,
            turn_limit=20,
        ),
        preflight=preflight,
    )

    assert request_timeouts == [37]
    assert sessions[0].passed is True


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

        async def close(self):
            calls.append(("close", "client"))

    fake = ModuleType("ollama")
    fake.AsyncClient = FakeClient
    monkeypatch.setitem(sys.modules, "ollama", fake)
    result = await preflight_ollama_models(
        ("reasoner",), "https://ollama.example", "cloud-secret"
    )
    assert calls == [
        ("https://ollama.example", "Bearer cloud-secret"),
        ("show", "reasoner"),
        ("close", "client"),
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

        async def close(self):
            pass

    fake = ModuleType("ollama")
    fake.AsyncClient = FakeClient
    monkeypatch.setitem(sys.modules, "ollama", fake)
    with pytest.raises(ProviderBenchmarkError, match="preflight failed"):
        await preflight_ollama_models(("missing",), "http://local", None)


async def test_ollama_preflight_configures_request_timeout(monkeypatch):
    configured: list[float] = []

    class FakeClient:
        def __init__(self, *, host, headers, timeout):
            del host, headers
            configured.append(timeout)

        async def show(self, model):
            del model
            return SimpleNamespace(details=None)

        async def close(self):
            pass

    fake = ModuleType("ollama")
    fake.AsyncClient = FakeClient
    monkeypatch.setitem(sys.modules, "ollama", fake)

    await preflight_ollama_models(
        ("reasoner",),
        "https://ollama.example",
        "cloud-secret",
        request_timeout_seconds=60,
    )

    assert configured == [60]


async def test_openrouter_preflight_lists_models_without_inference(monkeypatch):
    calls: list[tuple[str, str]] = []

    class FakeModels:
        async def list_async(self):
            calls.append(("models", "list"))
            architecture = SimpleNamespace(tokenizer="GPT")
            model = SimpleNamespace(
                id="openai/gpt-5.6-terra",
                architecture=architecture,
            )
            return SimpleNamespace(result=SimpleNamespace(data=[model]))

    class FakeClient:
        def __init__(self, *, api_key, server_url):
            calls.append((api_key, server_url))
            self.models = FakeModels()

    fake = ModuleType("openrouter")
    fake.OpenRouter = FakeClient
    monkeypatch.setitem(sys.modules, "openrouter", fake)

    result = await preflight_openrouter_models(
        ("openai/gpt-5.6-terra",),
        "https://openrouter.example/api/v1",
        "router-secret",
    )

    assert calls == [
        ("router-secret", "https://openrouter.example/api/v1"),
        ("models", "list"),
    ]
    assert result == (ModelMetadata("openai/gpt-5.6-terra", family="GPT"),)
    assert not hasattr(FakeClient, "chat")


def test_openrouter_configuration_requires_credential_and_uses_default_host():
    config = BenchmarkConfig(models=("model",), provider="openrouter")

    with pytest.raises(BenchmarkConfigurationError, match="OPENROUTER_API_KEY"):
        config.validated()

    configured = replace(config, api_key="router-secret").validated()
    assert configured.resolved_host == "https://openrouter.ai/api/v1"


def test_artifacts_have_stable_schemas_and_never_record_credentials(tmp_path):
    config = BenchmarkConfig(
        models=("model",),
        tutorials=("apple",),
        sessions=1,
        timeout_seconds=3600,
        max_output_tokens=8192,
        output=tmp_path,
        provider="ollama-cloud",
        host="https://user:host-secret@ollama.example/api?token=query-secret",
        api_key="never-write-this-secret",
        seed_helpful_memory=True,
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
    assert manifest["max_output_tokens"] == 8192
    assert manifest["seed_helpful_memory"] is True
    assert manifest["host"] == "https://ollama.example/api"
    session = json.loads((tmp_path / "sessions.jsonl").read_text(encoding="utf-8"))
    assert session["schema_version"] == SCHEMA_VERSION
    assert (tmp_path / "traces.jsonl").read_text(encoding="utf-8") == ""
    assert (tmp_path / "responses.jsonl").read_text(encoding="utf-8") == ""
    report = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert "LLM tutorial-ladder comparison" in report
    assert "Helpful memory seed: `enabled`" in report
    assert "Adding models" in report


def test_parser_accepts_helpful_memory_seed_flag():
    args = tutorial_benchmark_module.build_parser().parse_args(
        ["--model", "tiny", "--seed-helpful-memory"]
    )

    assert args.seed_helpful_memory is True


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
        prompt_event_ids=("event-1",),
        omitted_prompt_events=2,
    )
    writer.record_trace(trace)
    writer.record_session(_session("model", "apple", 1, passed=True))

    saved_trace = json.loads((tmp_path / "traces.jsonl").read_text(encoding="utf-8"))
    saved_session = json.loads((tmp_path / "sessions.jsonl").read_text(encoding="utf-8"))
    assert saved_trace["prompt"] == "full prompt"
    assert saved_trace["receipt_status"] == "committed"
    assert saved_trace["prompt_event_ids"] == ["event-1"]
    assert saved_trace["omitted_prompt_events"] == 2
    assert saved_session["session_id"] == "apple-model-1"
    assert (tmp_path / "summary.json").exists()
    assert (tmp_path / "report.md").exists()
