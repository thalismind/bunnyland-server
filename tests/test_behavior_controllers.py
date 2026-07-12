"""Tests for the behavioral (behavior-tree) and scripted character controllers."""

from __future__ import annotations

from dataclasses import replace

import pytest
from conftest import build_scenario

from bunnyland.core import (
    CharacterComponent,
    ContainmentMode,
    Contains,
    IdentityComponent,
    PortableComponent,
    spawn_entity,
)
from bunnyland.core.controllers import (
    BehaviorControllerComponent,
    DiscordControllerComponent,
    ScriptedControllerComponent,
)
from bunnyland.core.systems import ClaimTimeoutSystem
from bunnyland.llm_agents import (
    ControllerDispatch,
    ScriptedAgent,
    ToolCall,
    behavior_tree_names,
    register_behavior_tree,
    register_script,
    resolve_behavior_tree,
    resolve_script,
    script_names,
)
from bunnyland.llm_agents.behavior_tree import (
    ACTION_LIBRARY,
    CONDITION_LIBRARY,
    Action,
    BehaviorTree,
    BehaviorTreeAgent,
    Condition,
    Node,
    Selector,
    Sequence,
    Status,
    _greet_first_character,
    _has_open_exit,
    _move_first_exit,
    _say_action,
    _take_first_item,
    _warn_first_character,
    register_action,
    register_condition,
)
from bunnyland.plugins import PluginRegistry, bunnyland_plugins
from bunnyland.prompts.builder import PromptBuilder, PromptContext
from bunnyland.scripting.runtime import ScriptRuntime

_ScriptRuntime = ScriptRuntime


def ScriptRuntime(*args, **kwargs):
    return _ScriptRuntime(*args, registry=PluginRegistry(bunnyland_plugins()), **kwargs)


def _context(scenario, **overrides):
    context = PromptBuilder(scenario.actor.world).build(scenario.character)
    return replace(context, **overrides) if overrides else context


def _assign(scenario, component) -> int:
    controller = spawn_entity(scenario.actor.world, [component])
    return scenario.actor.assign_controller(scenario.character, controller.id)


def _add_visitor(scenario, name: str):
    world = scenario.actor.world
    visitor = spawn_entity(
        world, [IdentityComponent(name=name, kind="character"), CharacterComponent()]
    )
    world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), visitor.id
    )
    return visitor.id


# -- behavior-tree nodes ------------------------------------------------------------------


def test_base_node_tick_is_abstract():
    with pytest.raises(NotImplementedError):
        Node().tick(None)


def test_condition_reports_success_and_failure():
    truthy = Condition(lambda _ctx: True)
    falsy = Condition(lambda _ctx: False)
    assert truthy.tick(None) == (Status.SUCCESS, None)
    assert falsy.tick(None) == (Status.FAILURE, None)


def test_action_succeeds_only_when_it_produces_a_call():
    call = ToolCall("move", {"direction": "north"})
    acting = Action(lambda _ctx: call)
    waiting = Action(lambda _ctx: None)
    assert acting.tick(None) == (Status.SUCCESS, call)
    assert waiting.tick(None) == (Status.FAILURE, None)


def test_sequence_fails_when_a_child_fails():
    call = ToolCall("move", {"direction": "north"})
    sequence = Sequence(Condition(lambda _ctx: False), Action(lambda _ctx: call))
    assert sequence.tick(None) == (Status.FAILURE, None)


def test_sequence_returns_first_acting_child():
    call = ToolCall("move", {"direction": "north"})
    sequence = Sequence(Condition(lambda _ctx: True), Action(lambda _ctx: call))
    assert sequence.tick(None) == (Status.SUCCESS, call)


def test_sequence_without_acting_child_fails():
    sequence = Sequence(Condition(lambda _ctx: True))
    assert sequence.tick(None) == (Status.FAILURE, None)


def test_selector_returns_first_successful_branch():
    first = ToolCall("take", {"item_id": "x"})
    second = ToolCall("move", {"direction": "north"})
    selector = Selector(
        Action(lambda _ctx: None),
        Action(lambda _ctx: first),
        Action(lambda _ctx: second),
    )
    assert selector.tick(None) == (Status.SUCCESS, first)


def test_selector_fails_when_all_branches_fail():
    selector = Selector(Action(lambda _ctx: None), Condition(lambda _ctx: False))
    assert selector.tick(None) == (Status.FAILURE, None)


# -- built-in trees and the tree agent ----------------------------------------------------


