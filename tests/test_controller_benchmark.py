"""Fixed-snapshot comparisons across the supported controller families."""

import re
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
    BehaviorTree,
    ControllerBenchmarkCase,
    ControllerBenchmarkProbe,
    GoalDirectedAgent,
    ScriptedAgent,
    ToolCall,
    register_behavior_tree,
    register_script,
    run_fixed_snapshot_controller_benchmark,
)
from bunnyland.llm_agents.behavior_tree import Action
from bunnyland.llm_agents.benchmark import _trace_complete
from bunnyland.llm_agents.dispatch import Decision
from bunnyland.persistence import WorldMeta, save_world
from bunnyland.plugins import PluginRegistry, bunnyland_plugins
from bunnyland.prompts.builder import PromptContext


def _clover_parcel_call(context: PromptContext) -> ToolCall | None:
    active = any(
        "active incident: missing parcel" in line.lower() for line in context.conditions
    ) or any(
        "goal:" in line.lower() and "missing parcel" in line.lower()
        for line in context.persona
    )
    if not active:
        return None
    carrying = any("misrouted parcel" in item.lower() for item in context.inventory)
    visible = any("misrouted parcel" in item.lower() for item in context.visible_objects)
    obligation_line = next(
        (line for line in context.persona if "[obligation:" in line and "misrouted parcel" in line),
        "",
    )
    obligation_match = re.search(r"\[obligation:([^\s\]]+)", obligation_line)

    if carrying:
        if context.location_title == "Mailroom":
            return ToolCall("drop", {"item_id": "misrouted parcel"})
        direction = {
            "Laundry Room": "east",
            "Courtyard": "north",
            "Clover City Lobby": "east",
        }.get(context.location_title)
        return ToolCall("move", {"direction": direction}) if direction else None

    if obligation_match is not None:
        if visible:
            if context.location_title == "Mailroom":
                return ToolCall(
                    "resolve_obligation",
                    {
                        "obligation_id": obligation_match.group(1),
                        "status": "fulfilled",
                        "note": "Parcel returned to the mailroom.",
                    },
                )
            return ToolCall("take", {"item_id": "misrouted parcel"})
        direction = {
            "Mailroom": "west",
            "Clover City Lobby": "south",
            "Courtyard": "west",
        }.get(context.location_title)
        return ToolCall("move", {"direction": direction}) if direction else None

    if context.location_title == "Security Office":
        return ToolCall(
            "write",
            {
                "target_id": "incident log",
                "text": (
                    "Parcel-01 resolved after Pip returned the missing parcel and filed "
                    "the witness report."
                ),
            },
        )
    direction = {
        "Mailroom": "west",
        "Clover City Lobby": "southeast",
    }.get(context.location_title)
    return ToolCall("move", {"direction": direction}) if direction else None


class _CloverParcelAgent:
    async def decide(
        self,
        prompt: str,
        context: PromptContext,
        *,
        character_id: str,
        model: str | None = None,
        provider: str | None = None,
        tools: list[dict] | None = None,
    ) -> ToolCall | None:
        del prompt, character_id, model, provider, tools
        return _clover_parcel_call(context)


class _SequenceChooser:
    def __init__(self, calls: tuple[ToolCall, ...]) -> None:
        self.calls = calls
        self.index = 0

    def __call__(self, context: PromptContext) -> ToolCall | None:
        del context
        if self.index >= len(self.calls):
            return None
        call = self.calls[self.index]
        self.index += 1
        return call


class _SequenceAgent:
    def __init__(self, calls: tuple[ToolCall, ...]) -> None:
        self.chooser = _SequenceChooser(calls)

    async def decide(
        self,
        prompt: str,
        context: PromptContext,
        *,
        character_id: str,
        model: str | None = None,
        provider: str | None = None,
        tools: list[dict] | None = None,
    ) -> ToolCall | None:
        del prompt, character_id, model, provider, tools
        return self.chooser(context)


