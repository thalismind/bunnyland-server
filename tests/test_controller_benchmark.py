"""Fixed-snapshot comparisons across the supported controller families."""

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
