"""Tests for toon-sim sprite backfill (positions, images, draw layers)."""

from __future__ import annotations

from types import SimpleNamespace

from conftest import build_scenario

from bunnyland.core import (
    ActionPointsComponent,
    CharacterComponent,
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
from bunnyland.plugins import apply_plugins
from bunnyland.simpacks.toonsim import mechanics as toonsim
from bunnyland.simpacks.toonsim.mechanics import (
    LAYER_BACKGROUND,
    LAYER_CHARACTER,
    LAYER_FURNITURE,
    LAYER_ITEM,
    MoveSpriteHandler,
    PlacedOn,
    SpriteBackfillConsequence,
    SpriteBoundsComponent,
    SpriteImageComponent,
    SpriteLayerComponent,
    SpriteMovedEvent,
    SpritePositionComponent,
    SpriteScaleComponent,
    ToonRoomComponent,
    default_layer_for,
    install_toonsim,
)
from bunnyland.simpacks.toonsim.plugin import plugin as toonsim_plugin
from bunnyland.worldgen import ObjectSpec, RoomSpec, WorldProposal, instantiate


def _backfill(world) -> None:
    SpriteBackfillConsequence().process(world, epoch=0)


def test_backfills_layers_by_category():
    scenario = build_scenario()
    world = scenario.actor.world

    chair = spawn_entity(world, [IdentityComponent(name="a red chair", kind="chair")])
    chest = spawn_entity(
        world,
        [IdentityComponent(name="an oak chest", kind="container"), ContainerComponent()],
    )
    apple = spawn_entity(
        world,
        [IdentityComponent(name="an apple", kind="food"), PortableComponent()],
    )
    door = spawn_entity(world, [IdentityComponent(name="a door", kind="door"), DoorComponent()])

    _backfill(world)

    assert (
        world.get_entity(scenario.room_a).get_component(SpriteLayerComponent).layer
        == LAYER_BACKGROUND
    )
    assert (
        world.get_entity(scenario.character).get_component(SpriteLayerComponent).layer
        == LAYER_CHARACTER
    )
    assert chair.get_component(SpriteLayerComponent).layer == LAYER_FURNITURE
    assert chest.get_component(SpriteLayerComponent).layer == LAYER_FURNITURE
    assert apple.get_component(SpriteLayerComponent).layer == LAYER_ITEM
    assert door.get_component(SpriteLayerComponent).layer == LAYER_ITEM


def test_backfill_attaches_position_and_image():
    scenario = build_scenario()
    world = scenario.actor.world

    _backfill(world)

    room = world.get_entity(scenario.room_a)
    assert room.has_component(SpritePositionComponent)
    assert room.has_component(SpriteImageComponent)
    assert room.has_component(SpriteScaleComponent)
    assert room.get_component(SpritePositionComponent).x == 0.0
    assert room.get_component(SpriteImageComponent).url == ""
    assert room.get_component(SpriteScaleComponent).scale == 1.0


def test_skips_non_renderable_entities():
    scenario = build_scenario()
    world = scenario.actor.world

    faction = spawn_entity(world, [IdentityComponent(name="The Warren", kind="faction")])

    _backfill(world)

    assert not faction.has_component(SpriteLayerComponent)
    assert not faction.has_component(SpritePositionComponent)
    assert not faction.has_component(SpriteImageComponent)
    assert not faction.has_component(SpriteScaleComponent)
    assert default_layer_for(faction) is None


def test_does_not_overwrite_explicit_values():
    scenario = build_scenario()
    world = scenario.actor.world

    item = spawn_entity(
        world,
        [
            IdentityComponent(name="a painted egg", kind="art"),
            PortableComponent(),
            SpritePositionComponent(x=3.5, y=-2.0),
            SpriteImageComponent(url="https://cdn/egg.png"),
            SpriteLayerComponent(layer=99),
            SpriteScaleComponent(scale=2.5),
        ],
    )

    _backfill(world)

    # The pre-set layer wins; the entity already had SpriteLayerComponent so it is never touched.
    assert item.get_component(SpriteLayerComponent).layer == 99
    assert item.get_component(SpritePositionComponent).x == 3.5
    assert item.get_component(SpriteImageComponent).url == "https://cdn/egg.png"
    assert item.get_component(SpriteScaleComponent).scale == 2.5


def test_backfill_preserves_existing_sprite_parts_when_adding_layer():
    scenario = build_scenario()
    world = scenario.actor.world

    item = spawn_entity(
        world,
        [
            IdentityComponent(name="a painted egg", kind="food"),
            PortableComponent(),
            SpritePositionComponent(x=3.5, y=-2.0),
            SpriteImageComponent(url="https://cdn/egg.png"),
            SpriteScaleComponent(scale=2.5),
        ],
    )

    _backfill(world)

    assert item.get_component(SpriteLayerComponent).layer == LAYER_ITEM
    assert item.get_component(SpritePositionComponent).x == 3.5
    assert item.get_component(SpritePositionComponent).y == -2.0
    assert item.get_component(SpriteImageComponent).url == "https://cdn/egg.png"
    assert item.get_component(SpriteScaleComponent).scale == 2.5


def test_backfill_preserves_existing_bounds_when_adding_layer():
    scenario = build_scenario()
    world = scenario.actor.world

    item = spawn_entity(
        world,
        [
            IdentityComponent(name="a crate", kind="container"),
            ContainerComponent(),
            SpriteBoundsComponent(width=33.0, height=11.0, solid=True),
        ],
    )

    _backfill(world)

    assert item.get_component(SpriteLayerComponent).layer == LAYER_FURNITURE
    assert item.get_component(SpriteBoundsComponent).width == 33.0


def test_default_bounds_cover_renderable_categories_and_unnamed_kind():
    scenario = build_scenario()
    world = scenario.actor.world

    door = spawn_entity(world, [DoorComponent()])
    loose = spawn_entity(world, [PortableComponent()])
    unnamed = spawn_entity(world, [])

    assert toonsim._kind(unnamed) == ""
    assert toonsim.default_bounds_for(door).width == 10.0
    assert toonsim.default_bounds_for(loose).width == 4.0
    assert toonsim.default_bounds_for(unnamed) is None


def test_backfill_is_idempotent():
    scenario = build_scenario()
    world = scenario.actor.world

    _backfill(world)
    room = world.get_entity(scenario.room_a)
    first = room.get_component(SpriteLayerComponent).layer

    _backfill(world)
    assert room.get_component(SpriteLayerComponent).layer == first


async def test_install_registers_consequence_and_runs_on_tick():
    scenario = build_scenario()
    install_toonsim(scenario.actor)

    await scenario.actor.tick(0.0)

    room = scenario.actor.world.get_entity(scenario.room_a)
    assert room.get_component(SpriteLayerComponent).layer == LAYER_BACKGROUND


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
    assert room.has_component(SpriteBoundsComponent)
    assert table.get_component(SpriteLayerComponent).layer == LAYER_FURNITURE
    assert apple.get_component(SpriteLayerComponent).layer == LAYER_ITEM
    assert container_of(table) == room.id
    assert container_of(apple) == room.id
    assert room.has_relationship(Contains, table.id)
    assert room.has_relationship(Contains, apple.id)
    assert apple.has_relationship(PlacedOn, table.id)

    table_pos = table.get_component(SpritePositionComponent)
    table_bounds = table.get_component(SpriteBoundsComponent)
    apple_pos = apple.get_component(SpritePositionComponent)
    assert abs(apple_pos.x - table_pos.x) <= table_bounds.width / 2.0
    assert abs(apple_pos.y - table_pos.y) <= table_bounds.height / 2.0


def test_generated_positions_cover_directions_and_floor_fallback():
    scenario = build_scenario()
    world = scenario.actor.world
    room = world.get_entity(scenario.room_a)
    character = spawn_entity(
        world,
        [
            CharacterComponent(species="hare"),
            SpriteBoundsComponent(width=5.0, height=8.0, solid=True),
        ],
    )
    floor_item = spawn_entity(world, [PortableComponent(), SpriteBoundsComponent()])
    north = spawn_entity(
        world,
        [
            IdentityComponent(name="north hatch", kind="door"),
            DoorComponent(),
            SpriteBoundsComponent(width=10.0, height=8.0),
        ],
    )
    south = spawn_entity(
        world,
        [
            IdentityComponent(name="south hatch", kind="door"),
            DoorComponent(),
            SpriteBoundsComponent(width=10.0, height=8.0),
        ],
    )
    east = spawn_entity(
        world,
        [
            IdentityComponent(name="east hatch", kind="door"),
            DoorComponent(),
            SpriteBoundsComponent(width=10.0, height=8.0),
        ],
    )
    west = spawn_entity(
        world,
        [
            IdentityComponent(name="west hatch", kind="door"),
            DoorComponent(),
            SpriteBoundsComponent(width=10.0, height=8.0),
        ],
    )
    unnamed_door = spawn_entity(
        world, [DoorComponent(), SpriteBoundsComponent(width=10.0, height=8.0)]
    )

    assert 30.0 <= toonsim._generated_position(world, character, room, "c").x <= 70.0
    assert toonsim._generated_position(world, north, room, "n").y == 4.0
    assert toonsim._generated_position(world, south, room, "s").y == 96.0
    assert toonsim._generated_position(world, east, room, "e").x == 95.0
    assert toonsim._generated_position(world, west, room, "w").x == 5.0
    assert 5.0 <= toonsim._generated_position(world, unnamed_door, room, "u").x <= 95.0

    pos = toonsim._generated_position(world, floor_item, room, "floor")
    assert 2.0 <= pos.x <= 98.0
    assert 2.0 <= pos.y <= 98.0


def test_generated_surface_position_preserves_existing_placed_on_edge():
    scenario = build_scenario()
    world = scenario.actor.world
    room = world.get_entity(scenario.room_a)
    surface = spawn_entity(
        world,
        [
            IdentityComponent(name="desk", kind="desk"),
            SpritePositionComponent(x=45.0, y=45.0),
            SpriteBoundsComponent(width=20.0, height=10.0, solid=True),
        ],
    )
    item = spawn_entity(world, [PortableComponent(), SpriteBoundsComponent()])
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), surface.id)
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), item.id)
    item.add_relationship(PlacedOn(surface="top"), surface.id)

    pos = toonsim._generated_position(world, item, room, "item")

    assert item.has_relationship(PlacedOn, surface.id)
    assert abs(pos.x - 45.0) <= 10.0
    assert abs(pos.y - 45.0) <= 5.0

    unplaced = spawn_entity(world, [PortableComponent(), SpriteBoundsComponent()])
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), unplaced.id)
    toonsim._generated_position(world, unplaced, room, "unplaced-item")
    assert unplaced.has_relationship(PlacedOn, surface.id)


