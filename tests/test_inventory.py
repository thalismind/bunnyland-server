"""Tests for take / drop / put inventory verbs."""

from __future__ import annotations

import pytest
from conftest import build_scenario

from bunnyland.core import (
    CharacterComponent,
    CommandCost,
    ContainerComponent,
    ContainmentMode,
    Contains,
    DeadComponent,
    DropHandler,
    HoldableComponent,
    HoldHandler,
    Holding,
    IdentityComponent,
    InventoryComponent,
    Lane,
    PortableComponent,
    PutHandler,
    RemoveHandler,
    TakeHandler,
    UnholdHandler,
    WearableComponent,
    WearHandler,
    Wearing,
    build_submitted_command,
    container_of,
    contents,
    spawn_entity,
)
from bunnyland.core.handlers.base import HandlerContext

HOUR = 3600.0


def setup_inventory_scenario():
    scenario = build_scenario()
    actor = scenario.actor
    actor.register_handler(TakeHandler())
    actor.register_handler(DropHandler())
    actor.register_handler(PutHandler())
    actor.register_handler(HoldHandler())
    actor.register_handler(UnholdHandler())
    actor.register_handler(WearHandler())
    actor.register_handler(RemoveHandler())
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


def item_cmd(scenario, command_type, item_id):
    return build_submitted_command(
        character_id=str(scenario.character),
        controller_id=str(scenario.controller),
        controller_generation=scenario.generation,
        command_type=command_type,
        cost=CommandCost(action=1),
        lane=Lane.WORLD,
        payload={"item_id": str(item_id)},
    )


def handler_context(scenario):
    return HandlerContext(scenario.actor.world, scenario.actor.epoch)


def execute_take(scenario, item_id, *, character_id=None):
    command = take_cmd(scenario, item_id)
    if character_id is not None:
        command = build_submitted_command(
            character_id=character_id,
            controller_id=str(scenario.controller),
            controller_generation=scenario.generation,
            command_type="take",
            cost=CommandCost(action=1),
            lane=Lane.WORLD,
            payload={"item_id": str(item_id)},
        )
    return TakeHandler().execute(handler_context(scenario), command)


def execute_put(scenario, item_id, target=None, *, character_id=None, raw_payload=None):
    command = put_cmd(scenario, item_id, target)
    if character_id is not None or raw_payload is not None:
        command = build_submitted_command(
            character_id=character_id or str(scenario.character),
            controller_id=str(scenario.controller),
            controller_generation=scenario.generation,
            command_type="put",
            cost=CommandCost(action=1),
            lane=Lane.WORLD,
            payload=raw_payload if raw_payload is not None else command.payload,
        )
    return PutHandler().execute(handler_context(scenario), command)


def execute_item_handler(handler, scenario, item_id):
    return handler.execute(
        handler_context(scenario),
        item_cmd(scenario, handler.command_type, item_id),
    )


def execute_drop(scenario, item_id, *, character_id=None):
    command = build_submitted_command(
        character_id=character_id or str(scenario.character),
        controller_id=str(scenario.controller),
        controller_generation=scenario.generation,
        command_type="drop",
        cost=CommandCost(action=1),
        lane=Lane.WORLD,
        payload={"item_id": str(item_id)},
    )
    return DropHandler().execute(handler_context(scenario), command)


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


async def test_take_rejects_item_held_by_living_character():
    scenario = setup_inventory_scenario()
    other = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="Hazel", kind="character"), CharacterComponent()],
    )
    item = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="berry", kind="item"), PortableComponent()],
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), other.id
    )
    other.add_relationship(Contains(mode=ContainmentMode.INVENTORY), item.id)

    result = execute_take(scenario, item.id)

    assert result.reason == "item is not reachable"
    assert container_of(scenario.actor.world.get_entity(item.id)) == other.id


async def test_take_allows_item_from_dead_character():
    scenario = setup_inventory_scenario()
    other = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="Hazel", kind="character"),
            CharacterComponent(),
            DeadComponent(died_at_epoch=0, cause="test"),
        ],
    )
    item = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="berry", kind="item"), PortableComponent()],
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), other.id
    )
    other.add_relationship(Contains(mode=ContainmentMode.INVENTORY), item.id)

    result = execute_take(scenario, item.id)

    assert result.ok is True
    assert container_of(scenario.actor.world.get_entity(item.id)) == scenario.character


