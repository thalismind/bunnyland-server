"""Tests for toon-sim sprite backfill (positions, images, draw layers)."""

from __future__ import annotations

from conftest import build_scenario

from bunnyland.core import (
    ActionPointsComponent,
    CommandCost,
    ContainerComponent,
    DoorComponent,
    IdentityComponent,
    Lane,
    PortableComponent,
    build_submitted_command,
    spawn_entity,
)
from bunnyland.mechanics.toonsim import (
    LAYER_BACKGROUND,
    LAYER_CHARACTER,
    LAYER_FURNITURE,
    LAYER_ITEM,
    MoveSpriteHandler,
    SpriteBackfillConsequence,
    SpriteImage,
    SpriteLayer,
    SpriteMovedEvent,
    SpritePosition,
    SpriteScale,
    default_layer_for,
    install_toonsim,
)


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

    await scenario.actor.submit(_move_sprite(scenario, x=4.0, y=-1.5))
    await scenario.actor.tick(0.0)

    character = scenario.actor.world.get_entity(scenario.character)
    pos = character.get_component(SpritePosition)
    assert (pos.x, pos.y) == (4.0, -1.5)
    # No action points were spent on the free in-room move.
    assert character.get_component(ActionPointsComponent).current == 5.0
    assert moved and (moved[-1].x, moved[-1].y) == (4.0, -1.5)
    assert moved[-1].room_id == str(scenario.room_a)


async def test_move_sprite_rejects_bad_payload():
    scenario = build_scenario()
    scenario.actor.register_handler(MoveSpriteHandler())

    await scenario.actor.submit(_move_sprite(scenario, x="left"))
    await scenario.actor.tick(0.0)

    character = scenario.actor.world.get_entity(scenario.character)
    assert not character.has_component(SpritePosition)