def test_worldgen_hook_ignores_invalid_or_non_room_events():
    scenario = build_scenario()
    hook = toonsim.ToonWorldgenHook()
    hook.actor = scenario.actor
    room = scenario.actor.world.get_entity(scenario.room_a)

    hook._on_room(SimpleNamespace(entity_id="bad-id"))
    hook._on_object(SimpleNamespace(entity_id="bad-id", room_id=None, container_id=None))
    hook._on_object(
        SimpleNamespace(
            entity_id=str(scenario.character),
            room_id=str(scenario.room_a),
            container_id=str(scenario.character),
            object_key="nested",
        )
    )
    hook._on_object(
        SimpleNamespace(
            entity_id=str(scenario.character),
            room_id="entity_999",
            container_id="entity_999",
            object_key="missing",
        )
    )
    hook._on_character(SimpleNamespace(entity_id="entity_999", room_id=str(scenario.room_a)))

    assert not room.has_component(ToonRoomComponent)


def test_worldgen_hook_preserves_explicit_renderable_parts():
    scenario = build_scenario()
    actor = scenario.actor
    hook = toonsim.ToonWorldgenHook()
    hook.actor = actor
    room = actor.world.get_entity(scenario.room_a)
    room.add_component(ToonRoomComponent(default_start=True))
    room.add_component(SpritePositionComponent(x=12.0, y=34.0))
    entity = spawn_entity(
        actor.world,
        [
            IdentityComponent(name="apple", kind="food"),
            PortableComponent(),
            SpriteImageComponent(url="https://cdn/apple.png"),
            SpriteScaleComponent(scale=2.0),
            SpriteBoundsComponent(width=9.0, height=9.0),
            SpritePositionComponent(x=22.0, y=33.0),
        ],
    )
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), entity.id)

    hook._on_room(SimpleNamespace(entity_id=str(room.id)))
    hook._on_object(
        SimpleNamespace(
            entity_id=str(entity.id),
            room_id=str(room.id),
            container_id=str(room.id),
            object_key="apple",
        )
    )
    hook._on_character(
        SimpleNamespace(
            entity_id=str(scenario.character),
            room_id=str(room.id),
            character_key="juniper",
        )
    )

    assert room.get_component(ToonRoomComponent).default_start is True
    assert room.get_component(SpritePositionComponent).x == 12.0
    assert entity.get_component(SpriteImageComponent).url == "https://cdn/apple.png"
    assert entity.get_component(SpriteScaleComponent).scale == 2.0
    assert entity.get_component(SpritePositionComponent).x == 22.0