def _story_controller_cases(
    name: str, script: tuple[ToolCall, ...]
) -> tuple[ControllerBenchmarkCase, ...]:
    register_script(name, script)
    register_behavior_tree(BehaviorTree(name, Action(_SequenceChooser(script))))
    return (
        ControllerBenchmarkCase(
            name="scripted",
            family="scripted",
            controller_factory=lambda: ScriptedControllerComponent(script_name=name),
            agent_factory=lambda: ScriptedAgent(()),
        ),
        ControllerBenchmarkCase(
            name="behavior-tree",
            family="behavior_tree",
            controller_factory=lambda: BehaviorControllerComponent(behavior_name=name),
            agent_factory=lambda: ScriptedAgent(()),
        ),
        ControllerBenchmarkCase(
            name="goal-directed",
            family="goal_directed",
            controller_factory=lambda: LLMControllerComponent(
                profile_name=name, model="deterministic"
            ),
            agent_factory=lambda: _SequenceAgent(script),
        ),
        ControllerBenchmarkCase(
            name="llm-contract",
            family="llm",
            controller_factory=lambda: LLMControllerComponent(
                profile_name=name, model="deterministic"
            ),
            agent_factory=lambda: ScriptedAgent(script),
        ),
    )


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
        assert result.outcome_pass_rate == 1.0
        assert result.outcomes == ()
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
    partial_outcomes = replace(
        results[0], outcomes=(("first", True), ("second", False))
    )
    assert partial_outcomes.outcome_pass_rate == 0.5


