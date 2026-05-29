"""Tests for take / drop / put inventory verbs."""

from __future__ import annotations

import pytest
from conftest import build_scenario

from bunnyland.core import (
    CommandCost,
    ContainerComponent,
    ContainmentMode,
    Contains,
    IdentityComponent,
    Lane,
    PortableComponent,
    PutHandler,
    TakeHandler,
    build_submitted_command,
    container_of,
    contents,
    spawn_entity,
)

HOUR = 3600.0


def setup_inventory_scenario():
    scenario = build_scenario()
    actor = scenario.actor
    actor.register_handler(TakeHandler())
    actor.register_handler(PutHandler())
    return scenario


def place_item(scenario, room_id, *, portable=True, name="berry"):
    item = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name=name, kind="item"), PortableComponent(can_pick_up=portable)],
    )
    scenario.actor.world.get_entity(room_id).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), item.id
    )
    return item.id


def take_cmd(scenario, item_id):
    return build_submitted_command(
        character_id=str(scenario.character),
        controller_id=str(scenario.controller),
        controller_generation=scenario.generation,
        command_type="take",
        cost=CommandCost(action=1),
        lane=Lane.WORLD,
        payload={"item_id": str(item_id)},
    )


def put_cmd(scenario, item_id, target=None):
    payload = {"item_id": str(item_id)}
    if target is not None:
        payload["target_container_id"] = str(target)
    return build_submitted_command(
        character_id=str(scenario.character),
        controller_id=str(scenario.controller),
        controller_generation=scenario.generation,
        command_type="put",
        cost=CommandCost(action=1),
        lane=Lane.WORLD,
        payload=payload,
    )


async def test_take_moves_item_into_inventory():
    scenario = setup_inventory_scenario()
    item = place_item(scenario, scenario.room_a)

    await scenario.actor.submit(take_cmd(scenario, item))
    await scenario.actor.tick(HOUR)

    assert container_of(scenario.actor.world.get_entity(item)) == scenario.character
    assert item in contents(scenario.actor.world.get_entity(scenario.character))


async def test_take_unreachable_item_is_rejected():
    scenario = setup_inventory_scenario()
    item = place_item(scenario, scenario.room_b)  # different room

    await scenario.actor.submit(take_cmd(scenario, item))
    await scenario.actor.tick(HOUR)

    assert container_of(scenario.actor.world.get_entity(item)) == scenario.room_b


async def test_non_portable_item_cannot_be_taken():
    scenario = setup_inventory_scenario()
    item = place_item(scenario, scenario.room_a, portable=False)

    await scenario.actor.submit(take_cmd(scenario, item))
    await scenario.actor.tick(HOUR)

    assert container_of(scenario.actor.world.get_entity(item)) == scenario.room_a


async def test_drop_returns_item_to_room():
    scenario = setup_inventory_scenario()
    item = place_item(scenario, scenario.room_a)

    # take, then drop (put with no target)
    await scenario.actor.submit(take_cmd(scenario, item))
    await scenario.actor.tick(HOUR)
    assert container_of(scenario.actor.world.get_entity(item)) == scenario.character

    await scenario.actor.submit(put_cmd(scenario, item))
    await scenario.actor.tick(HOUR)
    assert container_of(scenario.actor.world.get_entity(item)) == scenario.room_a


async def test_put_into_container_in_room():
    scenario = setup_inventory_scenario()
    chest = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="oak chest", kind="container"), ContainerComponent(open=True)],
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), chest.id
    )
    item = place_item(scenario, scenario.room_a)

    await scenario.actor.submit(take_cmd(scenario, item))
    await scenario.actor.tick(HOUR)
    await scenario.actor.submit(put_cmd(scenario, item, target=chest.id))
    await scenario.actor.tick(HOUR)

    assert container_of(scenario.actor.world.get_entity(item)) == chest.id
    assert item in contents(chest)


async def test_put_into_closed_container_is_rejected():
    scenario = setup_inventory_scenario()
    chest = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="locked chest", kind="container"), ContainerComponent(open=False)],
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), chest.id
    )
    item = place_item(scenario, scenario.room_a)

    await scenario.actor.submit(take_cmd(scenario, item))
    await scenario.actor.tick(HOUR)
    await scenario.actor.submit(put_cmd(scenario, item, target=chest.id))
    await scenario.actor.tick(HOUR)

    # Put rejected -> item stays in inventory.
    assert container_of(scenario.actor.world.get_entity(item)) == scenario.character


async def test_cannot_put_item_not_in_inventory():
    scenario = setup_inventory_scenario()
    item = place_item(scenario, scenario.room_a)  # still on the floor

    await scenario.actor.submit(put_cmd(scenario, item))
    await scenario.actor.tick(HOUR)

    assert container_of(scenario.actor.world.get_entity(item)) == scenario.room_a
    # action not spent on rejected command
    from bunnyland.core import ActionPointsComponent

    char = scenario.actor.world.get_entity(scenario.character)
    assert char.get_component(ActionPointsComponent).current == pytest.approx(5.0)
