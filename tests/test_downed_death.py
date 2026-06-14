"""Tests for the downed -> recovery -> death consequence pass (spec 8.3-8.4)."""

from __future__ import annotations

from dataclasses import replace

from conftest import build_scenario

from bunnyland.core import (
    DeadComponent,
    DownedComponent,
    HealthComponent,
    SuspendedComponent,
    replace_component,
    spawn_entity,
)
from bunnyland.core.events import (
    CharacterDiedEvent,
    CharacterDownedEvent,
    CharacterRevivedEvent,
)
from bunnyland.mechanics.history import (
    death_consequence_for_event,
    install_history,
    world_history_records,
)

HOUR = 3600.0


def collect(actor, event_type):
    seen = []
    actor.bus.subscribe(event_type, seen.append)
    return seen


def with_health(scenario, current):
    char = scenario.actor.world.get_entity(scenario.character)
    char.add_component(HealthComponent(current=current, maximum=100.0))
    return char


async def test_zero_health_downs_active_character():
    scenario = build_scenario()
    char = with_health(scenario, 0.0)
    downed = collect(scenario.actor, CharacterDownedEvent)

    await scenario.actor.tick(HOUR)

    assert char.has_component(DownedComponent)
    assert not char.has_component(DeadComponent)
    assert len(downed) == 1


async def test_downed_then_dies_after_failed_recovery_checks():
    scenario = build_scenario()
    install_history(scenario.actor)
    char = with_health(scenario, 0.0)
    died = collect(scenario.actor, CharacterDiedEvent)

    # First tick downs (checks_remaining=3); subsequent ticks fail checks 3->2->1->dead.
    for _ in range(5):
        await scenario.actor.tick(HOUR)

    assert char.has_component(DeadComponent)
    assert not char.has_component(DownedComponent)
    assert len(died) == 1
    assert death_consequence_for_event(scenario.actor.world, died[0].event_id) is not None
    assert world_history_records(scenario.actor.world)[0][1].tags == (
        "death",
        "loss",
        "consequence",
    )


async def test_healing_revives_a_downed_character():
    scenario = build_scenario()
    char = with_health(scenario, 0.0)
    revived = collect(scenario.actor, CharacterRevivedEvent)

    await scenario.actor.tick(HOUR)  # downed
    assert char.has_component(DownedComponent)

    # Heal above zero before checks run out.
    replace_component(char, replace(char.get_component(HealthComponent), current=50.0))
    await scenario.actor.tick(HOUR)

    assert not char.has_component(DownedComponent)
    assert not char.has_component(DeadComponent)
    assert len(revived) == 1


async def test_suspended_character_cannot_be_downed_or_die():
    scenario = build_scenario()
    install_history(scenario.actor)
    char = with_health(scenario, 0.0)
    no_op = spawn_entity(scenario.actor.world)
    scenario.actor.suspend(scenario.character, no_op.id)

    for _ in range(5):
        await scenario.actor.tick(HOUR)

    assert char.has_component(SuspendedComponent)
    assert not char.has_component(DownedComponent)
    assert not char.has_component(DeadComponent)
    assert world_history_records(scenario.actor.world) == []


async def test_stable_downed_character_does_not_die():
    scenario = build_scenario()
    char = with_health(scenario, 0.0)
    await scenario.actor.tick(HOUR)  # downed with checks_remaining=3

    # A medic stabilizes them: stable downed characters stop failing checks.
    replace_component(char, replace(char.get_component(DownedComponent), stable=True))
    for _ in range(5):
        await scenario.actor.tick(HOUR)

    assert char.has_component(DownedComponent)
    assert not char.has_component(DeadComponent)
