"""Fixed-snapshot comparisons across the supported controller families."""

from dataclasses import replace

import pytest
from conftest import build_scenario

from bunnyland.core.controllers import (
    BehaviorControllerComponent,
    LLMControllerComponent,
    ScriptedControllerComponent,
)
from bunnyland.foundation.persona.mechanics import GoalComponent
from bunnyland.llm_agents import (
    ControllerBenchmarkCase,
    GoalDirectedAgent,
    ScriptedAgent,
    ToolCall,
    register_script,
    run_fixed_snapshot_controller_benchmark,
)
from bunnyland.llm_agents.benchmark import _trace_complete
from bunnyland.llm_agents.dispatch import Decision
from bunnyland.persistence import WorldMeta, save_world
from bunnyland.plugins import PluginRegistry, bunnyland_plugins


async def test_supported_controllers_share_fixed_snapshot_receipt_benchmark(tmp_path):
    scenario = build_scenario()
    scenario.actor.world.get_entity(scenario.character).add_component(
        GoalComponent(active_goals=("explore north",))
    )
    snapshot = tmp_path / "controller-benchmark.json"
    save_world(
        scenario.actor,
        snapshot,
        meta=WorldMeta(seed="controller-seed", plugins=()),
    )
    register_script("benchmark-north", (ToolCall("move", {"direction": "north"}),))
    cases = (
        ControllerBenchmarkCase(
            name="scripted",
            family="scripted",
            controller_factory=lambda: ScriptedControllerComponent(script_name="benchmark-north"),
            agent_factory=lambda: ScriptedAgent(()),
        ),
        ControllerBenchmarkCase(
            name="behavior-tree",
            family="behavior_tree",
            controller_factory=lambda: BehaviorControllerComponent(behavior_name="wanderer"),
            agent_factory=lambda: ScriptedAgent(()),
        ),
        ControllerBenchmarkCase(
            name="goal-directed",
            family="goal_directed",
            controller_factory=lambda: LLMControllerComponent(
                profile_name="benchmark", model="benchmark"
            ),
            agent_factory=GoalDirectedAgent,
        ),
        ControllerBenchmarkCase(
            name="llm-contract",
            family="llm",
            controller_factory=lambda: LLMControllerComponent(
                profile_name="benchmark", model="benchmark"
            ),
            agent_factory=lambda: ScriptedAgent((ToolCall("move", {"direction": "north"}),)),
        ),
    )

    results = await run_fixed_snapshot_controller_benchmark(
        snapshot,
        registry=PluginRegistry(bunnyland_plugins()),
        character_id=str(scenario.character),
        cases=cases,
    )

    assert {result.family for result in results} == {
        "scripted",
        "behavior_tree",
        "goal_directed",
        "llm",
    }
    assert len({result.snapshot_sha256 for result in results}) == 1
    assert {result.world_seed for result in results} == {"controller-seed"}
    for result in results:
        assert result.attempted_actions == 1
        assert result.structural_validity_rate == 1.0
        assert result.committed_commands == 1
        assert result.rejection_recovery_rate == 1.0
        assert result.trace_complete is True
        decision = result.decisions[0]
        assert decision.selected_action == "move"
        assert decision.command_id
        assert decision.submission_accepted is True
        assert decision.receipt_status == "committed"
        assert decision.result_event_ids

    no_activity = replace(
        results[0], attempted_actions=0, rejected_commands=0, recovered_rejections=0
    )
    assert no_activity.structural_validity_rate == 1.0
    assert no_activity.rejection_recovery_rate == 1.0
    partial_recovery = replace(results[0], rejected_commands=2, recovered_rejections=1)
    assert partial_recovery.rejection_recovery_rate == 0.5


async def test_fixed_snapshot_benchmark_validates_turns_and_character(tmp_path):
    scenario = build_scenario()
    snapshot = tmp_path / "controller-benchmark.json"
    save_world(scenario.actor, snapshot, meta=WorldMeta(seed="controller-seed", plugins=()))
    case = ControllerBenchmarkCase(
        name="llm-contract",
        family="llm",
        controller_factory=lambda: LLMControllerComponent(
            profile_name="benchmark", model="benchmark"
        ),
        agent_factory=lambda: ScriptedAgent(()),
    )

    with pytest.raises(ValueError, match="turns must be positive"):
        await run_fixed_snapshot_controller_benchmark(
            snapshot,
            registry=PluginRegistry(bunnyland_plugins()),
            character_id=str(scenario.character),
            cases=(case,),
            turns=0,
        )
    with pytest.raises(ValueError, match="does not exist"):
        await run_fixed_snapshot_controller_benchmark(
            snapshot,
            registry=PluginRegistry(bunnyland_plugins()),
            character_id="not-an-entity",
            cases=(case,),
        )
    with pytest.raises(ValueError, match="not a character"):
        await run_fixed_snapshot_controller_benchmark(
            snapshot,
            registry=PluginRegistry(bunnyland_plugins()),
            character_id=str(scenario.room_a),
            cases=(case,),
        )


async def test_fixed_snapshot_benchmark_records_policy_rejection_without_ticking(tmp_path):
    scenario = build_scenario()
    snapshot = tmp_path / "controller-benchmark.json"
    save_world(scenario.actor, snapshot, meta=WorldMeta(seed="controller-seed", plugins=()))
    case = ControllerBenchmarkCase(
        name="invalid-llm-action",
        family="llm",
        controller_factory=lambda: LLMControllerComponent(
            profile_name="benchmark", model="benchmark"
        ),
        agent_factory=lambda: ScriptedAgent((ToolCall("not-a-world-action", {}),)),
    )

    (result,) = await run_fixed_snapshot_controller_benchmark(
        snapshot,
        registry=PluginRegistry(bunnyland_plugins()),
        character_id=str(scenario.character),
        cases=(case,),
    )

    assert result.committed_commands == 0
    assert result.rejected_commands == 1
    assert result.decisions[0].command_id is None
    assert result.decisions[0].receipt_status == "policy_rejected"


def test_trace_completeness_requires_causal_decision_fields():
    base = Decision(
        character_id="character-1",
        tool=None,
        summary="waiting",
        governing_pressure="exploration",
        input_epoch=1,
    )

    assert _trace_complete(replace(base, governing_pressure="")) is False
    assert _trace_complete(replace(base, receipt_status="wait")) is True
    assert _trace_complete(replace(base, selected_action="move")) is False
    selected = replace(base, selected_action="move", candidate_actions=("move",))
    assert _trace_complete(replace(selected, receipt_status="policy_rejected")) is True
    assert _trace_complete(replace(selected, receipt_status=None)) is False
    assert _trace_complete(
        replace(selected, command_id="command-1", receipt_status="committed")
    ) is True