async def test_non_portable_item_cannot_be_taken():
    scenario = setup_inventory_scenario()
    item = place_item(scenario, scenario.room_a, portable=False)

    await scenario.actor.submit(take_cmd(scenario, item))
    await scenario.actor.tick(HOUR)

    assert container_of(scenario.actor.world.get_entity(item)) == scenario.room_a


async def test_drop_returns_item_to_room():
    scenario = setup_inventory_scenario()
    item = place_item(scenario, scenario.room_a)

    # take, then drop
    await scenario.actor.submit(take_cmd(scenario, item))
    await scenario.actor.tick(HOUR)
    assert container_of(scenario.actor.world.get_entity(item)) == scenario.character

    await scenario.actor.submit(item_cmd(scenario, "drop", item))
    await scenario.actor.tick(HOUR)
    assert container_of(scenario.actor.world.get_entity(item)) == scenario.room_a


async def test_hold_unhold_wear_and_remove_inventory_overlays():
    scenario = setup_inventory_scenario()
    tool = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="garden hoe", kind="tool"),
            PortableComponent(),
            HoldableComponent(slot="hand"),
        ],
    )
    hat = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="straw hat", kind="clothing"),
            PortableComponent(),
            WearableComponent(slot="head"),
        ],
    )
    character = scenario.actor.world.get_entity(scenario.character)
    character.add_relationship(Contains(mode=ContainmentMode.INVENTORY), tool.id)
    character.add_relationship(Contains(mode=ContainmentMode.INVENTORY), hat.id)

    await scenario.actor.submit(item_cmd(scenario, "hold", tool.id))
    await scenario.actor.tick(HOUR)
    await scenario.actor.submit(item_cmd(scenario, "wear", hat.id))
    await scenario.actor.tick(HOUR)
    assert character.has_relationship(Holding, tool.id)
    assert character.has_relationship(Wearing, hat.id)

    await scenario.actor.submit(item_cmd(scenario, "unhold", tool.id))
    await scenario.actor.tick(HOUR)
    await scenario.actor.submit(item_cmd(scenario, "remove", hat.id))
    await scenario.actor.tick(HOUR)
    assert not character.has_relationship(Holding, tool.id)
    assert not character.has_relationship(Wearing, hat.id)


def test_equipment_handlers_reject_bad_state_directly():
    scenario = setup_inventory_scenario()
    plain = place_item(scenario, scenario.room_a, name="plain rock")
    character = scenario.actor.world.get_entity(scenario.character)
    room = scenario.actor.world.get_entity(scenario.room_a)
    room.remove_relationship(Contains, plain)
    character.add_relationship(Contains(mode=ContainmentMode.INVENTORY), plain)

    assert execute_item_handler(HoldHandler(), scenario, plain).reason == "item cannot be held"
    assert execute_item_handler(WearHandler(), scenario, plain).reason == "item cannot be worn"
    assert execute_item_handler(UnholdHandler(), scenario, plain).reason == "item is not held"
    assert execute_item_handler(RemoveHandler(), scenario, plain).reason == "item is not worn"


def test_equipment_handlers_reject_invalid_missing_and_unheld_items_directly():
    scenario = setup_inventory_scenario()
    item = place_item(scenario, scenario.room_a, name="floor tool")

    invalid = build_submitted_command(
        character_id="not-an-id",
        controller_id=str(scenario.controller),
        controller_generation=scenario.generation,
        command_type="hold",
        cost=CommandCost(action=1),
        lane=Lane.WORLD,
        payload={"item_id": str(item)},
    )
    assert HoldHandler().execute(handler_context(scenario), invalid).reason == (
        "invalid character or item id"
    )
    missing_character = build_submitted_command(
        character_id="entity_999",
        controller_id=str(scenario.controller),
        controller_generation=scenario.generation,
        command_type="hold",
        cost=CommandCost(action=1),
        lane=Lane.WORLD,
        payload={"item_id": str(item)},
    )
    assert HoldHandler().execute(handler_context(scenario), missing_character).reason == (
        "character does not exist"
    )
    assert execute_item_handler(HoldHandler(), scenario, "entity_999").reason == (
        "item does not exist"
    )
    assert execute_item_handler(HoldHandler(), scenario, item).reason == (
        "item is not in inventory"
    )
    assert execute_item_handler(UnholdHandler(), scenario, item).reason == (
        "item is not in inventory"
    )
    assert execute_item_handler(WearHandler(), scenario, item).reason == (
        "item is not in inventory"
    )
    assert execute_item_handler(RemoveHandler(), scenario, item).reason == (
        "item is not in inventory"
    )


