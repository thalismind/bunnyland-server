"""Tests for sleep / wake / wait and the asleep/downed action gates."""

from __future__ import annotations

from conftest import build_scenario

from bunnyland.core import (
    CharacterComponent,
    CommandCost,
    ContainmentMode,
    Contains,
    IdentityComponent,
    Lane,
    SayHandler,
    SleepHandler,
    SleepingComponent,
    WaitHandler,
    WakeHandler,
    build_submitted_command,
    spawn_entity,
)
from bunnyland.core.events import CommandExecutedEvent, CommandRejectedEvent, SpeechSaidEvent

HOUR = 3600.0


def lifecycle_scenario():
    scenario = build_scenario()
    for handler in (SleepHandler(), WakeHandler(), WaitHandler(), SayHandler()):
        scenario.actor.register_handler(handler)
    return scenario


def cmd(scenario, command_type, *, cost=None, lane=Lane.WORLD, **payload):
    return build_submitted_command(
        character_id=str(scenario.character),
        controller_id=str(scenario.controller),
        controller_generation=scenario.generation,
        command_type=command_type,
        cost=cost if cost is not None else CommandCost(action=1),
        lane=lane,
        payload=payload,
    )


def collect(actor, event_type):
    seen = []
    actor.bus.subscribe(event_type, seen.append)
    return seen


async def test_sleep_then_wake():
    scenario = lifecycle_scenario()
    char = scenario.actor.world.get_entity(scenario.character)

    await scenario.actor.submit(cmd(scenario, "sleep"))
    await scenario.actor.tick(HOUR)
    assert char.has_component(SleepingComponent)

    await scenario.actor.submit(cmd(scenario, "wake", cost=CommandCost()))
    await scenario.actor.tick(HOUR)
    assert not char.has_component(SleepingComponent)


async def test_asleep_character_cannot_act_except_wake():
    scenario = lifecycle_scenario()
    rejects = collect(scenario.actor, CommandRejectedEvent)

    await scenario.actor.submit(cmd(scenario, "sleep"))
    await scenario.actor.tick(HOUR)

    # A say command while asleep is rejected...
    await scenario.actor.submit(
        cmd(scenario, "say", cost=CommandCost(action=1, focus=1), text="hi")
    )
    await scenario.actor.tick(HOUR)
    assert any(r.reason == "character is asleep" for r in rejects)

    char = scenario.actor.world.get_entity(scenario.character)
    assert char.has_component(SleepingComponent)  # still asleep


async def test_sleeping_listener_does_not_hear_say():
    scenario = lifecycle_scenario()
    sleeper = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="Hazel", kind="character"), CharacterComponent()],
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), sleeper.id
    )
    sleeper.add_component(SleepingComponent(started_at_epoch=0))
    said = collect(scenario.actor, SpeechSaidEvent)

    await scenario.actor.submit(
        cmd(scenario, "say", cost=CommandCost(action=1, focus=1), text="Anyone awake?")
    )
    await scenario.actor.tick(HOUR)

    assert str(sleeper.id) not in said[0].target_ids


async def test_wait_yields_turn_without_state_change():
    scenario = lifecycle_scenario()
    executed = collect(scenario.actor, CommandExecutedEvent)

    await scenario.actor.submit(cmd(scenario, "wait", cost=CommandCost()))
    await scenario.actor.tick(HOUR)

    assert len(executed) == 1
    char = scenario.actor.world.get_entity(scenario.character)
    assert not char.has_component(SleepingComponent)
