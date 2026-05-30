"""End-to-end checks for core simulation mechanics."""

from __future__ import annotations

import pytest
from conftest import build_scenario

from bunnyland.core import (
    ActionPointsComponent,
    BleedingComponent,
    BodyPlanComponent,
    CharacterComponent,
    CommandCost,
    ContainmentMode,
    Contains,
    EncumbranceComponent,
    HasInjury,
    HealthComponent,
    IdentityComponent,
    Lane,
    PainComponent,
    WeightComponent,
    build_submitted_command,
    spawn_entity,
)
from bunnyland.core.events import EncumbranceChangedEvent, InjuryAddedEvent
from bunnyland.mechanics.barbariansim import AttackHandler

HOUR = 3600.0


def collect(actor, event_type):
    seen = []
    actor.bus.subscribe(event_type, seen.append)
    return seen


async def test_carried_weight_updates_load_and_reduces_speed_when_over_capacity():
    scenario = build_scenario()
    character = scenario.actor.world.get_entity(scenario.character)
    character.add_component(EncumbranceComponent(capacity=5.0))
    boulder = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="basalt boulder", kind="item"),
            WeightComponent(weight=10.0),
        ],
    )
    character.add_relationship(Contains(mode=ContainmentMode.INVENTORY), boulder.id)
    changes = collect(scenario.actor, EncumbranceChangedEvent)

    await scenario.actor.tick(HOUR)

    encumbrance = character.get_component(EncumbranceComponent)
    assert encumbrance.current_load == pytest.approx(10.0)
    assert encumbrance.overburdened is True
    assert encumbrance.speed_multiplier == pytest.approx(0.5)
    assert changes[-1].actor_id == str(scenario.character)
    assert changes[-1].speed_multiplier == pytest.approx(0.5)


async def test_dropping_heavy_item_restores_encumbrance_speed():
    scenario = build_scenario()
    character = scenario.actor.world.get_entity(scenario.character)
    character.add_component(EncumbranceComponent(capacity=5.0))
    boulder = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="basalt boulder", kind="item"),
            WeightComponent(weight=10.0),
        ],
    )
    character.add_relationship(Contains(mode=ContainmentMode.INVENTORY), boulder.id)

    await scenario.actor.tick(HOUR)
    character.remove_relationship(Contains, boulder.id)
    await scenario.actor.tick(HOUR)

    encumbrance = character.get_component(EncumbranceComponent)
    assert encumbrance.current_load == pytest.approx(0.0)
    assert encumbrance.overburdened is False
    assert encumbrance.speed_multiplier == pytest.approx(1.0)


async def test_fight_creates_injury_and_bleeding_reduces_health():
    scenario = build_scenario()
    scenario.actor.register_handler(AttackHandler())
    attacker = scenario.actor.world.get_entity(scenario.character)
    attacker.add_component(HealthComponent(current=20.0, maximum=20.0))
    target = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="Hazel", kind="character"),
            CharacterComponent(),
            ActionPointsComponent(current=5.0, maximum=5.0),
            HealthComponent(current=20.0, maximum=20.0),
            BodyPlanComponent(parts=("torso",), vital_parts=("torso",)),
        ],
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), target.id
    )
    injuries = collect(scenario.actor, InjuryAddedEvent)

    await scenario.actor.submit(
        build_submitted_command(
            character_id=str(scenario.character),
            controller_id=str(scenario.controller),
            controller_generation=scenario.generation,
            command_type="attack",
            cost=CommandCost(action=1),
            lane=Lane.WORLD,
            payload={"target_id": str(target.id)},
        )
    )
    await scenario.actor.tick(HOUR)

    target_health = target.get_component(HealthComponent)
    assert target_health.current == pytest.approx(15.0)
    assert target.has_component(PainComponent)
    assert target.get_component(PainComponent).current == pytest.approx(5.0)
    assert target.has_component(BleedingComponent)
    assert target.get_component(BleedingComponent).rate == pytest.approx(0.5)
    assert len(target.get_relationships(HasInjury)) == 1
    assert injuries[-1].body_part == "torso"

    await scenario.actor.tick(HOUR)

    assert target.get_component(HealthComponent).current == pytest.approx(14.5)
    assert target.get_component(BleedingComponent).accumulated_loss == pytest.approx(0.5)