def test_equipment_handlers_reject_duplicate_hold_and_wear_directly():
    scenario = setup_inventory_scenario()
    tool = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="garden hoe", kind="tool"),
            PortableComponent(),
            HoldableComponent(slot="hand"),
        ],
    )
    hat = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="straw hat", kind="clothing"),
            PortableComponent(),
            WearableComponent(slot="head"),
        ],
    )
    character = scenario.actor.world.get_entity(scenario.character)
    character.add_relationship(Contains(mode=ContainmentMode.INVENTORY), tool.id)
    character.add_relationship(Contains(mode=ContainmentMode.INVENTORY), hat.id)

    assert execute_item_handler(HoldHandler(), scenario, tool.id).ok is True
    assert execute_item_handler(HoldHandler(), scenario, tool.id).reason == (
        "already holding item"
    )
    assert execute_item_handler(WearHandler(), scenario, hat.id).ok is True
    assert execute_item_handler(WearHandler(), scenario, hat.id).reason == (
        "already wearing item"
    )


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


def test_take_rejects_item_with_no_container():
    scenario = setup_inventory_scenario()
    item = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="loose pebble", kind="item"), PortableComponent()],
    )

    assert execute_take(scenario, item.id).reason == "item is nowhere"


def test_take_rejects_room_item_when_character_has_no_room():
    scenario = setup_inventory_scenario()
    item = place_item(scenario, scenario.room_a)
    scenario.actor.world.get_entity(scenario.room_a).remove_relationship(
        Contains,
        scenario.character,
    )

    assert execute_take(scenario, item).reason == "item is not reachable"


def test_take_rejects_invalid_and_missing_item_ids():
    scenario = setup_inventory_scenario()
    item = place_item(scenario, scenario.room_a)

    assert execute_take(scenario, item, character_id="not-an-id").reason == (
        "invalid character or item id"
    )
    assert execute_take(scenario, item, character_id="entity_999").reason == (
        "character does not exist"
    )
    assert execute_take(scenario, "entity_999").reason == "item does not exist"


def test_take_rejects_item_already_in_inventory():
    scenario = setup_inventory_scenario()
    item = place_item(scenario, scenario.room_a)
    scenario.actor.world.get_entity(scenario.room_a).remove_relationship(Contains, item)
    scenario.actor.world.get_entity(scenario.character).add_relationship(
        Contains(mode=ContainmentMode.INVENTORY),
        item,
    )

    assert execute_take(scenario, item).reason == "already holding item"


def test_take_rejects_closed_or_non_removable_source_container():
    scenario = setup_inventory_scenario()
    world = scenario.actor.world
    chest = spawn_entity(
        world,
        [
            IdentityComponent(name="sealed chest", kind="container"),
            ContainerComponent(open=True, allow_remove=False),
        ],
    )
    world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT),
        chest.id,
    )
    item = spawn_entity(
        world,
        [IdentityComponent(name="coin", kind="item"), PortableComponent()],
    )
    chest.add_relationship(Contains(mode=ContainmentMode.CONTAINER), item.id)

    assert execute_take(scenario, item.id).reason == "container does not allow removal"

    chest.remove_component(ContainerComponent)
    chest.add_component(ContainerComponent(open=False))

    assert execute_take(scenario, item.id).reason == "container is closed"


def test_take_rejects_full_inventory():
    scenario = setup_inventory_scenario()
    character = scenario.actor.world.get_entity(scenario.character)
    character.add_component(InventoryComponent(max_slots=1))
    carried = place_item(scenario, scenario.room_a, name="carried")
    target = place_item(scenario, scenario.room_a, name="target")
    scenario.actor.world.get_entity(scenario.room_a).remove_relationship(Contains, carried)
    character.add_relationship(Contains(mode=ContainmentMode.INVENTORY), carried)

    assert execute_take(scenario, target).reason == "inventory is full"


def test_take_allows_inventory_with_available_slots():
    scenario = setup_inventory_scenario()
    character = scenario.actor.world.get_entity(scenario.character)
    character.add_component(InventoryComponent(max_slots=2))
    carried = place_item(scenario, scenario.room_a, name="carried")
    target = place_item(scenario, scenario.room_a, name="target")
    scenario.actor.world.get_entity(scenario.room_a).remove_relationship(Contains, carried)
    character.add_relationship(Contains(mode=ContainmentMode.INVENTORY), carried)

    assert execute_take(scenario, target).ok is True
    assert container_of(scenario.actor.world.get_entity(target)) == scenario.character