async def test_clover_parcel_story_reproduces_across_controller_families(tmp_path):
    from bunnyland.core import (
        ActionPointsComponent,
        IdentityComponent,
        PortableComponent,
        ReadableComponent,
        SuspendedComponent,
        WorldActor,
        container_of,
    )
    from bunnyland.core.ecs import replace_component
    from bunnyland.foundation.persona.mechanics import GoalComponent
    from bunnyland.foundation.social.mechanics import ObligationComponent, SocialBond
    from bunnyland.foundation.storyteller.mechanics import IncidentComponent
    from bunnyland.plugins import apply_plugins
    from bunnyland.worldgen import GenOptions
    from bunnyland.worldgen.examples import CLOVER_CITY_DEMO

    plugins = bunnyland_plugins()
    actor = WorldActor()
    apply_plugins(plugins, actor)
    world = await CLOVER_CITY_DEMO.generate(actor, "clover-parcel-benchmark", GenOptions())
    pip_id = world.characters["pip"]
    ada_id = world.characters["ada"]
    pip = actor.world.get_entity(pip_id)
    pip.remove_component(SuspendedComponent)
    points = pip.get_component(ActionPointsComponent)
    replace_component(pip, replace(points, current=20, maximum=20))
    pip.add_component(GoalComponent(active_goals=("resolve the missing parcel incident",)))
    parcel = next(
        entity
        for entity in actor.world.query().with_all([PortableComponent]).execute_entities()
        if entity.has_component(IdentityComponent)
        and entity.get_component(IdentityComponent).name == "misrouted parcel"
    )
    obligation = next(
        entity
        for entity in actor.world.query().with_all([ObligationComponent]).execute_entities()
        if entity.get_component(ObligationComponent).source_event_id == "clover-story-0"
    )
    incident = next(
        entity
        for entity in actor.world.query().with_all([IncidentComponent]).execute_entities()
        if entity.get_component(IncidentComponent).kind == "missing_parcel"
    )
    snapshot = tmp_path / "clover-parcel-benchmark.json"
    save_world(
        actor,
        snapshot,
        meta=WorldMeta(seed="clover-parcel-benchmark", plugins=()),
    )

    script = (
        ToolCall("move", {"direction": "west"}),
        ToolCall("move", {"direction": "south"}),
        ToolCall("move", {"direction": "west"}),
        ToolCall("take", {"item_id": "misrouted parcel"}),
        ToolCall("move", {"direction": "east"}),
        ToolCall("move", {"direction": "north"}),
        ToolCall("move", {"direction": "east"}),
        ToolCall("drop", {"item_id": "misrouted parcel"}),
        ToolCall(
            "resolve_obligation",
            {
                "obligation_id": str(obligation.id),
                "status": "fulfilled",
                "note": "Parcel returned to the mailroom.",
            },
        ),
        ToolCall("move", {"direction": "west"}),
        ToolCall("move", {"direction": "southeast"}),
        ToolCall(
            "write",
            {
                "target_id": "incident log",
                "text": (
                    "Parcel-01 resolved after Pip returned the missing parcel and filed "
                    "the witness report."
                ),
            },
        ),
    )
    register_script("clover-missing-parcel", script)
    register_behavior_tree(BehaviorTree("clover-missing-parcel", Action(_clover_parcel_call)))

    def relationship_changed(candidate) -> bool:
        return any(
            target_id == pip_id and edge.trust >= 0.1 and edge.affinity >= 0.05
            for edge, target_id in candidate.world.get_entity(ada_id).get_relationships(SocialBond)
        )

    probes = (
        ControllerBenchmarkProbe(
            "parcel_returned",
            lambda candidate: container_of(candidate.world.get_entity(parcel.id))
            == world.rooms["mailroom"],
        ),
        ControllerBenchmarkProbe(
            "report_written",
            lambda candidate: "parcel-01 resolved"
            in candidate.world.get_entity(world.objects["log"])
            .get_component(ReadableComponent)
            .text.lower(),
        ),
        ControllerBenchmarkProbe(
            "obligation_fulfilled",
            lambda candidate: candidate.world.get_entity(obligation.id)
            .get_component(ObligationComponent)
            .status
            == "fulfilled",
        ),
        ControllerBenchmarkProbe(
            "incident_resolved",
            lambda candidate: candidate.world.get_entity(incident.id)
            .get_component(IncidentComponent)
            .resolved_at_epoch
            is not None,
        ),
        ControllerBenchmarkProbe("relationship_changed", relationship_changed),
    )
    cases = (
        ControllerBenchmarkCase(
            name="scripted",
            family="scripted",
            controller_factory=lambda: ScriptedControllerComponent(
                script_name="clover-missing-parcel"
            ),
            agent_factory=lambda: ScriptedAgent(()),
        ),
        ControllerBenchmarkCase(
            name="behavior-tree",
            family="behavior_tree",
            controller_factory=lambda: BehaviorControllerComponent(
                behavior_name="clover-missing-parcel"
            ),
            agent_factory=lambda: ScriptedAgent(()),
        ),
        ControllerBenchmarkCase(
            name="goal-directed",
            family="goal_directed",
            controller_factory=lambda: LLMControllerComponent(
                profile_name="clover-parcel", model="deterministic"
            ),
            agent_factory=_CloverParcelAgent,
        ),
        ControllerBenchmarkCase(
            name="llm-contract",
            family="llm",
            controller_factory=lambda: LLMControllerComponent(
                profile_name="clover-parcel", model="deterministic"
            ),
            agent_factory=lambda: ScriptedAgent(script),
        ),
    )

    results = await run_fixed_snapshot_controller_benchmark(
        snapshot,
        registry=PluginRegistry(plugins),
        character_id=str(pip_id),
        cases=cases,
        probes=probes,
        turns=12,
    )

    assert {result.family for result in results} == {
        "scripted",
        "behavior_tree",
        "goal_directed",
        "llm",
    }
    assert len({result.snapshot_sha256 for result in results}) == 1
    for result in results:
        assert result.attempted_actions == 12
        assert result.structurally_valid_actions == 12
        assert result.committed_commands == 12
        assert result.rejected_commands == 0
        assert result.trace_complete is True
        assert result.outcome_pass_rate == 1.0
        assert dict(result.outcomes) == {probe.name: True for probe in probes}
        assert all(
            decision.result_event_ids
            for decision in result.decisions
            if decision.command_id is not None
        )


