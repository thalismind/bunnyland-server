"""Tests for use (affordance dispatch) and write (physical writing)."""

from __future__ import annotations

from conftest import build_scenario

from bunnyland.core import (
    ButtonComponent,
    CloseHandler,
    CommandCost,
    ContainerComponent,
    ContainmentMode,
    Contains,
    DescriptionComponent,
    DoorClosedEvent,
    DoorComponent,
    DoorOpenedEvent,
    EntityInspectedEvent,
    IdentityComponent,
    InspectHandler,
    KeyComponent,
    Lane,
    LockableComponent,
    LockHandler,
    LookHandler,
    OpenHandler,
    ReadableComponent,
    RoomLookedEvent,
    UnlockHandler,
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
    scenario.actor.register_handler(LookHandler())
    scenario.actor.register_handler(InspectHandler())
    scenario.actor.register_handler(OpenHandler())
    scenario.actor.register_handler(CloseHandler())
    scenario.actor.register_handler(LockHandler())
    scenario.actor.register_handler(UnlockHandler())
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


def target_cmd(scenario, command_type, target_id, tool_id=None):
    payload = {"target_id": str(target_id)}
    if tool_id is not None:
        payload["tool_id"] = str(tool_id)
    return build_submitted_command(
        character_id=str(scenario.character),
        controller_id=str(scenario.controller),
        controller_generation=scenario.generation,
        command_type=command_type,
        cost=CommandCost(action=1),
        lane=Lane.WORLD,
        payload=payload,
    )


def command_with_payload(scenario, command_type, payload, *, character_id=None):
    return build_submitted_command(
        character_id=character_id or str(scenario.character),
        controller_id=str(scenario.controller),
        controller_generation=scenario.generation,
        command_type=command_type,
        cost=CommandCost(action=1),
        lane=Lane.WORLD,
        payload=payload,
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


# -- look / inspect ---------------------------------------------------------------------


async def test_look_and_inspect_emit_private_description_events():
    scenario = interaction_scenario()
    sign = in_room(
        scenario,
        [
            IdentityComponent(name="blank sign", kind="sign"),
            ReadableComponent(title="blank sign", text="Meet at dawn"),
        ],
    )
    looked = collect(scenario.actor, RoomLookedEvent)
    inspected = collect(scenario.actor, EntityInspectedEvent)

    await scenario.actor.submit(
        build_submitted_command(
            character_id=str(scenario.character),
            controller_id=str(scenario.controller),
            controller_generation=scenario.generation,
            command_type="look",
            cost=CommandCost(),
            lane=Lane.WORLD,
            payload={},
        )
    )
    await scenario.actor.tick(HOUR)
    await scenario.actor.submit(target_cmd(scenario, "inspect", sign.id))
    await scenario.actor.tick(HOUR)

    assert looked[0].summary.startswith("Mosslit Burrow")
    assert "blank sign" in looked[0].summary
    assert inspected[0].name == "blank sign"
    assert inspected[0].text == "Meet at dawn"


def test_inspect_rejects_unreachable_target_directly():
    scenario = interaction_scenario()
    far = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="far sign", kind="sign"), ReadableComponent(text="nope")],
    )
    scenario.actor.world.get_entity(scenario.room_b).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT),
        far.id,
    )

    result = InspectHandler().execute(
        handler_context(scenario),
        target_cmd(scenario, "inspect", far.id),
    )

    assert result.reason == "target is not reachable"


def test_look_rejects_invalid_character_and_missing_room_directly():
    scenario = interaction_scenario()

    invalid = command_with_payload(scenario, "look", {}, character_id="not-an-id")
    assert LookHandler().execute(handler_context(scenario), invalid).reason == (
        "invalid character id"
    )

    scenario.actor.world.get_entity(scenario.room_a).remove_relationship(
        Contains,
        scenario.character,
    )
    assert LookHandler().execute(
        handler_context(scenario),
        command_with_payload(scenario, "look", {}),
    ).reason == "character is not in a room"


