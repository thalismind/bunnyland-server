"""Tests for hunger/thirst rise and eat/drink relief."""

from __future__ import annotations

import pytest
from conftest import build_scenario

from bunnyland.core import (
    CommandCost,
    ContainmentMode,
    Contains,
    IdentityComponent,
    Lane,
    build_submitted_command,
    spawn_entity,
)
from bunnyland.mechanics import install_needs
from bunnyland.mechanics.consumables import (
    ConsumableComponent,
    DrinkableComponent,
    FoodComponent,
)
from bunnyland.mechanics.meter import Meter
from bunnyland.mechanics.needs import HungerComponent, ThirstComponent

HOUR = 3600.0


def needs_scenario(*, hunger=0.0, thirst=0.0):
    scenario = build_scenario()
    install_needs(scenario.actor)
    char = scenario.actor.world.get_entity(scenario.character)
    char.add_component(HungerComponent(meter=Meter(value=hunger), metabolism=2.0))
    char.add_component(ThirstComponent(meter=Meter(value=thirst), hydration_loss_rate=3.0))
    return scenario


def verb(scenario, command_type, **payload):
    return build_submitted_command(
        character_id=str(scenario.character),
        controller_id=str(scenario.controller),
        controller_generation=scenario.generation,
        command_type=command_type,
        cost=CommandCost(action=1),
        lane=Lane.WORLD,
        payload=payload,
    )


def give_item(scenario, components, *, in_inventory=True):
    item = spawn_entity(scenario.actor.world, components)
    holder = scenario.character if in_inventory else scenario.room_a
    mode = ContainmentMode.INVENTORY if in_inventory else ContainmentMode.ROOM_CONTENT
    scenario.actor.world.get_entity(holder).add_relationship(Contains(mode=mode), item.id)
    return item.id


# -- rise over time ---------------------------------------------------------------------


async def test_hunger_and_thirst_rise_independently():
    scenario = needs_scenario()
    char = scenario.actor.world.get_entity(scenario.character)

    await scenario.actor.tick(HOUR)
    # hunger += metabolism(2.0)*1h; thirst += loss(3.0)*1h
    assert char.get_component(HungerComponent).meter.value == pytest.approx(2.0)
    assert char.get_component(ThirstComponent).meter.value == pytest.approx(3.0)


async def test_suspended_character_does_not_get_hungry():
    scenario = needs_scenario()
    no_op = spawn_entity(scenario.actor.world)
    scenario.actor.suspend(scenario.character, no_op.id)

    await scenario.actor.tick(10 * HOUR)
    char = scenario.actor.world.get_entity(scenario.character)
    assert char.get_component(HungerComponent).meter.value == pytest.approx(0.0)
    assert char.get_component(ThirstComponent).meter.value == pytest.approx(0.0)


# -- eat --------------------------------------------------------------------------------


async def test_eat_reduces_hunger_and_consumes_item():
    scenario = needs_scenario(hunger=50.0)
    berry = give_item(
        scenario,
        [
            IdentityComponent(name="berry", kind="item"),
            FoodComponent(nutrition=5.0, satiety=20.0),
            ConsumableComponent(current_uses=1, max_uses=1),
        ],
    )

    await scenario.actor.submit(verb(scenario, "eat", item_id=str(berry)))
    await scenario.actor.tick(0.0)  # no rise this tick

    char = scenario.actor.world.get_entity(scenario.character)
    assert char.get_component(HungerComponent).meter.value == pytest.approx(30.0)
    assert not scenario.actor.world.has_entity(berry)  # single-use item consumed


async def test_eat_non_food_is_rejected():
    scenario = needs_scenario(hunger=50.0)
    rock = give_item(scenario, [IdentityComponent(name="rock", kind="item")])

    await scenario.actor.submit(verb(scenario, "eat", item_id=str(rock)))
    await scenario.actor.tick(0.0)

    char = scenario.actor.world.get_entity(scenario.character)
    assert char.get_component(HungerComponent).meter.value == pytest.approx(50.0)
    assert scenario.actor.world.has_entity(rock)


# -- drink ------------------------------------------------------------------------------


async def test_drink_reduces_thirst_from_renewable_source():
    scenario = needs_scenario(thirst=60.0)
    # A basin in the room: drinkable but not consumable -> renewable.
    basin = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="basin", kind="furniture"), DrinkableComponent(hydration=25.0)],
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), basin.id
    )

    await scenario.actor.submit(verb(scenario, "drink", source_id=str(basin.id)))
    await scenario.actor.tick(0.0)

    char = scenario.actor.world.get_entity(scenario.character)
    assert char.get_component(ThirstComponent).meter.value == pytest.approx(35.0)
    assert scenario.actor.world.has_entity(basin.id)  # renewable, not consumed


async def test_drink_meter_clamps_at_minimum():
    scenario = needs_scenario(thirst=10.0)
    cup = give_item(
        scenario,
        [IdentityComponent(name="cup", kind="item"), DrinkableComponent(hydration=50.0)],
    )

    await scenario.actor.submit(verb(scenario, "drink", source_id=str(cup)))
    await scenario.actor.tick(0.0)

    char = scenario.actor.world.get_entity(scenario.character)
    assert char.get_component(ThirstComponent).meter.value == pytest.approx(0.0)
