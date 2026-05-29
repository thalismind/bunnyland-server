"""Tests for control verbs (take-control / release-to-llm / suspend / resume)."""

from __future__ import annotations

from conftest import build_scenario

from bunnyland.core import (
    CommandCost,
    DiscordControllerComponent,
    Lane,
    LLMControllerComponent,
    SuspendedComponent,
    build_submitted_command,
    spawn_entity,
)
from bunnyland.core.events import ControllerChangedEvent

HOUR = 3600.0


def control_cmd(scenario, command_type, controller_id, **payload):
    return build_submitted_command(
        character_id=str(scenario.character),
        controller_id=str(scenario.controller),  # ignored for control verbs
        controller_generation=-1,  # control verbs bypass generation checks
        command_type=command_type,
        cost=CommandCost(),  # control verbs are free
        lane=Lane.WORLD,
        payload={"controller_id": str(controller_id), **payload},
    )


def collect(actor, event_type):
    seen = []
    actor.bus.subscribe(event_type, seen.append)
    return seen


def current_controller(scenario):
    from bunnyland.core import ControlledBy

    char = scenario.actor.world.get_entity(scenario.character)
    rels = char.get_relationships(ControlledBy)
    return rels[0][1] if rels else None


async def test_take_control_assigns_discord_controller_and_bumps_generation():
    scenario = build_scenario()  # starts under an LLM controller, generation 0
    human = spawn_entity(
        scenario.actor.world,
        [DiscordControllerComponent(discord_user_id=1, default_channel_id=2)],
    )
    changed = collect(scenario.actor, ControllerChangedEvent)

    await scenario.actor.submit(control_cmd(scenario, "take-control", human.id))
    await scenario.actor.tick(HOUR)

    assert current_controller(scenario) == human.id
    assert changed[0].controller_kind == "discord"
    assert changed[0].generation == 1


async def test_release_to_llm_reassigns_to_llm_controller():
    scenario = build_scenario()
    human = spawn_entity(
        scenario.actor.world,
        [DiscordControllerComponent(discord_user_id=1, default_channel_id=2)],
    )
    await scenario.actor.submit(control_cmd(scenario, "take-control", human.id))
    await scenario.actor.tick(HOUR)

    llm = spawn_entity(
        scenario.actor.world, [LLMControllerComponent(profile_name="p", model="m")]
    )
    await scenario.actor.submit(control_cmd(scenario, "release-to-llm", llm.id))
    await scenario.actor.tick(HOUR)

    assert current_controller(scenario) == llm.id


async def test_suspend_then_resume():
    scenario = build_scenario()
    no_op = spawn_entity(scenario.actor.world)
    char = scenario.actor.world.get_entity(scenario.character)

    await scenario.actor.submit(control_cmd(scenario, "suspend", no_op.id, reason="afk"))
    await scenario.actor.tick(HOUR)
    assert char.has_component(SuspendedComponent)

    human = spawn_entity(
        scenario.actor.world,
        [DiscordControllerComponent(discord_user_id=7, default_channel_id=8)],
    )
    await scenario.actor.submit(control_cmd(scenario, "resume", human.id))
    await scenario.actor.tick(HOUR)

    assert not char.has_component(SuspendedComponent)
    assert current_controller(scenario) == human.id


async def test_control_verb_with_missing_controller_is_rejected():
    scenario = build_scenario()
    from bunnyland.core.events import CommandRejectedEvent

    rejects = collect(scenario.actor, CommandRejectedEvent)
    # controller_id points at a non-existent entity
    bogus = build_submitted_command(
        character_id=str(scenario.character),
        controller_id=str(scenario.controller),
        controller_generation=-1,
        command_type="take-control",
        cost=CommandCost(),
        lane=Lane.WORLD,
        payload={"controller_id": "entity_999999999"},
    )
    await scenario.actor.submit(bogus)
    await scenario.actor.tick(HOUR)

    assert any(r.reason == "controller does not exist" for r in rejects)


async def test_handoff_flushes_commands_still_queued_under_old_controller():
    # A move that can't be afforded stays queued; a controller handoff flushes it.
    scenario = build_scenario(action_current=0.0)
    move = build_submitted_command(
        character_id=str(scenario.character),
        controller_id=str(scenario.controller),
        controller_generation=scenario.generation,
        command_type="move",
        cost=CommandCost(action=1),
        lane=Lane.WORLD,
        payload={"direction": "north"},
    )
    await scenario.actor.submit(move)
    await scenario.actor.tick(0.1)  # ingested + queued, but unaffordable -> waits
    assert scenario.actor.queues.has_pending(str(scenario.character), Lane.WORLD)

    new_controller = spawn_entity(scenario.actor.world)
    scenario.actor.assign_controller(scenario.character, new_controller.id)

    assert not scenario.actor.queues.has_pending(str(scenario.character), Lane.WORLD)