async def test_clover_water_shortage_reproduces_with_rejection_recovery(tmp_path):
    from bunnyland.core import (
        ActionPointsComponent,
        ReadableComponent,
        SuspendedComponent,
        WorldActor,
        container_of,
    )
    from bunnyland.core.ecs import replace_component
    from bunnyland.foundation.consumables.components import ConsumableComponent
    from bunnyland.foundation.needs.mechanics import ThirstComponent
    from bunnyland.foundation.persona.mechanics import GoalComponent
    from bunnyland.foundation.social.mechanics import ObligationComponent, SocialBond
    from bunnyland.foundation.storyteller.mechanics import IncidentComponent
    from bunnyland.plugins import apply_plugins
    from bunnyland.worldgen import GenOptions
    from bunnyland.worldgen.examples import CLOVER_CITY_DEMO

    plugins = bunnyland_plugins()
    actor = WorldActor()
    apply_plugins(plugins, actor)
    world = await CLOVER_CITY_DEMO.generate(actor, "clover-water-benchmark", GenOptions())
    wick_id = world.characters["wick"]
    saffron_id = world.characters["saffron"]
    for character_id in (wick_id, saffron_id):
        actor.world.get_entity(character_id).remove_component(SuspendedComponent)
    wick = actor.world.get_entity(wick_id)
    points = wick.get_component(ActionPointsComponent)
    replace_component(wick, replace(points, current=50, maximum=50))
    wick.add_component(
        GoalComponent(active_goals=("resolve the rooftop water shortage fairly",))
    )
    obligation = next(
        entity
        for entity in actor.world.query().with_all([ObligationComponent]).execute_entities()
        if entity.get_component(ObligationComponent).source_event_id == "clover-story-1"
    )
    incident = next(
        entity
        for entity in actor.world.query().with_all([IncidentComponent]).execute_entities()
        if entity.get_component(IncidentComponent).kind == "rooftop_water_shortage"
    )
    snapshot = tmp_path / "clover-water-benchmark.json"
    save_world(actor, snapshot, meta=WorldMeta(seed="clover-water-benchmark", plugins=()))

    script = (
        ToolCall("take", {"item_id": str(world.objects["pantry"])}),
        ToolCall("move", {"direction": "west"}),
        ToolCall("move", {"direction": "north"}),
        ToolCall("move", {"direction": "out"}),
        ToolCall("move", {"direction": "east"}),
        ToolCall("take", {"item_id": str(world.objects["water_jug"])}),
        ToolCall("move", {"direction": "west"}),
        ToolCall("move", {"direction": "in"}),
        ToolCall("move", {"direction": "west"}),
        ToolCall("move", {"direction": "up"}),
        ToolCall("drop", {"item_id": str(world.objects["water_jug"])}),
        ToolCall(
            "tell",
            {
                "target_id": str(saffron_id),
                "text": "Thank you for agreeing to share the emergency water fairly.",
                "intent": "praise",
            },
        ),
        ToolCall(
            "resolve_obligation",
            {
                "obligation_id": str(obligation.id),
                "status": "fulfilled",
                "note": "Emergency water delivered and the rooftop ration agreed.",
            },
        ),
        ToolCall("move", {"direction": "down"}),
        ToolCall("move", {"direction": "east"}),
        ToolCall("move", {"direction": "southeast"}),
        ToolCall(
            "write",
            {
                "target_id": str(world.objects["log"]),
                "text": (
                    "Water-01 resolved: rooftop water shortage replenished and the shared "
                    "ration agreed with Saffron."
                ),
            },
        ),
    )

    def relationship_changed(candidate) -> bool:
        return any(
            target_id == wick_id and edge.trust >= 0.1
            for edge, target_id in candidate.world.get_entity(saffron_id).get_relationships(
                SocialBond
            )
        )

    probes = (
        ControllerBenchmarkProbe(
            "water_replenished",
            lambda candidate: container_of(
                candidate.world.get_entity(world.objects["water_jug"])
            )
            == world.rooms["roof"]
            and candidate.world.get_entity(world.objects["water_jug"])
            .get_component(ConsumableComponent)
            .current_uses
            == 4,
        ),
        ControllerBenchmarkProbe(
            "pressure_persisted",
            lambda candidate: candidate.world.get_entity(world.objects["pantry"])
            .get_component(ConsumableComponent)
            .current_uses
            == 2
            and candidate.world.get_entity(saffron_id)
            .get_component(ThirstComponent)
            .meter.value
            >= 70,
        ),
        ControllerBenchmarkProbe(
            "obligation_fulfilled",
            lambda candidate: candidate.world.get_entity(obligation.id)
            .get_component(ObligationComponent)
            .status
            == "fulfilled",
        ),
        ControllerBenchmarkProbe("relationship_changed", relationship_changed),
        ControllerBenchmarkProbe(
            "incident_resolved",
            lambda candidate: candidate.world.get_entity(incident.id)
            .get_component(IncidentComponent)
            .resolved_at_epoch
            is not None,
        ),
        ControllerBenchmarkProbe(
            "aftermath_recorded",
            lambda candidate: "water-01 resolved"
            in candidate.world.get_entity(world.objects["log"])
            .get_component(ReadableComponent)
            .text.lower(),
        ),
    )
    cases = _story_controller_cases("clover-water-shortage", script)

    results = await run_fixed_snapshot_controller_benchmark(
        snapshot,
        registry=PluginRegistry(plugins),
        character_id=str(wick_id),
        cases=cases,
        probes=probes,
        turns=len(script),
    )

    assert len({result.snapshot_sha256 for result in results}) == 1
    for result in results:
        assert result.attempted_actions == len(script)
        assert result.structurally_valid_actions == len(script)
        assert result.committed_commands == len(script) - 1
        assert result.rejected_commands == 1
        assert result.recovered_rejections == 1
        assert result.trace_complete is True
        assert result.outcome_pass_rate == 1.0