def test_put_rejects_invalid_and_missing_item_ids():
    scenario = setup_inventory_scenario()
    item = place_item(scenario, scenario.room_a)

    assert execute_put(scenario, item, character_id="not-an-id").reason == (
        "invalid character or item id"
    )
    assert execute_put(scenario, item, character_id="entity_999").reason == (
        "character does not exist"
    )
    assert execute_put(scenario, "entity_999").reason == "item does not exist"


def test_put_drop_rejects_when_character_has_no_room():
    scenario = setup_inventory_scenario()
    item = place_item(scenario, scenario.room_a)
    room = scenario.actor.world.get_entity(scenario.room_a)
    character = scenario.actor.world.get_entity(scenario.character)
    room.remove_relationship(Contains, scenario.character)
    room.remove_relationship(Contains, item)
    character.add_relationship(Contains(mode=ContainmentMode.INVENTORY), item)

    assert execute_put(scenario, item).reason == "character is not in a room"


def test_drop_rejects_invalid_missing_unheld_and_roomless_items():
    scenario = setup_inventory_scenario()
    item = place_item(scenario, scenario.room_a)

    assert execute_drop(scenario, item, character_id="not-an-id").reason == (
        "invalid character or item id"
    )
    assert execute_drop(scenario, "entity_999").reason == "item does not exist"
    assert execute_drop(scenario, item).reason == "item is not in inventory"

    character = scenario.actor.world.get_entity(scenario.character)
    scenario.actor.world.get_entity(scenario.room_a).remove_relationship(Contains, item)
    scenario.actor.world.get_entity(scenario.room_a).remove_relationship(
        Contains,
        scenario.character,
    )
    character.add_relationship(Contains(mode=ContainmentMode.INVENTORY), item)
    assert execute_drop(scenario, item).reason == "character is not in a room"


def test_put_rejects_unreachable_self_and_non_container_targets():
    scenario = setup_inventory_scenario()
    item = place_item(scenario, scenario.room_a)
    target = place_item(scenario, scenario.room_a, name="flat rock")
    room = scenario.actor.world.get_entity(scenario.room_a)
    character = scenario.actor.world.get_entity(scenario.character)
    room.remove_relationship(Contains, item)
    character.add_relationship(Contains(mode=ContainmentMode.INVENTORY), item)

    assert execute_put(scenario, item, target=item).reason == "target is not reachable"
    assert execute_put(scenario, item, target=target).reason == "target is not a container"


def test_put_rejects_container_add_constraints():
    scenario = setup_inventory_scenario()
    world = scenario.actor.world
    item = place_item(scenario, scenario.room_a)
    filler = place_item(scenario, scenario.room_a, name="filler")
    room = world.get_entity(scenario.room_a)
    character = world.get_entity(scenario.character)
    room.remove_relationship(Contains, item)
    character.add_relationship(Contains(mode=ContainmentMode.INVENTORY), item)
    chest = spawn_entity(
        world,
        [
            IdentityComponent(name="full chest", kind="container"),
            ContainerComponent(open=True, allow_add=False),
        ],
    )
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), chest.id)

    assert execute_put(scenario, item, target=chest.id).reason == "container does not allow adding"

    chest.remove_component(ContainerComponent)
    chest.add_component(ContainerComponent(open=True, max_slots=1))
    room.remove_relationship(Contains, filler)
    chest.add_relationship(Contains(mode=ContainmentMode.CONTAINER), filler)

    assert execute_put(scenario, item, target=chest.id).reason == "container is full"


def test_put_removes_holding_and_wearing_overlays_when_relocating_item():
    scenario = setup_inventory_scenario()
    item = place_item(scenario, scenario.room_a)
    room = scenario.actor.world.get_entity(scenario.room_a)
    character = scenario.actor.world.get_entity(scenario.character)
    room.remove_relationship(Contains, item)
    character.add_relationship(Contains(mode=ContainmentMode.INVENTORY), item)
    character.add_relationship(Holding(), item)
    character.add_relationship(Wearing(), item)

    result = execute_put(scenario, item)

    assert result.ok is True
    assert not character.has_relationship(Holding, item)
    assert not character.has_relationship(Wearing, item)