def test_worldgen_hook_keeps_existing_character_position():
    scenario = build_scenario()
    actor = scenario.actor
    hook = toonsim.ToonWorldgenHook()
    hook.actor = actor
    character = actor.world.get_entity(scenario.character)
    character.add_component(SpritePositionComponent(x=42.0, y=24.0))

    hook._on_character(
        SimpleNamespace(
            entity_id=str(scenario.character),
            room_id=str(scenario.room_a),
            character_key="juniper",
        )
    )

    # Already-positioned character is left where it sits (430->exit false branch).
    assert character.get_component(SpritePositionComponent).x == 42.0
    assert character.get_component(SpritePositionComponent).y == 24.0


def test_ensure_renderable_skips_layer_and_bounds_for_non_renderable_entity():
    scenario = build_scenario()
    actor = scenario.actor
    hook = toonsim.ToonWorldgenHook()
    hook.actor = actor
    # A faction is not renderable: default_layer_for and default_bounds_for both
    # return None, so the layer guard (375->377) and bounds guard (383->exit) both
    # take their false path -- only SpriteImageComponent/SpriteScaleComponent get attached.
    faction = spawn_entity(actor.world, [IdentityComponent(name="The Warren", kind="faction")])

    hook._ensure_renderable(faction)

    assert not faction.has_component(SpriteLayerComponent)
    assert not faction.has_component(SpriteBoundsComponent)
    assert faction.has_component(SpriteImageComponent)
    assert faction.has_component(SpriteScaleComponent)