async def test_clover_elevator_disruption_reproduces_with_rejection_recovery(tmp_path):
    from bunnyland.core import (
        ActionPointsComponent,
        ButtonComponent,
        ReadableComponent,
        SuspendedComponent,
        WorldActor,
        container_of,
    )
    from bunnyland.core.ecs import replace_component
    from bunnyland.foundation.persona.mechanics import GoalComponent
    from bunnyland.foundation.social.mechanics import ObligationComponent, SocialBond
    from bunnyland.foundation.storyteller.mechanics import IncidentComponent
    from bunnyland.plugins import apply_plugins
    from bunnyland.simpacks.gardensim.mechanics import (
        MachineBreakdownComponent,
        MachineComponent,
    )
    from bunnyland.simpacks.lifesim.mechanics import HasRoutine, RoutineComponent
    from bunnyland.worldgen import GenOptions
    from bunnyland.worldgen.examples import CLOVER_CITY_DEMO

    plugins = bunnyland_plugins()
    actor = WorldActor()
    apply_plugins(plugins, actor)
    world = await CLOVER_CITY_DEMO.generate(actor, "clover-elevator-benchmark", GenOptions())
    jun_id = world.characters["jun"]
    orla_id = world.characters["orla"]
    for character_id in (jun_id, orla_id):
        actor.world.get_entity(character_id).remove_component(SuspendedComponent)
    jun = actor.world.get_entity(jun_id)
    points = jun.get_component(ActionPointsComponent)
    replace_component(jun, replace(points, current=50, maximum=50))
    jun.add_component(
        GoalComponent(active_goals=("repair the elevator and resolve the noise dispute",))
    )
    obligation = next(
        entity
        for entity in actor.world.query().with_all([ObligationComponent]).execute_entities()
        if entity.get_component(ObligationComponent).source_event_id == "clover-story-2"
    )
    incident = next(
        entity
        for entity in actor.world.query().with_all([IncidentComponent]).execute_entities()
        if entity.get_component(IncidentComponent).kind == "elevator_noise_dispute"
    )
    snapshot = tmp_path / "clover-elevator-benchmark.json"
    save_world(actor, snapshot, meta=WorldMeta(seed="clover-elevator-benchmark", plugins=()))

    script = (
        ToolCall("move", {"direction": "up"}),
        ToolCall("move", {"direction": "east"}),
        ToolCall("move", {"direction": "north"}),
        ToolCall("repair_machine", {"machine_id": str(world.objects["panel"])}),
        ToolCall("move", {"direction": "south"}),
        ToolCall("move", {"direction": "west"}),
        ToolCall("move", {"direction": "down"}),
        ToolCall("take", {"item_id": str(world.objects["repair_kit"])}),
        ToolCall("move", {"direction": "up"}),
        ToolCall("move", {"direction": "east"}),
        ToolCall("move", {"direction": "north"}),
        ToolCall(
            "repair_machine",
            {
                "machine_id": str(world.objects["panel"]),
                "tool_id": str(world.objects["repair_kit"]),
            },
        ),
        ToolCall("move", {"direction": "south"}),
        ToolCall("move", {"direction": "southeast"}),
        ToolCall(
            "tell",
            {
                "target_id": str(orla_id),
                "text": "I am sorry the repair delay made the music-room disagreement worse.",
                "intent": "apology",
            },
        ),
        ToolCall(
            "resolve_obligation",
            {
                "obligation_id": str(obligation.id),
                "status": "fulfilled",
                "note": "Elevator repaired and the noise disagreement addressed with Orla.",
            },
        ),
        ToolCall(
            "set_routine",
            {
                "activity": "inspect repaired elevator after restart",
                "interval_seconds": 86400,
                "next_due_epoch": actor.epoch + 3600,
            },
        ),
        ToolCall("move", {"direction": "northwest"}),
        ToolCall("move", {"direction": "northwest"}),
        ToolCall("use", {"item_id": str(world.objects["piano"])}),
        ToolCall("move", {"direction": "southeast"}),
        ToolCall("move", {"direction": "southeast"}),
        ToolCall(
            "write",
            {
                "target_id": str(world.objects["log"]),
                "text": (
                    "Lift-01 resolved: elevator noise dispute closed after the relay repair, "
                    "quiet-hours agreement, and revised inspection routine."
                ),
            },
        ),
    )

    def relationship_changed(candidate) -> bool:
        return any(
            target_id == jun_id and edge.trust >= 0.1
            for edge, target_id in candidate.world.get_entity(orla_id).get_relationships(
                SocialBond
            )
        )

    probes = (
        ControllerBenchmarkProbe(
            "repair_tool_retained",
            lambda candidate: container_of(
                candidate.world.get_entity(world.objects["repair_kit"])
            )
            == jun_id,
        ),
        ControllerBenchmarkProbe(
            "elevator_repaired",
            lambda candidate: not candidate.world.get_entity(world.objects["panel"])
            .has_component(MachineBreakdownComponent)
            and candidate.world.get_entity(world.objects["panel"])
            .get_component(MachineComponent)
            .quality
            >= 0.8,
        ),
        ControllerBenchmarkProbe(
            "noise_stopped",
            lambda candidate: candidate.world.get_entity(world.objects["piano"])
            .get_component(ButtonComponent)
            .pressed,
        ),
        ControllerBenchmarkProbe(
            "obligation_fulfilled",
            lambda candidate: candidate.world.get_entity(obligation.id)
            .get_component(ObligationComponent)
            .status
            == "fulfilled",
        ),
        ControllerBenchmarkProbe("relationship_changed", relationship_changed),
        ControllerBenchmarkProbe(
            "routine_revised",
            lambda candidate: any(
                candidate.world.get_entity(routine_id)
                .get_component(RoutineComponent)
                .activity
                == "inspect repaired elevator after restart"
                for _edge, routine_id in candidate.world.get_entity(jun_id).get_relationships(
                    HasRoutine
                )
            ),
        ),
        ControllerBenchmarkProbe(
            "incident_resolved",
            lambda candidate: candidate.world.get_entity(incident.id)
            .get_component(IncidentComponent)
            .resolved_at_epoch
            is not None,
        ),
        ControllerBenchmarkProbe(
            "aftermath_recorded",
            lambda candidate: "lift-01 resolved"
            in candidate.world.get_entity(world.objects["log"])
            .get_component(ReadableComponent)
            .text.lower(),
        ),
    )
    cases = _story_controller_cases("clover-elevator-disruption", script)

    results = await run_fixed_snapshot_controller_benchmark(
        snapshot,
        registry=PluginRegistry(plugins),
        character_id=str(jun_id),
        cases=cases,
        probes=probes,
        turns=len(script),
    )

    assert len({result.snapshot_sha256 for result in results}) == 1
    for result in results:
        assert result.attempted_actions == len(script)
        assert result.structurally_valid_actions == len(script)
        assert result.committed_commands == len(script) - 1
        assert result.rejected_commands == 1
        assert result.recovered_rejections == 1
        assert result.trace_complete is True
        assert result.outcome_pass_rate == 1.0


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