def test_inspect_describes_rooms_nameless_entities_descriptions_and_locked_state():
    scenario = interaction_scenario()
    room_result = InspectHandler().execute(
        handler_context(scenario),
        target_cmd(scenario, "inspect", scenario.room_a),
    )
    assert room_result.ok is True
    assert room_result.events[0].name == "Mosslit Burrow"
    assert room_result.events[0].kind == "room"

    nameless = in_room(scenario, [])
    nameless_result = InspectHandler().execute(
        handler_context(scenario),
        target_cmd(scenario, "inspect", nameless.id),
    )
    assert nameless_result.events[0].name == str(nameless.id)

    note = in_room(
        scenario,
        [
            IdentityComponent(name="etched note", kind="item"),
            DescriptionComponent(short="short", long="long", appearance="appearance"),
        ],
    )
    note_result = InspectHandler().execute(
        handler_context(scenario),
        target_cmd(scenario, "inspect", note.id),
    )
    assert note_result.events[0].description == "long"

    locked = in_room(
        scenario,
        [
            IdentityComponent(name="locked box", kind="container"),
            ContainerComponent(open=False, locked=True),
        ],
    )
    locked_result = InspectHandler().execute(
        handler_context(scenario),
        target_cmd(scenario, "inspect", locked.id),
    )
    assert locked_result.events[0].state == "closed, locked"


def test_reachable_target_rejects_invalid_and_missing_target_directly():
    scenario = interaction_scenario()

    invalid = command_with_payload(scenario, "inspect", {"target_id": "not-an-id"})
    assert InspectHandler().execute(handler_context(scenario), invalid).reason == (
        "invalid character or target id"
    )

    missing = target_cmd(scenario, "inspect", "entity_999")
    assert InspectHandler().execute(handler_context(scenario), missing).reason == (
        "target does not exist"
    )


# -- explicit open / close / lock / unlock ---------------------------------------------


async def test_open_close_lock_and_unlock_update_components():
    scenario = interaction_scenario()
    chest = in_room(
        scenario,
        [IdentityComponent(name="oak chest", kind="container"), ContainerComponent(open=False)],
    )
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
    opened_doors = collect(scenario.actor, DoorOpenedEvent)
    closed_doors = collect(scenario.actor, DoorClosedEvent)

    await scenario.actor.submit(target_cmd(scenario, "open", chest.id))
    await scenario.actor.tick(HOUR)
    assert chest.get_component(ContainerComponent).open is True

    await scenario.actor.submit(target_cmd(scenario, "close", chest.id))
    await scenario.actor.tick(HOUR)
    assert chest.get_component(ContainerComponent).open is False

    await scenario.actor.submit(target_cmd(scenario, "unlock", door.id, tool_id=key.id))
    await scenario.actor.tick(HOUR)
    assert door.get_component(LockableComponent).locked is False

    await scenario.actor.submit(target_cmd(scenario, "open", door.id))
    await scenario.actor.tick(HOUR)
    assert door.get_component(DoorComponent).open is True
    assert opened_doors[0].target_id == str(door.id)

    await scenario.actor.submit(target_cmd(scenario, "close", door.id))
    await scenario.actor.tick(HOUR)
    assert door.get_component(DoorComponent).open is False
    assert closed_doors[0].target_id == str(door.id)

    await scenario.actor.submit(target_cmd(scenario, "lock", door.id, tool_id=key.id))
    await scenario.actor.tick(HOUR)
    assert door.get_component(LockableComponent).locked is True