async def test_idle_tree_always_waits():
    scenario = build_scenario()
    agent = BehaviorTreeAgent(resolve_behavior_tree("idle"))
    assert await agent.decide("", _context(scenario), character_id=str(scenario.character)) is None


async def test_wanderer_tree_takes_first_open_exit():
    scenario = build_scenario()
    agent = BehaviorTreeAgent(resolve_behavior_tree("wanderer"))
    assert await agent.decide(
        "", _context(scenario), character_id=str(scenario.character)
    ) == ToolCall(
        "move", {"direction": "north"}
    )


async def test_forager_tree_takes_a_visible_item_first():
    scenario = build_scenario()
    world = scenario.actor.world
    item = spawn_entity(
        world, [IdentityComponent(name="acorn", kind="item"), PortableComponent(can_pick_up=True)]
    )
    world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), item.id
    )
    agent = BehaviorTreeAgent(resolve_behavior_tree("forager"))
    decision = await agent.decide("", _context(scenario), character_id=str(scenario.character))
    assert decision == ToolCall("take", {"item_id": "acorn"})


async def test_forager_tree_moves_when_nothing_to_take():
    scenario = build_scenario()
    agent = BehaviorTreeAgent(resolve_behavior_tree("forager"))
    assert await agent.decide(
        "", _context(scenario), character_id=str(scenario.character)
    ) == ToolCall(
        "move", {"direction": "north"}
    )


async def test_guard_tree_warns_visitors_and_holds_alone():
    scenario = build_scenario()
    agent = BehaviorTreeAgent(resolve_behavior_tree("guard"))
    alone = _context(scenario)
    assert await agent.decide("", alone, character_id=str(scenario.character)) is None
    _add_visitor(scenario, "Hazel")
    context = _context(scenario)
    assert await agent.decide("", context, character_id=str(scenario.character)) == ToolCall(
        "say", {"text": "Hazel, keep your distance.", "intent": "threat", "approach": "cold"}
    )


async def test_greeter_tree_greets_visitors():
    scenario = build_scenario()
    _add_visitor(scenario, "Hazel")
    context = _context(scenario)
    agent = BehaviorTreeAgent(resolve_behavior_tree("greeter"))
    assert await agent.decide("", context, character_id=str(scenario.character)) == ToolCall(
        "say", {"text": "Hazel, good to see you.", "intent": "praise", "approach": "friendly"}
    )


def test_behavior_tree_agent_exposes_its_tree():
    tree = resolve_behavior_tree("idle")
    assert BehaviorTreeAgent(tree).tree is tree


def _bare_context(**overrides) -> PromptContext:
    base = PromptContext(
        name="Juniper",
        kind="character",
        status="active",
        action=(1.0, 1.0),
        focus=(1.0, 1.0),
        location_title="Burrow",
        room_summary="A quiet burrow.",
    )
    return replace(base, **overrides)


def test_leaf_choosers_wait_when_their_command_is_unavailable():
    # No matching command available -> each chooser declines to act.
    objects = _bare_context(visible_objects=("rock",))
    assert _take_first_item(objects) is None
    assert _take_first_item(_bare_context(visible_objects=())) is None
    assert _move_first_exit(_bare_context(exits=("north",))) is None
    assert _greet_first_character(_bare_context(visible_characters=())) is None
    assert _greet_first_character(_bare_context(visible_characters=("Hazel",))) is None
    assert _warn_first_character(_bare_context(visible_characters=())) is None
    assert _warn_first_character(_bare_context(visible_characters=("Hazel",))) is None


def test_has_open_exit_reflects_unlocked_exits():
    # No exits -> no open exit; a plain exit is open; a fully-locked exit is not.
    assert _has_open_exit(_bare_context(exits=())) is False
    assert _has_open_exit(_bare_context(exits=("north to Meadow",))) is True
    assert _has_open_exit(_bare_context(exits=("north to Vault (locked)",))) is False


def test_say_action_waits_when_say_command_unavailable():
    chooser = _say_action({"text": "hello there", "intent": "praise", "approach": "friendly"})
    # 'say' is not in the available commands -> the chooser declines to act.
    assert chooser(_bare_context(commands=())) is None
    # With the command available it emits the say call verbatim.
    call = chooser(_bare_context(commands=("say something to the room",)))
    assert call == ToolCall(
        "say", {"text": "hello there", "intent": "praise", "approach": "friendly"}
    )


# -- registries ---------------------------------------------------------------------------


