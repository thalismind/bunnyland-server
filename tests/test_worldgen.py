"""Tests for world generation: validation, instantiation, and the MVP checklist."""

from __future__ import annotations

import pytest

from bunnyland.core import (
    CharacterComponent,
    CommandCost,
    ContainerComponent,
    ControlledBy,
    ExitTo,
    IdentityComponent,
    Lane,
    LightComponent,
    MemoryProfileComponent,
    PortableComponent,
    RoomComponent,
    SuspendedComponent,
    TemperatureComponent,
    WorldActor,
    build_submitted_command,
    container_of,
)
from bunnyland.core.components import WritableComponent
from bunnyland.core.events import WorldGeneratedEvent
from bunnyland.mechanics.consumables import DrinkableComponent, FoodComponent
from bunnyland.plugins import apply_plugins, bunnyland_plugins
from bunnyland.worldgen import (
    CharacterProposal,
    CharacterSpec,
    ExitSpec,
    GenOptions,
    RoomSpec,
    StubWorldBuilder,
    WorldProposal,
    halloween_generator,
    holiday_generator,
    instantiate,
    validate_proposal,
    waiting_room_generator,
)

HOUR = 3600.0


def test_validate_rejects_dangling_references():
    proposal = WorldProposal(
        seed="x",
        rooms=[RoomSpec(key="a", title="A")],
        exits=[ExitSpec(from_key="a", direction="north", to_key="ghost")],
    )
    errors = validate_proposal(proposal)
    assert any("unknown room" in e for e in errors)


def test_validate_accepts_stub_proposal():
    proposal = StubWorldBuilder().propose("a quiet marsh")
    assert validate_proposal(proposal) == []


def test_character_proposal_defaults_null_llm_fields():
    proposal = CharacterProposal.model_validate(
        {"name": "Moss", "controller": "llm", "llm_profile": None, "llm_model": None}
    )

    assert proposal.llm_profile == "default"
    assert proposal.llm_model == "deepseek-v4-flash"


def test_character_spec_defaults_to_flash_controller_model():
    spec = CharacterSpec.model_validate(
        {
            "key": "moss",
            "name": "Moss",
            "room_key": "burrow",
            "controller": "llm",
            "llm_model": None,
        }
    )

    assert spec.llm_model == "deepseek-v4-flash"


def test_generation_options_default_to_pro_worldgen_model():
    assert GenOptions(llm=True).model == "deepseek-v4-pro"
    assert GenOptions(llm=True).provider == "ollama"


async def test_waiting_room_generator_builds_single_white_room_with_red_chair():
    actor = WorldActor()

    result = await waiting_room_generator(actor, "ignored seed", GenOptions())

    assert set(result.rooms) == {"waiting_room"}
    assert set(result.objects) == {"red_chair"}
    assert result.characters == {}

    room = actor.world.get_entity(result.rooms["waiting_room"])
    room_component = room.get_component(RoomComponent)
    assert room_component.title == "Waiting Room"
    assert room_component.biome == "white-room"
    assert room_component.indoor is True
    assert room.get_component(LightComponent).level == 1.0
    assert room.get_component(TemperatureComponent).celsius == 20.0

    chair = actor.world.get_entity(result.objects["red_chair"])
    identity = chair.get_component(IdentityComponent)
    assert identity.name == "a red chair"
    assert identity.kind == "chair"
    assert not chair.has_component(PortableComponent)
    assert container_of(chair) == result.rooms["waiting_room"]


