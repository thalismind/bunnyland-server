"""Tests for use (affordance dispatch) and write (physical writing)."""

from __future__ import annotations

from conftest import build_scenario

from bunnyland.core import (
    ButtonComponent,
    CommandCost,
    ContainmentMode,
    Contains,
    DoorComponent,
    IdentityComponent,
    KeyComponent,
    Lane,
    LockableComponent,
    ReadableComponent,
    UseHandler,
    WritableComponent,
    WriteHandler,
    build_submitted_command,
    spawn_entity,
)
from bunnyland.core.events import ItemUsedEvent, PhysicalWriteEvent
from bunnyland.core.handlers.base import HandlerContext

HOUR = 3600.0


def interaction_scenario():
    scenario = build_scenario()
    scenario.actor.register_handler(UseHandler())
    scenario.actor.register_handler(WriteHandler())
    return scenario


def in_room(scenario, components):
    entity = spawn_entity(scenario.actor.world, components)
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), entity.id
    )
    return entity


def in_inventory(scenario, components):
    entity = spawn_entity(scenario.actor.world, components)
    scenario.actor.world.get_entity(scenario.character).add_relationship(
        Contains(mode=ContainmentMode.INVENTORY), entity.id
    )
    return entity


def use(scenario, target_id, tool_id=None):
    payload = {"target_id": str(target_id)}
    if tool_id is not None:
        payload["tool_id"] = str(tool_id)
    return build_submitted_command(
        character_id=str(scenario.character),
        controller_id=str(scenario.controller),
        controller_generation=scenario.generation,
        command_type="use",
        cost=CommandCost(action=1),
        lane=Lane.WORLD,
        payload=payload,
    )


def write(scenario, target_id, text):
    return build_submitted_command(
        character_id=str(scenario.character),
        controller_id=str(scenario.controller),
        controller_generation=scenario.generation,
        command_type="write",
        cost=CommandCost(action=1, focus=1),
        lane=Lane.WORLD,
        payload={"target_id": str(target_id), "text": text},
    )


def handler_context(scenario):
    return HandlerContext(scenario.actor.world, scenario.actor.epoch)


def execute_use(scenario, target_id, tool_id=None, *, character_id=None):
    command = use(scenario, target_id, tool_id)
    if character_id is not None:
        command = build_submitted_command(
            character_id=character_id,
            controller_id=str(scenario.controller),
            controller_generation=scenario.generation,
            command_type="use",
            cost=CommandCost(action=1),
            lane=Lane.WORLD,
            payload=command.payload,
        )
    return UseHandler().execute(handler_context(scenario), command)


def execute_write(scenario, target_id, text, *, character_id=None):
    command = write(scenario, target_id, text)
    if character_id is not None:
        command = build_submitted_command(
            character_id=character_id,
            controller_id=str(scenario.controller),
            controller_generation=scenario.generation,
            command_type="write",
            cost=CommandCost(action=1, focus=1),
            lane=Lane.WORLD,
            payload=command.payload,
        )
    return WriteHandler().execute(handler_context(scenario), command)


def collect(actor, event_type):
    seen = []
    actor.bus.subscribe(event_type, seen.append)
    return seen


# -- use --------------------------------------------------------------------------------


async def test_use_opens_a_closed_door():
    scenario = interaction_scenario()
    door = in_room(
        scenario,
        [IdentityComponent(name="oak door", kind="door"), DoorComponent(open=False)],
    )
    used = collect(scenario.actor, ItemUsedEvent)

    await scenario.actor.submit(use(scenario, door.id))
    await scenario.actor.tick(HOUR)

    assert door.get_component(DoorComponent).open is True
    assert used[0].affordance == "door_opened"


async def test_use_locked_door_without_key_is_rejected():
    scenario = interaction_scenario()
    door = in_room(
        scenario,
        [
            IdentityComponent(name="vault door", kind="door"),
            DoorComponent(open=False),
            LockableComponent(locked=True, key_name="brass"),
        ],
    )

    await scenario.actor.submit(use(scenario, door.id))
    await scenario.actor.tick(HOUR)

    assert door.get_component(DoorComponent).open is False
    assert door.get_component(LockableComponent).locked is True


async def test_use_key_unlocks_then_door_opens():
    scenario = interaction_scenario()
    door = in_room(
        scenario,
        [
            IdentityComponent(name="vault door", kind="door"),
            DoorComponent(open=False),
            LockableComponent(locked=True, key_name="brass"),
        ],
    )
    key = in_inventory(
        scenario,
        [IdentityComponent(name="brass key", kind="key"), KeyComponent(key_name="brass")],
    )

    # First use with the key unlocks.
    await scenario.actor.submit(use(scenario, door.id, tool_id=key.id))
    await scenario.actor.tick(HOUR)
    assert door.get_component(LockableComponent).locked is False

    # Now an unlocked use opens it.
    await scenario.actor.submit(use(scenario, door.id))
    await scenario.actor.tick(HOUR)
    assert door.get_component(DoorComponent).open is True