def test_open_close_lock_unlock_reject_bad_state_directly():
    scenario = interaction_scenario()
    rock = in_room(scenario, [IdentityComponent(name="rock", kind="item")])
    open_box = in_room(
        scenario,
        [IdentityComponent(name="open box", kind="container"), ContainerComponent(open=True)],
    )
    closed_box = in_room(
        scenario,
        [IdentityComponent(name="closed box", kind="container"), ContainerComponent(open=False)],
    )
    open_door = in_room(
        scenario,
        [IdentityComponent(name="open door", kind="door"), DoorComponent(open=True)],
    )
    closed_door = in_room(
        scenario,
        [IdentityComponent(name="closed door", kind="door"), DoorComponent(open=False)],
    )
    locked = in_room(
        scenario,
        [
            IdentityComponent(name="locked box", kind="container"),
            ContainerComponent(open=False, locked=True),
        ],
    )
    keyed = in_room(
        scenario,
        [
            IdentityComponent(name="keyed door", kind="door"),
            DoorComponent(open=False),
            LockableComponent(locked=True, key_name="brass"),
        ],
    )

    assert (
        OpenHandler()
        .execute(handler_context(scenario), target_cmd(scenario, "open", open_box.id))
        .reason
        == "it is already open"
    )
    assert (
        OpenHandler()
        .execute(handler_context(scenario), target_cmd(scenario, "open", open_door.id))
        .reason
        == "it is already open"
    )
    assert (
        CloseHandler()
        .execute(handler_context(scenario), target_cmd(scenario, "close", closed_box.id))
        .reason
        == "it is already closed"
    )
    assert (
        CloseHandler()
        .execute(handler_context(scenario), target_cmd(scenario, "close", closed_door.id))
        .reason
        == "it is already closed"
    )
    assert (
        CloseHandler()
        .execute(handler_context(scenario), target_cmd(scenario, "close", rock.id))
        .reason
        == "target is not closeable"
    )
    assert (
        OpenHandler()
        .execute(handler_context(scenario), target_cmd(scenario, "open", rock.id))
        .reason
        == "target is not openable"
    )
    assert (
        OpenHandler()
        .execute(handler_context(scenario), target_cmd(scenario, "open", locked.id))
        .reason
        == "it is locked"
    )
    assert UnlockHandler().execute(
        handler_context(scenario),
        target_cmd(scenario, "unlock", keyed.id),
    ).reason == "matching key is required"
    assert (
        LockHandler()
        .execute(handler_context(scenario), target_cmd(scenario, "lock", rock.id))
        .reason
        == "target is not lockable"
    )


def test_lock_and_unlock_container_variants_directly():
    scenario = interaction_scenario()
    box = in_room(
        scenario,
        [IdentityComponent(name="lock box", kind="container"), ContainerComponent(locked=False)],
    )

    locked = LockHandler().execute(
        handler_context(scenario),
        target_cmd(scenario, "lock", box.id),
    )
    assert locked.ok is True
    assert box.get_component(ContainerComponent).locked is True

    assert LockHandler().execute(
        handler_context(scenario),
        target_cmd(scenario, "lock", box.id),
    ).reason == "it is already locked"

    unlocked = UnlockHandler().execute(
        handler_context(scenario),
        target_cmd(scenario, "unlock", box.id),
    )
    assert unlocked.ok is True
    assert box.get_component(ContainerComponent).locked is False

    assert UnlockHandler().execute(
        handler_context(scenario),
        target_cmd(scenario, "unlock", box.id),
    ).reason == "it is already unlocked"


def test_lock_and_unlock_key_variants_directly():
    scenario = interaction_scenario()
    door = in_room(
        scenario,
        [
            IdentityComponent(name="keyed door", kind="door"),
            DoorComponent(open=False),
            LockableComponent(locked=True, key_name="brass"),
        ],
    )
    wrong_key = in_inventory(
        scenario,
        [IdentityComponent(name="iron key", kind="key"), KeyComponent(key_name="iron")],
    )
    far_key = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="far key", kind="key"), KeyComponent(key_name="brass")],
    )
    scenario.actor.world.get_entity(scenario.room_b).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT),
        far_key.id,
    )
    latch = in_room(
        scenario,
        [
            IdentityComponent(name="simple latch", kind="door"),
            DoorComponent(open=False),
            LockableComponent(locked=True, key_name=None),
        ],
    )

    assert UnlockHandler().execute(
        handler_context(scenario),
        target_cmd(scenario, "unlock", door.id, tool_id=wrong_key.id),
    ).reason == "matching key is required"
    assert UnlockHandler().execute(
        handler_context(scenario),
        target_cmd(scenario, "unlock", door.id, tool_id=far_key.id),
    ).reason == "tool is not reachable"

    assert UnlockHandler().execute(
        handler_context(scenario),
        target_cmd(scenario, "unlock", latch.id),
    ).ok is True
    assert LockHandler().execute(
        handler_context(scenario),
        target_cmd(scenario, "lock", latch.id),
    ).ok is True


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