@pytest.mark.parametrize(
    ("generate", "expected"),
    [
        (
            halloween_generator,
            {
                "rooms": {"porch", "foyer", "cellar"},
                "objects": {"candy_bowl", "lantern", "spell_note", "rain_barrel"},
                "characters": {"caretaker", "host"},
                "start": "porch",
                "direction": "in",
                "destination": "foyer",
                "claimable": "caretaker",
                "portable": "lantern",
                "food": "candy_bowl",
                "water": "rain_barrel",
            },
        ),
        (
            holiday_generator,
            {
                "rooms": {"snowfield", "workshop", "stable"},
                "objects": {"cocoa", "gingerbread", "gift_box", "silver_bell"},
                "characters": {"helper", "foreman"},
                "start": "snowfield",
                "direction": "in",
                "destination": "workshop",
                "claimable": "helper",
                "portable": "silver_bell",
                "food": "gingerbread",
                "water": "cocoa",
            },
        ),
    ],
)
async def test_seasonal_generators_build_playable_demo_worlds(generate, expected):
    actor = WorldActor()

    result = await generate(actor, "ignored seed", GenOptions())

    assert set(result.rooms) == expected["rooms"]
    assert set(result.objects) == expected["objects"]
    assert set(result.characters) == expected["characters"]

    start = actor.world.get_entity(result.rooms[expected["start"]])
    exits = {edge.direction: target for edge, target in start.get_relationships(ExitTo)}
    assert exits[expected["direction"]] == result.rooms[expected["destination"]]

    claimable = actor.world.get_entity(result.characters[expected["claimable"]])
    assert claimable.has_component(CharacterComponent)
    assert claimable.has_component(SuspendedComponent)

    portable = actor.world.get_entity(result.objects[expected["portable"]])
    assert portable.has_component(PortableComponent)

    food = actor.world.get_entity(result.objects[expected["food"]])
    assert food.has_component(FoodComponent)

    water = actor.world.get_entity(result.objects[expected["water"]])
    assert water.has_component(DrinkableComponent)


async def test_instantiate_builds_the_mvp_checklist():
    actor = WorldActor()
    events = []
    actor.bus.subscribe(WorldGeneratedEvent, events.append)

    proposal = StubWorldBuilder().propose("a quiet marsh")
    result = await instantiate(actor, proposal)
    world = actor.world

    # at least a few connected rooms
    assert len(result.rooms) == 2
    burrow = world.get_entity(result.rooms["burrow"])
    assert burrow.has_component(RoomComponent)

    # food + water + container + writable paper
    assert world.get_entity(result.objects["berries"]).has_component(FoodComponent)
    assert world.get_entity(result.objects["basin"]).has_component(DrinkableComponent)
    assert world.get_entity(result.objects["chest"]).has_component(ContainerComponent)
    assert world.get_entity(result.objects["paper"]).has_component(WritableComponent)

    # a controllable (suspended/claimable) character and an LLM character
    juniper = world.get_entity(result.characters["juniper"])
    hazel = world.get_entity(result.characters["hazel"])
    assert juniper.has_component(SuspendedComponent)
    assert juniper.has_component(CharacterComponent)
    assert not hazel.has_component(SuspendedComponent)
    assert hazel.get_relationships(ControlledBy)  # has an (LLM) controller
    assert hazel.get_component(MemoryProfileComponent).vector_collection == "mem-hazel"

    # both characters are in the burrow (so speech has an audience)
    assert container_of(juniper) == result.rooms["burrow"]
    assert container_of(hazel) == result.rooms["burrow"]

    assert events and events[0].room_count == 2 and events[0].character_count == 2


async def test_generated_world_is_playable_via_plugins():
    # Apply the core verbs, then drive a generated character through a move.
    actor = WorldActor()
    apply_plugins(bunnyland_plugins(), actor)
    result = await instantiate(actor, StubWorldBuilder().propose("seed"))

    # Resume Juniper under a fresh controller so it can act.
    from bunnyland.core import spawn_entity

    controller = spawn_entity(actor.world)
    gen = actor.assign_controller(result.characters["juniper"], controller.id)
    actor.world.get_entity(result.characters["juniper"]).remove_component(SuspendedComponent)

    move = build_submitted_command(
        character_id=str(result.characters["juniper"]),
        controller_id=str(controller.id),
        controller_generation=gen,
        command_type="move",
        cost=CommandCost(action=1),
        lane=Lane.WORLD,
        payload={"direction": "north"},
    )
    await actor.submit(move)
    await actor.tick(HOUR)

    juniper = actor.world.get_entity(result.characters["juniper"])
    assert container_of(juniper) == result.rooms["tunnel"]


async def test_instantiate_raises_on_invalid_proposal():
    actor = WorldActor()
    bad = WorldProposal(seed="x", rooms=[])
    with pytest.raises(ValueError):
        await instantiate(actor, bad)
