"""Tests for toon-sim sprite backfill (positions, images, draw layers)."""

from __future__ import annotations

from conftest import build_scenario

from bunnyland.core import (
    ActionPointsComponent,
    CommandCost,
    ContainerComponent,
    ContainmentMode,
    Contains,
    DoorComponent,
    IdentityComponent,
    Lane,
    PortableComponent,
    build_submitted_command,
    container_of,
    spawn_entity,
)
from bunnyland.core.handlers import HandlerContext
from bunnyland.mechanics.toonsim import (
    LAYER_BACKGROUND,
    LAYER_CHARACTER,
    LAYER_FURNITURE,
    LAYER_ITEM,
    MoveSpriteHandler,
    PlacedOn,
    SpriteBackfillConsequence,
    SpriteBounds,
    SpriteImage,
    SpriteLayer,
    SpriteMovedEvent,
    SpritePosition,
    SpriteScale,
    ToonRoomComponent,
    default_layer_for,
    install_toonsim,
)
from bunnyland.plugins import apply_plugins
from bunnyland.plugins.builtin import toonsim_plugin
from bunnyland.worldgen import ObjectSpec, RoomSpec, WorldProposal, instantiate


def _backfill(world) -> None:
    SpriteBackfillConsequence().process(world, epoch=0)


def test_backfills_layers_by_category():
    scenario = build_scenario()
    world = scenario.actor.world

    chair = spawn_entity(
        world, [IdentityComponent(name="a red chair", kind="chair")]
    )
    chest = spawn_entity(
        world,
        [IdentityComponent(name="an oak chest", kind="container"), ContainerComponent()],
    )
    apple = spawn_entity(
        world,
        [IdentityComponent(name="an apple", kind="food"), PortableComponent()],
    )
    door = spawn_entity(
        world, [IdentityComponent(name="a door", kind="door"), DoorComponent()]
    )

    _backfill(world)

    assert world.get_entity(scenario.room_a).get_component(SpriteLayer).layer == LAYER_BACKGROUND
    assert world.get_entity(scenario.character).get_component(SpriteLayer).layer == LAYER_CHARACTER
    assert chair.get_component(SpriteLayer).layer == LAYER_FURNITURE
    assert chest.get_component(SpriteLayer).layer == LAYER_FURNITURE
    assert apple.get_component(SpriteLayer).layer == LAYER_ITEM
    assert door.get_component(SpriteLayer).layer == LAYER_ITEM


def test_backfill_attaches_position_and_image():
    scenario = build_scenario()
    world = scenario.actor.world

    _backfill(world)

    room = world.get_entity(scenario.room_a)
    assert room.has_component(SpritePosition)
    assert room.has_component(SpriteImage)
    assert room.has_component(SpriteScale)
    assert room.get_component(SpritePosition).x == 0.0
    assert room.get_component(SpriteImage).url == ""
    assert room.get_component(SpriteScale).scale == 1.0


def test_skips_non_renderable_entities():
    scenario = build_scenario()
    world = scenario.actor.world

    faction = spawn_entity(world, [IdentityComponent(name="The Warren", kind="faction")])

    _backfill(world)

    assert not faction.has_component(SpriteLayer)
    assert not faction.has_component(SpritePosition)
    assert not faction.has_component(SpriteImage)
    assert not faction.has_component(SpriteScale)
    assert default_layer_for(faction) is None


def test_does_not_overwrite_explicit_values():
    scenario = build_scenario()
    world = scenario.actor.world

    item = spawn_entity(
        world,
        [
            IdentityComponent(name="a painted egg", kind="art"),
            PortableComponent(),
            SpritePosition(x=3.5, y=-2.0),
            SpriteImage(url="https://cdn/egg.png"),
            SpriteLayer(layer=99),
            SpriteScale(scale=2.5),
        ],
    )

    _backfill(world)

    # The pre-set layer wins; the entity already had SpriteLayer so it is never touched.
    assert item.get_component(SpriteLayer).layer == 99
    assert item.get_component(SpritePosition).x == 3.5
    assert item.get_component(SpriteImage).url == "https://cdn/egg.png"
    assert item.get_component(SpriteScale).scale == 2.5


def test_backfill_preserves_existing_sprite_parts_when_adding_layer():
    scenario = build_scenario()
    world = scenario.actor.world

    item = spawn_entity(
        world,
        [
            IdentityComponent(name="a painted egg", kind="food"),
            PortableComponent(),
            SpritePosition(x=3.5, y=-2.0),
            SpriteImage(url="https://cdn/egg.png"),
            SpriteScale(scale=2.5),
        ],
    )

    _backfill(world)

    assert item.get_component(SpriteLayer).layer == LAYER_ITEM
    assert item.get_component(SpritePosition).x == 3.5
    assert item.get_component(SpritePosition).y == -2.0
    assert item.get_component(SpriteImage).url == "https://cdn/egg.png"
    assert item.get_component(SpriteScale).scale == 2.5


def test_backfill_is_idempotent():
    scenario = build_scenario()
    world = scenario.actor.world

    _backfill(world)
    room = world.get_entity(scenario.room_a)
    first = room.get_component(SpriteLayer).layer

    _backfill(world)
    assert room.get_component(SpriteLayer).layer == first