async def test_use_button_presses_it():
    scenario = interaction_scenario()
    button = in_room(
        scenario,
        [IdentityComponent(name="red button", kind="button"), ButtonComponent()],
    )

    await scenario.actor.submit(use(scenario, button.id))
    await scenario.actor.tick(HOUR)

    assert button.get_component(ButtonComponent).pressed is True


def test_use_rejects_invalid_missing_and_unreachable_targets():
    scenario = interaction_scenario()
    target = in_room(scenario, [IdentityComponent(name="lever", kind="button"), ButtonComponent()])
    far = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="far lever", kind="button"), ButtonComponent()],
    )
    scenario.actor.world.get_entity(scenario.room_b).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT),
        far.id,
    )

    assert execute_use(scenario, target.id, character_id="not-an-id").reason == (
        "invalid character or target id"
    )
    assert execute_use(scenario, "entity_999").reason == "target does not exist"
    assert execute_use(scenario, far.id).reason == "target is not reachable"


def test_use_rejects_unreachable_tool_and_wrong_key():
    scenario = interaction_scenario()
    door = in_room(
        scenario,
        [
            IdentityComponent(name="vault door", kind="door"),
            LockableComponent(locked=True, key_name="brass"),
        ],
    )
    far_key = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="brass key", kind="key"), KeyComponent(key_name="brass")],
    )
    scenario.actor.world.get_entity(scenario.room_b).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT),
        far_key.id,
    )
    wrong_key = in_inventory(
        scenario,
        [IdentityComponent(name="iron key", kind="key"), KeyComponent(key_name="iron")],
    )

    assert execute_use(scenario, door.id, tool_id=far_key.id).reason == "tool is not reachable"
    assert execute_use(scenario, door.id, tool_id=wrong_key.id).reason == "it is locked"


def test_use_closes_open_door_rejects_inactive_button_and_plain_item():
    scenario = interaction_scenario()
    door = in_room(
        scenario,
        [IdentityComponent(name="open door", kind="door"), DoorComponent(open=True)],
    )
    inactive = in_room(
        scenario,
        [
            IdentityComponent(name="dead button", kind="button"),
            ButtonComponent(active=False),
        ],
    )
    rock = in_room(scenario, [IdentityComponent(name="rock", kind="item")])

    closed = execute_use(scenario, door.id)
    assert closed.ok is True
    assert closed.events[0].affordance == "door_closed"
    assert door.get_component(DoorComponent).open is False

    assert execute_use(scenario, inactive.id).reason == "nothing happens"
    assert execute_use(scenario, rock.id).reason == "you can't use that"


# -- write ------------------------------------------------------------------------------


async def test_write_appends_text_to_writable_object():
    scenario = interaction_scenario()
    paper = in_inventory(
        scenario,
        [IdentityComponent(name="paper", kind="item"), WritableComponent(), ReadableComponent()],
    )
    written = collect(scenario.actor, PhysicalWriteEvent)

    await scenario.actor.submit(write(scenario, paper.id, "The basin water is unsafe."))
    await scenario.actor.tick(HOUR)

    assert paper.get_component(ReadableComponent).text == "The basin water is unsafe."
    assert written[0].text == "The basin water is unsafe."


async def test_write_on_non_writable_is_rejected():
    scenario = interaction_scenario()
    rock = in_room(scenario, [IdentityComponent(name="rock", kind="item")])

    await scenario.actor.submit(write(scenario, rock.id, "hello"))
    await scenario.actor.tick(HOUR)

    assert not rock.has_component(ReadableComponent)


def test_write_rejects_invalid_empty_missing_unreachable_and_oversized_text():
    scenario = interaction_scenario()
    paper = in_inventory(
        scenario,
        [
            IdentityComponent(name="small paper", kind="item"),
            WritableComponent(remaining_space=4),
        ],
    )
    far_paper = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="far paper", kind="item"),
            WritableComponent(),
        ],
    )
    scenario.actor.world.get_entity(scenario.room_b).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT),
        far_paper.id,
    )

    assert execute_write(scenario, paper.id, "hi", character_id="not-an-id").reason == (
        "invalid character or target id"
    )
    assert execute_write(scenario, paper.id, "   ").reason == "nothing to write"
    assert execute_write(scenario, "entity_999", "hi").reason == "target does not exist"
    assert execute_write(scenario, far_paper.id, "hi").reason == "target is not reachable"
    assert execute_write(scenario, paper.id, "hello").reason == "not enough room to write that"


def test_write_appends_existing_text_and_updates_remaining_space():
    scenario = interaction_scenario()
    paper = in_inventory(
        scenario,
        [
            IdentityComponent(name="paper", kind="item"),
            WritableComponent(remaining_space=20),
            ReadableComponent(text="first line"),
        ],
    )

    result = execute_write(scenario, paper.id, "second")

    assert result.ok is True
    assert paper.get_component(ReadableComponent).text == "first line\nsecond"
    assert paper.get_component(WritableComponent).remaining_space == 14
