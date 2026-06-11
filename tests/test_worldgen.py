"""Tests for world generation: validation, instantiation, and the MVP checklist."""

from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from bunnyland.core import (
    CharacterComponent,
    CommandCost,
    ContainerComponent,
    ControlledBy,
    EditorDisplayComponent,
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
    parse_entity_id,
)
from bunnyland.core.components import ReadableComponent, WritableComponent
from bunnyland.core.events import (
    CharacterGeneratedEvent,
    ObjectGeneratedEvent,
    RoomGeneratedEvent,
    WorldGeneratedEvent,
)
from bunnyland.mechanics.consumables import DrinkableComponent, FoodComponent
from bunnyland.plugins import ContentContribution, Plugin, apply_plugins, bunnyland_plugins
from bunnyland.worldgen import (
    CharacterProposal,
    CharacterSpec,
    ExitSpec,
    GenOptions,
    ItemProposal,
    ObjectSpec,
    RoomSpec,
    StoryEventProposal,
    StubWorldBuilder,
    WorldProposal,
    halloween_generator,
    holiday_generator,
    instantiate,
    tower_debate_generator,
    validate_proposal,
    waiting_room_generator,
)
from bunnyland.worldgen.ollama_builder import OllamaWorldBuilder, repair_world_proposal

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


def test_character_proposal_coerces_object_llm_profile_to_string():
    proposal = CharacterProposal.model_validate(
        {
            "name": "Elara",
            "controller": "llm",
            "llm_profile": {"name": "meadow-shepherd", "role": "guide"},
        }
    )

    assert proposal.llm_profile == "meadow-shepherd"


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


def test_ollama_world_builder_initializes_client_with_host_and_auth(monkeypatch):
    captured = {}

    class Client:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setitem(sys.modules, "ollama", SimpleNamespace(Client=Client))

    builder = OllamaWorldBuilder(model="world-model", host="https://ollama.example", api_key="k")

    assert builder._model == "world-model"
    assert captured == {
        "host": "https://ollama.example",
        "headers": {"Authorization": "Bearer k"},
    }


def test_story_event_proposal_accepts_common_severity_labels():
    event = StoryEventProposal.model_validate(
        {
            "title": "A harmless clue",
            "severity": "minor",
            "budget_spent": "low",
            "stimulus_intensity": "high",
        }
    )

    assert event.severity == 1.0
    assert event.budget_spent == 1.0
    assert event.stimulus_intensity == 3.0


def test_item_and_object_proposals_default_explicit_null_scalars():
    item = ItemProposal.model_validate(
        {
            "name": "a live-test tool",
            "nutrition": None,
            "satiety": None,
            "hydration": None,
            "open": None,
            "locked": None,
        }
    )
    obj = ObjectSpec.model_validate(
        {
            "key": "tool",
            "room_key": "room",
            "name": "a live-test tool",
            "nutrition": None,
            "satiety": None,
            "hydration": None,
            "open": None,
            "locked": None,
        }
    )

    assert item.nutrition == 0.0
    assert item.satiety == 0.0
    assert item.hydration == 0.0
    assert item.open is True
    assert item.locked is False
    assert obj.nutrition == 0.0
    assert obj.satiety == 0.0
    assert obj.hydration == 0.0
    assert obj.open is True
    assert obj.locked is False


def test_repair_world_proposal_moves_nested_objects_to_first_room_and_drops_bad_exits():
    proposal = WorldProposal.model_validate(
        {
            "seed": "repair",
            "rooms": [{"key": "meadow", "title": "Meadow"}],
            "exits": [{"from_key": "meadow", "direction": "east", "to_key": "ghost"}],
            "objects": [
                {
                    "key": "apple",
                    "room_key": "box",
                    "name": "an apple",
                    "kind": "food",
                }
            ],
            "characters": [{"key": "helper", "name": "Helper", "room_key": "box"}],
        }
    )

    repaired = repair_world_proposal(proposal)

    assert repaired.objects[0].room_key == "meadow"
    assert repaired.characters[0].room_key == "meadow"
    assert repaired.exits == []


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