def test_behavior_registry_round_trip_and_unknown():
    tree = BehaviorTree("custom-test-tree", Selector(Action(lambda _ctx: None)))
    register_behavior_tree(tree)
    assert resolve_behavior_tree("custom-test-tree") is tree
    assert "custom-test-tree" in behavior_tree_names()
    assert "idle" in behavior_tree_names()
    with pytest.raises(ValueError, match="unknown behavior tree"):
        resolve_behavior_tree("no-such-tree")


def test_script_registry_round_trip_and_unknown():
    calls = (ToolCall("move", {"direction": "north"}),)
    register_script("custom-test-script", calls)
    assert resolve_script("custom-test-script") == calls
    assert "custom-test-script" in script_names()
    assert "wait" in script_names()
    assert "hungry-courier-intro" in script_names()
    with pytest.raises(ValueError, match="unknown script"):
        resolve_script("no-such-script")


def test_register_condition_makes_factory_available():
    register_condition("always-test-true", lambda _params: lambda _ctx: True)
    assert CONDITION_LIBRARY["always-test-true"]({})(_bare_context()) is True


def test_register_action_makes_factory_available():
    call = ToolCall("move", {"direction": "north"})
    register_action("fixed-test-move", lambda _params: lambda _ctx: call)
    assert ACTION_LIBRARY["fixed-test-move"]({})(_bare_context()) == call


# -- scripted agent replay ----------------------------------------------------------------


async def test_scripted_agent_replays_then_waits():
    agent = ScriptedAgent([ToolCall("move", {"direction": "north"})])
    assert await agent.decide("", None, character_id="c") == ToolCall(
        "move", {"direction": "north"}
    )
    assert await agent.decide("", None, character_id="c") is None


async def test_scripted_agent_loops_when_enabled():
    calls = [ToolCall("move", {"direction": "north"}), ToolCall("move", {"direction": "south"})]
    agent = ScriptedAgent(calls, loop=True)
    seen = [await agent.decide("", None, character_id="c") for _ in range(3)]
    assert seen == [calls[0], calls[1], calls[0]]


async def test_scripted_agent_empty_script_always_waits():
    agent = ScriptedAgent([], loop=True)
    assert await agent.decide("", None, character_id="c") is None


# -- dispatch driving the new controller types --------------------------------------------


async def test_dispatch_drives_behavioral_controller():
    scenario = build_scenario()
    _assign(scenario, BehaviorControllerComponent(behavior_name="wanderer"))
    dispatch = ControllerDispatch(
        scenario.actor, PromptBuilder(scenario.actor.world), ScriptedAgent([])
    )

    assert await dispatch.run_once() == []
    decisions = await dispatch.await_pending()

    assert [d.tool for d in decisions] == ["move"]
    assert not scenario.actor._inbox.empty()


async def test_dispatch_drives_scripted_controller_across_ticks():
    scenario = build_scenario()
    register_script(
        "north-then-south",
        [ToolCall("move", {"direction": "north"}), ToolCall("move", {"direction": "south"})],
    )
    _assign(scenario, ScriptedControllerComponent(script_name="north-then-south"))
    dispatch = ControllerDispatch(
        scenario.actor, PromptBuilder(scenario.actor.world), ScriptedAgent([])
    )

    assert await dispatch.run_once() == []
    first = await dispatch.await_pending()
    assert await dispatch.run_once() == []
    second = await dispatch.await_pending()
    assert await dispatch.run_once() == []
    third = await dispatch.await_pending()

    assert [d.summary.split()[0] for d in first] == ["move"]
    assert "north" in first[0].summary
    assert "south" in second[0].summary
    # Exhausted (non-looping) script waits.
    assert third[0].tool is None


async def test_dispatch_loops_scripted_controller():
    scenario = build_scenario()
    register_script("loop-north", [ToolCall("move", {"direction": "north"})])
    _assign(scenario, ScriptedControllerComponent(script_name="loop-north", loop=True))
    dispatch = ControllerDispatch(
        scenario.actor, PromptBuilder(scenario.actor.world), ScriptedAgent([])
    )

    await dispatch.run_once()
    assert (await dispatch.await_pending())[0].tool == "move"
    await dispatch.run_once()
    assert (await dispatch.await_pending())[0].tool == "move"