def test_backfill_skips_bounds_when_default_is_missing(monkeypatch):
    scenario = build_scenario()
    world = scenario.actor.world
    apple = spawn_entity(
        world, [IdentityComponent(name="an apple", kind="food"), PortableComponent()]
    )
    # Force the renderable entity to report no default footprint so the backfill's
    # bounds guard (211->198) takes its false path and loops on without adding bounds.
    monkeypatch.setattr(toonsim, "default_bounds_for", lambda entity: None)

    _backfill(world)

    assert apple.get_component(SpriteLayerComponent).layer == LAYER_ITEM
    assert not apple.has_component(SpriteBoundsComponent)


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
    pos = character.get_component(SpritePositionComponent)
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
    assert not character.has_component(SpritePositionComponent)


def test_move_sprite_rejects_solid_collision():
    scenario = build_scenario()
    world = scenario.actor.world
    blocker = spawn_entity(
        world,
        [
            IdentityComponent(name="oak table", kind="table"),
            SpritePositionComponent(x=40.0, y=40.0),
            SpriteBoundsComponent(width=12.0, height=12.0, solid=True),
        ],
    )
    world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), blocker.id
    )
    ctx = HandlerContext(world, scenario.actor.epoch)

    result = MoveSpriteHandler().execute(ctx, _move_sprite(scenario, x=40.0, y=40.0))

    character = world.get_entity(scenario.character)
    assert result.reason == "position is blocked"
    assert not character.has_component(SpritePositionComponent)