async def test_tower_debate_generator_builds_locked_philosophy_room():
    actor = WorldActor()

    result = await tower_debate_generator(actor, "ignored seed", GenOptions())

    assert set(result.rooms) == {"tower_room", "stair_landing"}
    assert set(result.objects) == {
        "arched_window",
        "debate_table",
        "angel_chair",
        "devil_chair",
        "narrow_bed",
        "cool_prisoners_print",
        "great_day_print",
        "higher_force_plaque",
    }
    assert set(result.characters) == {"angel", "devil"}

    tower_room = actor.world.get_entity(result.rooms["tower_room"])
    room_component = tower_room.get_component(RoomComponent)
    assert room_component.title == "Locked Tower Room"
    assert room_component.indoor is True
    exits = {
        edge.direction: (edge, target)
        for edge, target in tower_room.get_relationships(ExitTo)
    }
    down_edge, down_target = exits["down"]
    assert down_edge.locked is True
    assert down_target == result.rooms["stair_landing"]

    angel = actor.world.get_entity(result.characters["angel"])
    devil = actor.world.get_entity(result.characters["devil"])
    assert angel.get_component(CharacterComponent).species == "angel"
    assert devil.get_component(CharacterComponent).species == "devil"
    assert not angel.has_component(SuspendedComponent)
    assert not devil.has_component(SuspendedComponent)
    assert angel.get_relationships(ControlledBy)
    assert devil.get_relationships(ControlledBy)
    assert container_of(angel) == result.rooms["tower_room"]
    assert container_of(devil) == result.rooms["tower_room"]

    window = actor.world.get_entity(result.objects["arched_window"])
    assert window.get_component(IdentityComponent).kind == "window"
    assert not window.has_component(PortableComponent)

    art = actor.world.get_entity(result.objects["great_day_print"])
    readable = art.get_component(ReadableComponent)
    assert readable.title == "Make Every Day The Same Argument"
    assert "same debate about meaning" in readable.text
    assert "unseen above the tower" in readable.text


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


async def test_instantiate_emits_typed_generation_events_with_intent_tags_and_wants():
    actor = WorldActor()
    rooms: list[RoomGeneratedEvent] = []
    objects: list[ObjectGeneratedEvent] = []
    characters: list[CharacterGeneratedEvent] = []
    actor.bus.subscribe(RoomGeneratedEvent, rooms.append)
    actor.bus.subscribe(ObjectGeneratedEvent, objects.append)
    actor.bus.subscribe(CharacterGeneratedEvent, characters.append)

    proposal = WorldProposal(
        seed="storm cellar",
        rooms=[
            RoomSpec(
                key="cellar",
                title="Flooded Cellar",
                biome="cellar",
                indoor=True,
                description="a flooded cellar, signs of recent struggle",
                tags=("wet",),
                wants=("humidity",),
            )
        ],
        objects=[
            ObjectSpec(
                key="crate",
                room_key="cellar",
                name="a swollen crate",
                kind="container",
                description="waterlogged supplies",
                tags=("salvage",),
                wants=("loot-table",),
            )
        ],
        characters=[
            CharacterSpec(
                key="scout",
                name="Scout",
                room_key="cellar",
                species="hare",
                description="a worried scout checking the flood",
                traits=("watchful",),
                tags=("local",),
                wants=("faction-allegiance",),
            )
        ],
    )

    result = await instantiate(actor, proposal)

    assert [event.room_key for event in rooms] == ["cellar"]
    assert rooms[0].entity_id == str(result.rooms["cellar"])
    assert rooms[0].intent == "a flooded cellar, signs of recent struggle"
    assert rooms[0].tags == ("cellar", "indoor", "wet")
    assert rooms[0].wants == ("humidity",)

    assert [event.object_key for event in objects] == ["crate"]
    assert objects[0].entity_id == str(result.objects["crate"])
    assert objects[0].room_id == str(result.rooms["cellar"])
    assert objects[0].container_id == str(result.rooms["cellar"])
    assert objects[0].intent == "waterlogged supplies"
    assert objects[0].tags == ("container", "salvage")
    assert objects[0].wants == ("loot-table",)

    assert [event.character_key for event in characters] == ["scout"]
    assert characters[0].entity_id == str(result.characters["scout"])
    assert characters[0].room_id == str(result.rooms["cellar"])
    assert characters[0].intent == "a worried scout checking the flood"
    assert characters[0].tags == ("hare", "watchful", "local")
    assert characters[0].wants == ("faction-allegiance",)


async def test_plugin_worldgen_hook_can_enrich_generated_entities():
    class RoomEmojiHook:
        def subscribe(self, actor: WorldActor) -> None:
            self.actor = actor
            actor.bus.subscribe(RoomGeneratedEvent, self.on_room)

        def on_room(self, event: RoomGeneratedEvent) -> None:
            if "humidity" not in event.wants:
                return
            entity_id = parse_entity_id(event.entity_id)
            assert entity_id is not None
            self.actor.world.get_entity(entity_id).add_component(
                EditorDisplayComponent(emoji="~")
            )

    actor = WorldActor()
    apply_plugins(
        [
            Plugin(
                id="humidity",
                name="Humidity",
                content=ContentContribution(worldgen_hooks=(RoomEmojiHook,)),
            )
        ],
        actor,
    )
    proposal = WorldProposal(
        seed="rain",
        rooms=[
            RoomSpec(
                key="room",
                title="Rain Room",
                description="rain pools on the floor",
                wants=("humidity",),
            )
        ],
    )

    result = await instantiate(actor, proposal)

    room = actor.world.get_entity(result.rooms["room"])
    assert room.get_component(EditorDisplayComponent).emoji == "~"


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
