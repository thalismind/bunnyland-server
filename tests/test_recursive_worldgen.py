"""Tests for the recursive, breadth-first world generator."""

from __future__ import annotations

from bunnyland.core import (
    CharacterComponent,
    ContainerComponent,
    ControlledBy,
    DoorComponent,
    SuspendedComponent,
    WorldActor,
    container_of,
    contents,
)
from bunnyland.core.components import WritableComponent
from bunnyland.core.edges import ExitTo
from bunnyland.core.events import WorldGeneratedEvent
from bunnyland.mechanics.consumables import FoodComponent
from bunnyland.worldgen import (
    DanglingResolution,
    GenOptions,
    RecursiveWorldGenerator,
    StubRecursiveBuilder,
    oneshot_generator,
    recursive_generator,
)


def _exits(world, room_id):
    room = world.get_entity(room_id)
    return {edge.direction: target for edge, target in room.get_relationships(ExitTo)}


async def test_bfs_respects_the_room_budget():
    actor = WorldActor()
    gen = RecursiveWorldGenerator(actor, StubRecursiveBuilder(), max_rooms=2)
    result = await gen.generate("a quiet marsh")

    assert len(result.rooms) == 2
    assert gen.stats["rooms"] == 2


async def test_doors_are_bidirectional_unless_marked_one_way():
    actor = WorldActor()
    # Budget of 3 expands the north tunnel and the one-way slide (BFS order).
    gen = RecursiveWorldGenerator(actor, StubRecursiveBuilder(), max_rooms=3)
    result = await gen.generate("seed")
    world = actor.world

    root = result.rooms["room_0"]
    root_exits = _exits(world, root)
    assert "north" in root_exits
    assert "down" in root_exits

    # The north tunnel is two-way: the room behind it has a return exit to the root.
    tunnel = root_exits["north"]
    assert root in _exits(world, tunnel).values()

    # The down slide is one-way: the slide room has no exit back to the root.
    slide = root_exits["down"]
    assert root not in _exits(world, slide).values()


async def test_dangling_doors_are_sealed_dropped_or_linked():
    actor = WorldActor()
    # Budget of 3 leaves a hidden door (seal), a two-way door with no free target
    # (drop), and a two-way door with a free target (link).
    gen = RecursiveWorldGenerator(actor, StubRecursiveBuilder(), max_rooms=3)
    result = await gen.generate("seed")
    world = actor.world

    # The hidden vault door is sealed -> a locked Door object appears in the room.
    sealed = [
        oid
        for oid in result.objects.values()
        if world.get_entity(oid).has_component(DoorComponent)
    ]
    assert sealed and gen.stats["sealed"] >= 1
    assert not world.get_entity(sealed[0]).get_component(DoorComponent).open

    assert gen.stats["dropped"] >= 1
    assert gen.stats["linked"] >= 1


async def test_no_duplicate_exit_overwrites_on_link():
    actor = WorldActor()
    gen = RecursiveWorldGenerator(actor, StubRecursiveBuilder(), max_rooms=2)
    result = await gen.generate("seed")
    world = actor.world

    # Every exit still resolves to a real, distinct room (no clobbered edges).
    for room_id in result.rooms.values():
        for _edge, target in world.get_entity(room_id).get_relationships(ExitTo):
            assert world.has_entity(target)


async def test_rooms_are_populated_with_objects_and_characters():
    actor = WorldActor()
    gen = RecursiveWorldGenerator(actor, StubRecursiveBuilder(), max_rooms=2)
    result = await gen.generate("seed")
    world = actor.world

    berries = result.objects["room_0_obj0"]
    assert world.get_entity(berries).has_component(FoodComponent)
    paper = result.objects["room_0_obj3"]
    assert world.get_entity(paper).has_component(WritableComponent)

    juniper = world.get_entity(result.characters["char_0"])
    hazel = world.get_entity(result.characters["char_1"])
    assert juniper.has_component(CharacterComponent)
    assert juniper.has_component(SuspendedComponent)
    assert hazel.get_relationships(ControlledBy)  # llm controller
    assert container_of(juniper) == result.rooms["room_0"]


async def test_recurses_into_inventory_and_containers():
    actor = WorldActor()
    gen = RecursiveWorldGenerator(actor, StubRecursiveBuilder(), max_rooms=2)
    result = await gen.generate("seed")
    world = actor.world

    # Hazel carries a hazel twig (inventory recursion).
    hazel_id = result.characters["char_1"]
    assert contents(world.get_entity(hazel_id)), "Hazel should be carrying something"

    # The oak chest is a container and holds a ruby (container recursion).
    chest_id = result.objects["room_0_obj2"]
    chest = world.get_entity(chest_id)
    assert chest.has_component(ContainerComponent)
    assert contents(chest), "the chest should contain something"


async def test_emits_world_generated_event():
    actor = WorldActor()
    events: list[WorldGeneratedEvent] = []
    actor.bus.subscribe(WorldGeneratedEvent, events.append)
    gen = RecursiveWorldGenerator(actor, StubRecursiveBuilder(), max_rooms=2)
    result = await gen.generate("seed")

    assert events
    assert events[0].room_count == len(result.rooms)
    assert events[0].character_count == len(result.characters)


def test_dangling_resolution_defaults_to_seal():
    assert DanglingResolution().action == "seal"


async def test_builtin_generator_functions_produce_worlds_offline():
    options = GenOptions(llm=False, max_rooms=3)

    one = await oneshot_generator(WorldActor(), "seed", options)
    assert one.rooms and one.characters

    many = await recursive_generator(WorldActor(), "seed", options)
    assert len(many.rooms) == 3 and many.characters