async def test_install_registers_consequence_and_runs_on_tick():
    scenario = build_scenario()
    install_toonsim(scenario.actor)

    await scenario.actor.tick(0.0)

    room = scenario.actor.world.get_entity(scenario.room_a)
    assert room.get_component(SpriteLayer).layer == LAYER_BACKGROUND


async def test_worldgen_hook_places_items_on_table_without_changing_containment():
    scenario = build_scenario()
    actor = scenario.actor
    apply_plugins([toonsim_plugin()], actor)
    proposal = WorldProposal(
        seed="toon table",
        rooms=[RoomSpec(key="room", title="Breakfast Nook")],
        objects=[
            ObjectSpec(
                key="table",
                room_key="room",
                name="oak table",
                kind="table",
                portable=False,
            ),
            ObjectSpec(key="apple", room_key="room", name="red apple", kind="food"),
        ],
    )

    result = await instantiate(actor, proposal)

    room = actor.world.get_entity(result.rooms["room"])
    table = actor.world.get_entity(result.objects["table"])
    apple = actor.world.get_entity(result.objects["apple"])
    assert room.has_component(ToonRoomComponent)
    assert room.has_component(SpriteBounds)
    assert table.get_component(SpriteLayer).layer == LAYER_FURNITURE
    assert apple.get_component(SpriteLayer).layer == LAYER_ITEM
    assert container_of(table) == room.id
    assert container_of(apple) == room.id
    assert room.has_relationship(Contains, table.id)
    assert room.has_relationship(Contains, apple.id)
    assert apple.has_relationship(PlacedOn, table.id)

    table_pos = table.get_component(SpritePosition)
    table_bounds = table.get_component(SpriteBounds)
    apple_pos = apple.get_component(SpritePosition)
    assert abs(apple_pos.x - table_pos.x) <= table_bounds.width / 2.0
    assert abs(apple_pos.y - table_pos.y) <= table_bounds.height / 2.0


def _move_sprite(scenario, **payload):
    return build_submitted_command(
        character_id=str(scenario.character),
        controller_id=str(scenario.controller),
        controller_generation=scenario.generation,
        command_type="move-sprite",
        cost=CommandCost(),  # in-room movement is free
        lane=Lane.WORLD,
        payload=payload,
    )


async def test_move_sprite_repositions_for_free():
    scenario = build_scenario(action_current=5.0)
    scenario.actor.register_handler(MoveSpriteHandler())
    moved: list[SpriteMovedEvent] = []
    scenario.actor.bus.subscribe(SpriteMovedEvent, moved.append)

    await scenario.actor.submit(_move_sprite(scenario, x=20.0, y=20.0))
    await scenario.actor.tick(0.0)

    character = scenario.actor.world.get_entity(scenario.character)
    pos = character.get_component(SpritePosition)
    assert (pos.x, pos.y) == (20.0, 20.0)
    # No action points were spent on the free in-room move.
    assert character.get_component(ActionPointsComponent).current == 5.0
    assert moved and (moved[-1].x, moved[-1].y) == (20.0, 20.0)
    assert moved[-1].room_id == str(scenario.room_a)


def test_move_sprite_rejects_out_of_room_bounds():
    scenario = build_scenario()
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)

    result = MoveSpriteHandler().execute(ctx, _move_sprite(scenario, x=1.0, y=1.0))

    character = scenario.actor.world.get_entity(scenario.character)
    assert result.reason == "position is outside room bounds"
    assert not character.has_component(SpritePosition)


def test_move_sprite_rejects_solid_collision():
    scenario = build_scenario()
    world = scenario.actor.world
    blocker = spawn_entity(
        world,
        [
            IdentityComponent(name="oak table", kind="table"),
            SpritePosition(x=40.0, y=40.0),
            SpriteBounds(width=12.0, height=12.0, solid=True),
        ],
    )
    world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), blocker.id
    )
    ctx = HandlerContext(world, scenario.actor.epoch)

    result = MoveSpriteHandler().execute(ctx, _move_sprite(scenario, x=40.0, y=40.0))

    character = world.get_entity(scenario.character)
    assert result.reason == "position is blocked"
    assert not character.has_component(SpritePosition)


async def test_move_sprite_rejects_bad_payload():
    scenario = build_scenario()
    scenario.actor.register_handler(MoveSpriteHandler())

    await scenario.actor.submit(_move_sprite(scenario, x="left"))
    await scenario.actor.tick(0.0)

    character = scenario.actor.world.get_entity(scenario.character)
    assert not character.has_component(SpritePosition)


def test_move_sprite_rejects_invalid_character_id():
    scenario = build_scenario()
    command = build_submitted_command(
        character_id="not-an-entity-id",
        controller_id=str(scenario.controller),
        controller_generation=scenario.generation,
        command_type="move-sprite",
        cost=CommandCost(),
        lane=Lane.WORLD,
        payload={"x": 1, "y": 2},
    )
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)

    result = MoveSpriteHandler().execute(ctx, command)

    assert result.reason == "invalid character id"