def test_move_sprite_allows_nearby_non_overlapping_solid_member():
    scenario = build_scenario()
    world = scenario.actor.world
    blocker = spawn_entity(
        world,
        [
            IdentityComponent(name="oak table", kind="table"),
            SpritePositionComponent(x=70.0, y=70.0),
            SpriteBoundsComponent(width=12.0, height=12.0, solid=True),
        ],
    )
    world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), blocker.id
    )
    ctx = HandlerContext(world, scenario.actor.epoch)

    result = MoveSpriteHandler().execute(ctx, _move_sprite(scenario, x=40.0, y=40.0))

    assert result.ok is True
    assert world.get_entity(scenario.character).get_component(SpritePositionComponent).x == 40.0


def test_move_sprite_ignores_non_solid_and_unpositioned_members():
    scenario = build_scenario()
    world = scenario.actor.world
    non_solid = spawn_entity(
        world,
        [
            IdentityComponent(name="apple", kind="food"),
            SpritePositionComponent(x=40.0, y=40.0),
            SpriteBoundsComponent(width=20.0, height=20.0, solid=False),
        ],
    )
    unpositioned_solid = spawn_entity(
        world,
        [
            IdentityComponent(name="table", kind="table"),
            SpriteBoundsComponent(width=20.0, height=20.0, solid=True),
        ],
    )
    room = world.get_entity(scenario.room_a)
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), non_solid.id)
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), unpositioned_solid.id)
    ctx = HandlerContext(world, scenario.actor.epoch)

    result = MoveSpriteHandler().execute(ctx, _move_sprite(scenario, x=40.0, y=40.0))

    assert result.ok is True
    assert world.get_entity(scenario.character).get_component(SpritePositionComponent).x == 40.0


def test_move_sprite_rejects_character_without_room():
    scenario = build_scenario()
    world = scenario.actor.world
    world.get_entity(scenario.room_a).remove_relationship(Contains, scenario.character)
    ctx = HandlerContext(world, scenario.actor.epoch)

    result = MoveSpriteHandler().execute(ctx, _move_sprite(scenario, x=40.0, y=40.0))

    assert result.reason == "character is not in a room"


def test_move_sprite_rejects_entity_without_sprite_bounds():
    scenario = build_scenario()
    world = scenario.actor.world
    character = world.get_entity(scenario.character)
    character.remove_component(CharacterComponent)
    ctx = HandlerContext(world, scenario.actor.epoch)

    result = MoveSpriteHandler().execute(ctx, _move_sprite(scenario, x=40.0, y=40.0))

    assert result.reason == "character has no sprite bounds"


def test_move_sprite_preserves_existing_character_bounds():
    scenario = build_scenario()
    world = scenario.actor.world
    character = world.get_entity(scenario.character)
    character.add_component(SpriteBoundsComponent(width=3.0, height=7.0, solid=True))
    ctx = HandlerContext(world, scenario.actor.epoch)

    result = MoveSpriteHandler().execute(ctx, _move_sprite(scenario, x=40.0, y=40.0))

    # The character already has bounds, so they are reused unchanged (477->479).
    assert result.ok is True
    bounds = world.get_entity(scenario.character).get_component(SpriteBoundsComponent)
    assert bounds.width == 3.0
    assert bounds.height == 7.0
    assert world.get_entity(scenario.character).get_component(SpritePositionComponent).x == 40.0


async def test_move_sprite_rejects_bad_payload():
    scenario = build_scenario()
    scenario.actor.register_handler(MoveSpriteHandler())

    await scenario.actor.submit(_move_sprite(scenario, x="left"))
    await scenario.actor.tick(0.0)

    character = scenario.actor.world.get_entity(scenario.character)
    assert not character.has_component(SpritePositionComponent)


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