async def test_dispatch_reuses_cached_behavior_agent_across_ticks():
    scenario = build_scenario()
    _assign(scenario, BehaviorControllerComponent(behavior_name="wanderer"))
    dispatch = ControllerDispatch(
        scenario.actor, PromptBuilder(scenario.actor.world), ScriptedAgent([])
    )

    await dispatch.run_once()
    await dispatch.await_pending()
    first_agent = dispatch._behavior_agents["wanderer"]
    await dispatch.run_once()
    await dispatch.await_pending()
    second_agent = dispatch._behavior_agents["wanderer"]

    # The behavior agent is built once and then served from cache (the agent-not-None arc),
    # so the same instance drives every tick.
    assert first_agent is second_agent
    assert list(dispatch._behavior_agents) == ["wanderer"]


async def test_dispatch_throttles_behavioral_controller_by_act_every_ticks():
    scenario = build_scenario()
    _assign(scenario, BehaviorControllerComponent(behavior_name="wanderer", act_every_ticks=2))
    dispatch = ControllerDispatch(
        scenario.actor, PromptBuilder(scenario.actor.world), ScriptedAgent([])
    )

    assert await dispatch.run_once() == []  # tick 1 skipped
    assert await dispatch.run_once() == []  # tick 2 schedules the decision
    assert [d.tool for d in await dispatch.await_pending()] == ["move"]


async def test_dispatch_waits_on_unknown_behavior_name_without_crashing():
    scenario = build_scenario()
    _assign(scenario, BehaviorControllerComponent(behavior_name="does-not-exist"))
    dispatch = ControllerDispatch(
        scenario.actor, PromptBuilder(scenario.actor.world), ScriptedAgent([])
    )

    decisions = await dispatch.run_once()

    assert len(decisions) == 1
    assert decisions[0].tool is None
    assert "unknown behavior tree" in decisions[0].summary
    assert scenario.actor._inbox.empty()


async def test_dispatch_rebuilds_scripted_agent_when_script_changes():
    scenario = build_scenario()
    register_script("alpha", [ToolCall("move", {"direction": "north"})])
    register_script("beta", [ToolCall("move", {"direction": "south"})])
    gen = _assign(scenario, ScriptedControllerComponent(script_name="alpha"))
    assert gen >= 0
    dispatch = ControllerDispatch(
        scenario.actor, PromptBuilder(scenario.actor.world), ScriptedAgent([])
    )
    await dispatch.run_once()
    assert "north" in (await dispatch.await_pending())[0].summary

    _assign(scenario, ScriptedControllerComponent(script_name="beta"))
    await dispatch.run_once()
    assert "south" in (await dispatch.await_pending())[0].summary


# -- controller-kind detection ------------------------------------------------------------


def test_world_actor_controller_kind_recognizes_new_types():
    scenario = build_scenario()
    actor = scenario.actor
    behavioral = spawn_entity(actor.world, [BehaviorControllerComponent()])
    scripted = spawn_entity(actor.world, [ScriptedControllerComponent()])
    assert actor._controller_kind(behavioral.id) == "behavioral"
    assert actor._controller_kind(scripted.id) == "scripted"


def test_claim_timeout_system_controller_kind_recognizes_new_types():
    scenario = build_scenario()
    behavioral = spawn_entity(scenario.actor.world, [BehaviorControllerComponent()])
    scripted = spawn_entity(scenario.actor.world, [ScriptedControllerComponent()])
    assert ClaimTimeoutSystem._controller_kind(behavioral) == "behavioral"
    assert ClaimTimeoutSystem._controller_kind(scripted) == "scripted"


def test_scripting_runtime_controller_kind_recognizes_new_types():
    scenario = build_scenario()
    runtime = ScriptRuntime()
    _assign(scenario, BehaviorControllerComponent())
    character = scenario.actor.world.get_entity(scenario.character)
    assert runtime._controller_kind(scenario.actor, character) == "behavioral"
    _assign(scenario, ScriptedControllerComponent())
    character = scenario.actor.world.get_entity(scenario.character)
    assert runtime._controller_kind(scenario.actor, character) == "scripted"


def test_prompt_status_line_describes_new_controllers():
    scenario = build_scenario()
    _assign(scenario, BehaviorControllerComponent())
    context = PromptBuilder(scenario.actor.world).build(scenario.character)
    assert "controlled by a behavior routine" in context.status
    _assign(scenario, ScriptedControllerComponent())
    context = PromptBuilder(scenario.actor.world).build(scenario.character)
    assert "controlled by a scripted routine" in context.status


def test_discord_controller_kind_unaffected():
    scenario = build_scenario()
    discord = spawn_entity(
        scenario.actor.world,
        [DiscordControllerComponent(discord_user_id=1, default_channel_id=2)],
    )
    assert scenario.actor._controller_kind(discord.id) == "discord"
