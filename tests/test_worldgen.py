"""Tests for world generation: validation, instantiation, and the MVP checklist."""

from __future__ import annotations

import sys
from dataclasses import dataclass, replace
from types import SimpleNamespace

import pytest
from relics import Component, Edge

from bunnyland.core import (
    CharacterComponent,
    CommandCost,
    ContainerComponent,
    ContainmentMode,
    Contains,
    ControlledBy,
    ExitTo,
    GenerationChild,
    GenerationDelta,
    GenerationError,
    GenerationIntentComponent,
    GenerationRequest,
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
    spawn_entity,
)
from bunnyland.core.components import ReadableComponent, WritableComponent
from bunnyland.core.ecs import replace_component
from bunnyland.core.events import (
    CharacterGeneratedEvent,
    ObjectGeneratedEvent,
    RoomGeneratedEvent,
    WorldGeneratedEvent,
)
from bunnyland.foundation.consumables.components import (
    ConsumableComponent,
    DrinkableComponent,
    FoodComponent,
)
from bunnyland.foundation.meters.mechanics import Meter, with_value
from bunnyland.foundation.needs.mechanics import HungerComponent
from bunnyland.foundation.persona.mechanics import GoalComponent
from bunnyland.foundation.tutorial.mechanics import (
    DELIVERY_MARK,
    HungryCourierAgent,
    HungryCourierControllerComponent,
)
from bunnyland.llm_agents import ControllerDispatch, ScriptedAgent
from bunnyland.plugins import (
    ContentContribution,
    EcsContribution,
    Plugin,
    apply_plugins,
    bunnyland_plugins,
)
from bunnyland.prompts.builder import PromptBuilder
from bunnyland.server import serialize_character_projection
from bunnyland.server.models import ClientRoomView
from bunnyland.server.serialization import (
    _first_run_suggestions,
    _has_named_inventory,
    _room_has_named_entity,
)
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
    collect_generators,
    halloween_generator,
    holiday_generator,
    instantiate,
    tower_debate_generator,
    validate_proposal,
    waiting_room_generator,
)
from bunnyland.worldgen.examples import APPLE_CROSSING_DEMO, BELL_GREEN_DEMO, CLOVER_CITY_DEMO
from bunnyland.worldgen.ollama_builder import OllamaWorldBuilder, repair_world_proposal

HOUR = 3600.0


async def _hungry_courier_world():
    actor = WorldActor()
    apply_plugins(bunnyland_plugins(), actor)
    world = await APPLE_CROSSING_DEMO.generate(actor, "apple", GenOptions())
    return actor, world


def _hungry_courier_agent(actor: WorldActor) -> HungryCourierAgent:
    dispatch = ControllerDispatch(actor, PromptBuilder(actor.world), ScriptedAgent([]))
    return HungryCourierAgent(dispatch, HungryCourierControllerComponent())


def _move_entity(actor: WorldActor, entity_id, destination_id) -> None:
    entity = actor.world.get_entity(entity_id)
    source_id = container_of(entity)
    if source_id is not None:
        actor.world.get_entity(source_id).remove_relationship(Contains, entity_id)
    actor.world.get_entity(destination_id).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), entity_id
    )


def _feed_character(character) -> None:
    replace_component(
        character,
        HungerComponent(meter=with_value(Meter(), 0.0), metabolism=0.0),
    )


class _WorldWithMissingEntities:
    def __init__(self, world, missing_ids) -> None:
        self._world = world
        self._missing_ids = set(missing_ids)

    def has_entity(self, entity_id) -> bool:
        if entity_id in self._missing_ids:
            return False
        return self._world.has_entity(entity_id)

    def __getattr__(self, name: str):
        return getattr(self._world, name)


async def test_hungry_courier_demo_surfaces_first_run_guidance():
    actor, world = await _hungry_courier_world()
    projection = serialize_character_projection(actor, str(world.characters["player"]))

    assert "Pip" in projection.current_goal
    assert [item.id for item in projection.checklist] == [
        "claim",
        "look",
        "room-action",
        "move",
        "say",
        "help-courier",
        "watch-courier",
        "inspect-consequence",
    ]
    assert any("Apple Hedge" in action for action in projection.suggested_actions)


async def test_apple_crossing_generator_builds_tutorial_world_shape():
    actor, world = await _hungry_courier_world()

    titles = {
        actor.world.get_entity(room_id).get_component(RoomComponent).title
        for room_id in world.rooms.values()
    }
    character_names = {
        actor.world.get_entity(character_id).get_component(IdentityComponent).name
        for character_id in world.characters.values()
    }

    assert APPLE_CROSSING_DEMO.name == "apple-crossing"
    assert {
        "Apple Crossing",
        "Pippa's Post Hut",
        "Apple Hedge",
        "Old Footbridge",
        "Mira's Cottage Lane",
        "Mira's Cottage",
    } <= titles
    assert {"Pippa Bramble", "Pip Thistle", "Mira Vale", "Rowan Reed"} <= character_names
    assert actor.world.get_entity(world.objects["apple"]).has_component(FoodComponent)
    assert actor.world.get_entity(world.objects["letter"]).has_component(ReadableComponent)


async def test_hungry_courier_demo_delivers_through_validated_actions():
    actor, world = await _hungry_courier_world()

    # Simulate the golden-path player help: food becomes physically reachable to Moss.
    _move_entity(actor, world.objects["apple"], world.rooms["crossing"])

    dispatch = ControllerDispatch(actor, PromptBuilder(actor.world), ScriptedAgent([]))
    decisions = []
    for _ in range(8):
        await actor.tick(HOUR)
        decisions.extend(await dispatch.run_once())

    tools = [decision.tool for decision in decisions]
    assert "eat" in tools
    assert "take" in tools
    assert tools.count("move") >= 2
    assert "write" in tools

    ledger = actor.world.get_entity(world.objects["ledger"])
    assert DELIVERY_MARK in ledger.get_component(ReadableComponent).text


async def test_hungry_courier_agent_handles_invalid_done_and_hungry_states():
    actor, world = await _hungry_courier_world()
    agent = _hungry_courier_agent(actor)
    courier_id = str(world.characters["courier"])
    courier = actor.world.get_entity(world.characters["courier"])

    assert agent.decide("", None, character_id="not-an-entity") is None
    assert agent.decide("", None, character_id="entity_999999") is None

    decision = agent.decide("", None, character_id=courier_id)
    assert decision is not None
    assert decision.name == "say"
    assert "cannot just declare myself fed" in decision.arguments["text"]

    ledger = actor.world.get_entity(world.objects["ledger"])
    readable = ledger.get_component(ReadableComponent)
    replace_component(ledger, replace(readable, text=f"{readable.text}\n{DELIVERY_MARK}"))

    assert agent.decide("", None, character_id=courier_id) is None
    assert agent._room(courier) is not None


async def test_hungry_courier_agent_branches_on_real_world_state():
    actor, world = await _hungry_courier_world()
    agent = _hungry_courier_agent(actor)
    agent.component = HungryCourierControllerComponent(food_query="slice")
    courier = actor.world.get_entity(world.characters["courier"])
    courier_id = str(courier.id)
    letter = actor.world.get_entity(world.objects["letter"])
    ledger = actor.world.get_entity(world.objects["ledger"])

    _feed_character(courier)
    _move_entity(actor, letter.id, world.rooms["apple_hedge"])

    missing_letter = agent.decide("", None, character_id=courier_id)
    assert missing_letter is not None
    assert missing_letter.name == "say"
    assert "letter is not where I can reach it" in missing_letter.arguments["text"]

    _move_entity(actor, letter.id, world.rooms["crossing"])
    take_letter = agent.decide("", None, character_id=courier_id)
    assert take_letter is not None
    assert take_letter.name == "take"

    actor.world.get_entity(world.rooms["crossing"]).remove_relationship(Contains, letter.id)
    courier.add_relationship(Contains(mode=ContainmentMode.INVENTORY), letter.id)
    _move_entity(actor, courier.id, world.rooms["crossing"])

    move = agent.decide("", None, character_id=courier_id)
    assert move is not None
    assert move.name == "move"
    assert move.arguments["direction"] == "south"

    _move_entity(actor, courier.id, world.rooms["cottage"])
    _move_entity(actor, ledger.id, world.rooms["apple_hedge"])
    drop = agent.decide("", None, character_id=courier_id)
    assert drop is not None
    assert drop.name == "drop"

    _move_entity(actor, courier.id, world.rooms["apple_hedge"])
    actor.world.get_entity(world.rooms["apple_hedge"]).remove_relationship(Contains, courier.id)
    no_room = agent._room(courier)
    assert no_room is None
    assert agent._route_direction(no_room) is None

    actor.world.get_entity(world.rooms["apple_hedge"]).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), courier.id
    )
    plain_room = spawn_entity(actor.world, [IdentityComponent(name="Plain", kind="room")])
    assert agent._room_title(plain_room) == str(plain_room.id)
    _move_entity(actor, courier.id, plain_room.id)

    confused = agent.decide("", None, character_id=courier_id)
    assert confused is not None
    assert confused.name == "say"
    assert "need a route" in confused.arguments["text"]


async def test_hungry_courier_agent_finds_food_by_state_not_script():
    actor, world = await _hungry_courier_world()
    agent = _hungry_courier_agent(actor)
    agent.component = HungryCourierControllerComponent(food_query="slice")
    courier = actor.world.get_entity(world.characters["courier"])
    crossing = actor.world.get_entity(world.rooms["crossing"])
    hedge = actor.world.get_entity(world.rooms["apple_hedge"])
    hedge.remove_relationship(Contains, world.objects["apple"])

    apple_slice = spawn_entity(
        actor.world,
        [
            IdentityComponent(name="apple slice", kind="food"),
            FoodComponent(nutrition=1.0, satiety=1.0),
        ],
    )
    cracker = spawn_entity(
        actor.world,
        [
            IdentityComponent(name="cracker", kind="food"),
            FoodComponent(nutrition=1.0, satiety=1.0),
        ],
    )
    crossing.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), apple_slice.id)
    crossing.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), cracker.id)

    assert agent._reachable_food(courier) == apple_slice
    crossing.remove_relationship(Contains, apple_slice.id)

    agent.component = HungryCourierControllerComponent(food_query="apple")
    apple_sign = spawn_entity(actor.world, [IdentityComponent(name="apple sign", kind="sign")])
    crossing.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), apple_sign.id)
    assert agent._reachable_food(courier) == cracker

    crossing.remove_relationship(Contains, cracker.id)
    assert agent._reachable_food(courier) is None
    assert agent._is_hungry(spawn_entity(actor.world, [])) is False
    assert agent._matches(spawn_entity(actor.world, []), "apple") is False

    stale_item = spawn_entity(actor.world, [IdentityComponent(name="stale", kind="prop")])
    decoy_item = spawn_entity(actor.world, [IdentityComponent(name="decoy", kind="prop")])
    courier.add_relationship(Contains(mode=ContainmentMode.INVENTORY), stale_item.id)
    courier.add_relationship(Contains(mode=ContainmentMode.INVENTORY), decoy_item.id)

    fake_actor = SimpleNamespace(world=_WorldWithMissingEntities(actor.world, {stale_item.id}))
    fake_agent = HungryCourierAgent(
        SimpleNamespace(actor=fake_actor), HungryCourierControllerComponent()
    )
    assert fake_agent._carried_match(courier, "missing") is None


async def test_first_run_suggestions_cover_courier_states():
    actor, world = await _hungry_courier_world()
    player = actor.world.get_entity(world.characters["player"])
    apple = actor.world.get_entity(world.objects["apple"])
    crossing = actor.world.get_entity(world.rooms["crossing"])
    hedge = actor.world.get_entity(world.rooms["apple_hedge"])

    crossing_view = ClientRoomView(id=str(crossing.id), title="Apple Crossing")
    hedge_view = ClientRoomView(id=str(hedge.id), title="Apple Hedge")
    cottage_view = ClientRoomView(id=str(world.rooms["cottage"]), title="Mira's Cottage")
    unknown_view = ClientRoomView(id=str(crossing.id), title="Unknown Room")

    assert _room_has_named_entity(actor, crossing.id, "courier letter") is True
    assert _room_has_named_entity(actor, None, "anything") is False
    assert _room_has_named_entity(actor, parse_entity_id("entity_999999"), "anything") is False

    stale_item = spawn_entity(actor.world, [IdentityComponent(name="stale", kind="prop")])
    crossing.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), stale_item.id)
    fake_actor = SimpleNamespace(world=_WorldWithMissingEntities(actor.world, {stale_item.id}))
    assert _room_has_named_entity(fake_actor, crossing.id, "missing") is False

    assert "Go east" in _first_run_suggestions(actor, player, crossing_view)[0]

    _move_entity(actor, apple.id, player.id)
    assert _has_named_inventory(actor, player, "apple") is True
    assert "Drop the apple" in _first_run_suggestions(actor, player, crossing_view)[0]
    assert "Go west" in _first_run_suggestions(actor, player, hedge_view)[0]

    stale_inventory_item = spawn_entity(
        actor.world, [IdentityComponent(name="stale inventory", kind="prop")]
    )
    player.add_relationship(Contains(mode=ContainmentMode.INVENTORY), stale_inventory_item.id)
    fake_actor = SimpleNamespace(
        world=_WorldWithMissingEntities(actor.world, {stale_inventory_item.id})
    )
    assert _has_named_inventory(fake_actor, player, "missing") is False

    player.remove_relationship(Contains, apple.id)
    hedge.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), apple.id)
    assert "Take the red crossing apple" in _first_run_suggestions(actor, player, hedge_view)[0]

    hedge.remove_relationship(Contains, apple.id)
    assert "apple is gone" in _first_run_suggestions(actor, player, hedge_view)[0]
    assert "Inspect the delivery ledger" in _first_run_suggestions(actor, player, cottage_view)[0]
    assert "Watch Pip choose" in _first_run_suggestions(actor, player, unknown_view)[0]

    replace_component(player, GoalComponent(active_goals=()))
    assert _first_run_suggestions(actor, player, crossing_view) == []


async def test_progression_generators_are_registered_without_apartment_alias_changes():
    registry = collect_generators(bunnyland_plugins())

    assert registry["apple-crossing"] is APPLE_CROSSING_DEMO
    assert registry["bell-green"] is BELL_GREEN_DEMO
    assert registry["clover-city"] is CLOVER_CITY_DEMO
    assert registry["apple-crossing"].group == "tutorials"
    assert registry["bell-green"].group == "tutorials"
    assert registry["clover-city"].group == "tutorials"
    assert "hungry-courier-demo" not in registry
    assert "apartment-demo" in registry


async def test_bell_green_generator_builds_online_sandbox_shape():
    actor = WorldActor()
    world = await BELL_GREEN_DEMO.generate(actor, "bell-green", GenOptions())

    room_titles = {
        actor.world.get_entity(room_id).get_component(RoomComponent).title
        for room_id in world.rooms.values()
    }
    character_names = {
        actor.world.get_entity(character_id).get_component(IdentityComponent).name
        for character_id in world.characters.values()
    }
    readable = actor.world.get_entity(world.objects["notice"]).get_component(ReadableComponent)

    assert len(world.rooms) == 12
    assert 8 <= len(world.characters) <= 12
    assert {
        "Bell Green",
        "Bell Green Post Office",
        "Garden Walk",
        "Nettle's General Store",
        "Jun's Workshop",
        "Hearthwick Inn",
        "Pet Yard",
        "Old Bell Shrine",
    } <= room_titles
    assert {"Pippa Bramble", "Pip Thistle", "Mira Vale", "Button", "Morrow Grey"} <= (
        character_names
    )
    assert "help Pip finish a delivery" in readable.text


async def test_clover_city_generator_builds_dense_world_shape():
    from bunnyland.simpacks.lifesim.mechanics import RoutineComponent

    actor = WorldActor()
    world = await CLOVER_CITY_DEMO.generate(actor, "clover-city", GenOptions())

    room_titles = {
        actor.world.get_entity(room_id).get_component(RoomComponent).title
        for room_id in world.rooms.values()
    }
    character_names = {
        actor.world.get_entity(character_id).get_component(IdentityComponent).name
        for character_id in world.characters.values()
    }
    routines = list(actor.world.query().with_all([RoutineComponent]).execute_entities())
    bulletin = actor.world.get_entity(world.objects["bulletin"]).get_component(ReadableComponent)

    assert len(world.rooms) >= 20
    assert len(world.characters) >= 16
    assert {
        "Clover City Lobby",
        "Mailroom",
        "Elevator",
        "Laundry Room",
        "Rooftop Garden",
        "Community Kitchen",
        "Basement Workshop",
        "Security Office",
        "Street Stop",
    } <= room_titles
    assert {"Ada Warden", "Pip Thistle", "Kestrel Vale", "Brindle", "Morrow Grey"} <= (
        character_names
    )
    assert len(routines) >= len(world.characters) * 3
    assert "Missing package" in bulletin.text


def test_validate_rejects_dangling_references():
    proposal = WorldProposal(
        seed="x",
        rooms=[RoomSpec(key="a", title="A")],
        exits=[ExitSpec(from_key="a", direction="north", to_key="ghost")],
    )
    errors = validate_proposal(proposal)
    assert any("unknown room" in e for e in errors)


def test_validate_reports_duplicate_and_invalid_generation_references():
    proposal = WorldProposal(
        seed="bad",
        rooms=[
            RoomSpec(key="room", title="Room"),
            RoomSpec(key="room", title="Duplicate Room"),
        ],
        exits=[ExitSpec(from_key="ghost", direction="north", to_key="missing")],
        objects=[
            ObjectSpec(key="apple", room_key="room", name="apple"),
            ObjectSpec(key="apple", room_key="missing", name="duplicate apple"),
        ],
        characters=[
            CharacterSpec(
                key="helper",
                name="Helper",
                room_key="missing",
                controller="player",
            )
        ],
    )

    errors = validate_proposal(proposal)

    assert "duplicate room keys" in errors
    assert "duplicate object keys" in errors
    assert "exit from unknown room 'ghost'" in errors
    assert "exit to unknown room 'missing'" in errors
    assert "object 'apple' in unknown room 'missing'" in errors
    assert "character 'helper' in unknown room 'missing'" in errors
    assert "character 'helper' has invalid controller" in errors


async def test_validate_accepts_stub_proposal():
    proposal = await StubWorldBuilder().propose("a quiet marsh")
    assert validate_proposal(proposal) == []


def _single_character_proposal(**character_kwargs) -> WorldProposal:
    return WorldProposal(
        seed="ctrl",
        rooms=[RoomSpec(key="room", title="Room")],
        characters=[CharacterSpec(key="c", name="C", room_key="room", **character_kwargs)],
    )


def test_validate_accepts_behavioral_and_scripted_controllers():
    behavioral = _single_character_proposal(controller="behavioral", behavior_name="forager")
    scripted = _single_character_proposal(controller="scripted", script_name="wait")
    assert validate_proposal(behavioral) == []
    assert validate_proposal(scripted) == []


def test_validate_rejects_unknown_behavior_and_script_names():
    behavioral = _single_character_proposal(controller="behavioral", behavior_name="nope")
    scripted = _single_character_proposal(controller="scripted", script_name="nope")
    assert "character 'c' has unknown behavior 'nope'" in validate_proposal(behavioral)
    assert "character 'c' has unknown script 'nope'" in validate_proposal(scripted)


async def test_instantiate_wires_behavioral_and_scripted_controllers():
    from bunnyland.core.controllers import (
        BehaviorControllerComponent,
        ScriptedControllerComponent,
    )

    actor = WorldActor()
    proposal = WorldProposal(
        seed="ctrl",
        rooms=[RoomSpec(key="room", title="Room")],
        characters=[
            CharacterSpec(
                key="forager",
                name="Forager",
                room_key="room",
                controller="behavioral",
                behavior_name="forager",
            ),
            CharacterSpec(
                key="patroller",
                name="Patroller",
                room_key="room",
                controller="scripted",
                script_name="patrol",
                script_loop=True,
            ),
        ],
    )

    result = await instantiate(actor, proposal)
    world = actor.world

    forager = world.get_entity(result.characters["forager"])
    patroller = world.get_entity(result.characters["patroller"])
    assert not forager.has_component(SuspendedComponent)
    assert not patroller.has_component(SuspendedComponent)

    forager_controller = world.get_entity(list(forager.get_relationships(ControlledBy))[0][1])
    patrol_controller = world.get_entity(list(patroller.get_relationships(ControlledBy))[0][1])
    assert forager_controller.get_component(BehaviorControllerComponent).behavior_name == "forager"
    scripted = patrol_controller.get_component(ScriptedControllerComponent)
    assert scripted.script_name == "patrol"
    assert scripted.loop is True


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


def test_character_proposal_defaults_unrecognized_object_llm_profile():
    proposal = CharacterProposal.model_validate(
        {
            "name": "Elara",
            "controller": "llm",
            "llm_profile": {"role": "guide"},
        }
    )

    assert proposal.llm_profile == "default"


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

    class AsyncClient:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setitem(sys.modules, "ollama", SimpleNamespace(AsyncClient=AsyncClient))

    builder = OllamaWorldBuilder(model="world-model", host="https://ollama.example", api_key="k")

    assert builder._model == "world-model"
    assert captured == {
        "host": "https://ollama.example",
        "headers": {"Authorization": "Bearer k"},
    }


def test_ollama_world_builder_missing_extra_raises(monkeypatch):
    monkeypatch.setitem(sys.modules, "ollama", None)
    with pytest.raises(RuntimeError, match="OllamaWorldBuilder requires the 'llm' extra"):
        OllamaWorldBuilder()


async def test_ollama_world_builder_propose_parses_chat_response(monkeypatch):
    class AsyncClient:
        def __init__(self, **kwargs):
            self.calls: list[dict] = []

        async def chat(self, **kwargs):
            self.calls.append(kwargs)
            return {
                "message": {
                    "content": '{"rooms": [{"key": "atrium", "title": "Atrium", '
                    '"intent": "a glassy atrium"}]}'
                }
            }

    monkeypatch.setitem(sys.modules, "ollama", SimpleNamespace(AsyncClient=AsyncClient))

    builder = OllamaWorldBuilder(model="world-model")
    proposal = await builder.propose("a quiet seed")

    assert isinstance(proposal, WorldProposal)
    assert proposal.seed == "a quiet seed"
    assert builder._client.calls[0]["model"] == "world-model"
    assert builder._client.calls[0]["format"] == "json"


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


def test_generation_intent_models_accept_legacy_and_component_forms():
    legacy = RoomSpec.model_validate(
        {
            "key": "room",
            "title": "Room",
            "intent": "legacy room",
            "tags": ("old",),
            "wants": ("light",),
            "needs": ("water",),
        }
    )
    component = RoomSpec.model_validate(
        {
            "key": "room2",
            "title": "Room 2",
            "generation": GenerationIntentComponent(
                description="component room",
                tags=("component",),
                wants=("shade",),
                needs=("bunnyland.gardensim.soil",),
            ),
        }
    )
    scalar_generation = RoomSpec.model_validate(
        {"key": "room3", "title": "Room 3", "generation": 123}
    )

    with pytest.raises(ValueError):
        RoomSpec.model_validate("not a mapping")

    assert legacy.description == "legacy room"
    assert legacy.tags == ("old",)
    assert legacy.wants == ("light",)
    assert legacy.needs == ("water",)
    assert component.description == "component room"
    assert component.tags == ("component",)
    assert component.wants == ("shade",)
    assert component.needs == ("bunnyland.gardensim.soil",)
    assert scalar_generation.description == ""


def test_story_event_proposal_keeps_numeric_severity_values():
    event = StoryEventProposal(title="A clue", severity=2.5)

    assert event.severity == 2.5


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


def test_repair_world_proposal_leaves_empty_proposals_unchanged():
    proposal = WorldProposal(seed="empty")

    assert repair_world_proposal(proposal) is proposal


def test_repair_world_proposal_keeps_valid_references_without_warning(caplog):
    proposal = WorldProposal.model_validate(
        {
            "seed": "valid",
            "rooms": [
                {"key": "meadow", "title": "Meadow"},
                {"key": "burrow", "title": "Burrow"},
            ],
            "exits": [{"from_key": "meadow", "direction": "east", "to_key": "burrow"}],
            "objects": [{"key": "apple", "room_key": "meadow", "name": "an apple", "kind": "food"}],
            "characters": [{"key": "helper", "name": "Helper", "room_key": "burrow"}],
        }
    )

    with caplog.at_level("WARNING"):
        repaired = repair_world_proposal(proposal)

    # Nothing was repaired: every reference is already valid, so no warning is logged.
    assert repaired.objects[0].room_key == "meadow"
    assert repaired.characters[0].room_key == "burrow"
    assert [exit_.to_key for exit_ in repaired.exits] == ["burrow"]
    assert "repaired live world proposal references" not in caplog.text


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


async def test_instantiate_builds_water_container_and_writable_paper_objects():
    from bunnyland.foundation.needs.mechanics import HungerComponent, ThirstComponent

    actor = WorldActor()
    proposal = WorldProposal(
        seed="objects",
        rooms=[RoomSpec(key="room", title="Room")],
        objects=[
            ObjectSpec(
                key="water",
                room_key="room",
                name="canteen",
                kind="water",
                hydration=2.0,
                renewable=False,
            ),
            ObjectSpec(
                key="box",
                room_key="room",
                name="box",
                kind="container",
                open=False,
            ),
            ObjectSpec(
                key="paper",
                room_key="room",
                name="paper",
                kind="paper",
                writable=True,
            ),
        ],
        characters=[
            CharacterSpec(
                key="minimal",
                name="Minimal",
                room_key="room",
                traits=("bunny", "calm"),
                with_needs=False,
                with_memory=False,
            )
        ],
    )

    result = await instantiate(actor, proposal)

    water = actor.world.get_entity(result.objects["water"])
    box = actor.world.get_entity(result.objects["box"])
    paper = actor.world.get_entity(result.objects["paper"])
    assert water.get_component(DrinkableComponent).hydration == 2.0
    assert water.has_component(ConsumableComponent)
    assert box.get_component(ContainerComponent).open is False
    assert paper.has_component(ReadableComponent)
    assert paper.has_component(WritableComponent)
    minimal = actor.world.get_entity(result.characters["minimal"])
    assert not minimal.has_component(HungerComponent)
    assert not minimal.has_component(ThirstComponent)
    assert not minimal.has_component(MemoryProfileComponent)
    assert minimal.get_component(GenerationIntentComponent).tags == ("bunny", "calm")


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
        edge.direction: (edge, target) for edge, target in tower_room.get_relationships(ExitTo)
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

    proposal = await StubWorldBuilder().propose("a quiet marsh")
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
    assert rooms[0].generation.description == "a flooded cellar, signs of recent struggle"
    assert rooms[0].generation.tags == ("cellar", "indoor", "wet")
    assert rooms[0].generation.wants == ("humidity",)
    assert (
        actor.world.get_entity(result.rooms["cellar"]).get_component(GenerationIntentComponent)
        == rooms[0].generation
    )

    assert [event.object_key for event in objects] == ["crate"]
    assert objects[0].entity_id == str(result.objects["crate"])
    assert objects[0].room_id == str(result.rooms["cellar"])
    assert objects[0].container_id == str(result.rooms["cellar"])
    assert objects[0].generation.description == "waterlogged supplies"
    assert objects[0].generation.tags == ("container", "salvage")
    assert objects[0].generation.wants == ("loot-table",)

    assert [event.character_key for event in characters] == ["scout"]
    assert characters[0].entity_id == str(result.characters["scout"])
    assert characters[0].room_id == str(result.rooms["cellar"])
    assert characters[0].generation.description == "a worried scout checking the flood"
    assert characters[0].generation.tags == ("hare", "watchful", "local")
    assert characters[0].generation.wants == ("faction-allegiance",)


async def test_plugin_generation_enricher_can_add_owned_components():
    @dataclass(frozen=True)
    class HumidityComponent(Component):
        level: str = "damp"

    class HumidityEnricher:
        capabilities = ("humidity.room",)

        def enrich(self, request):
            return GenerationDelta(
                components=(HumidityComponent(),),
                satisfies=("humidity.room",),
            )

    actor = WorldActor()
    apply_plugins(
        [
            Plugin(
                id="humidity",
                name="Humidity",
                ecs=EcsContribution(components=(HumidityComponent,)),
                content=ContentContribution(
                    generation_capabilities=("humidity.room",),
                    generation_enrichers=(HumidityEnricher(),),
                ),
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
                wants=("humidity.room",),
            )
        ],
    )

    result = await instantiate(actor, proposal)

    room = actor.world.get_entity(result.rooms["room"])
    assert room.get_component(HumidityComponent).level == "damp"


async def test_generation_children_are_compiled_linked_and_published_after_creation():
    @dataclass(frozen=True)
    class ChildMarkerComponent(Component):
        label: str = "mailbox"

    class ChildEnricher:
        capabilities = ()

        def enrich(self, request):
            if request.entity_kind == "room":
                return GenerationDelta(
                    children=(
                        GenerationChild(
                            request=GenerationRequest(
                                entity_kind="object",
                                description="mailbox",
                                source_seed=request.source_seed,
                                source_key=f"{request.source_key}:mailbox",
                                tags=("child-marker",),
                            ),
                            parent_edge=Contains(mode=ContainmentMode.ROOM_CONTENT),
                        ),
                    )
                )
            if "child-marker" in request.tags:
                return GenerationDelta(components=(ChildMarkerComponent(),))
            return GenerationDelta()

    actor = WorldActor()
    apply_plugins(
        [
            Plugin(
                id="children",
                name="Children",
                ecs=EcsContribution(components=(ChildMarkerComponent,)),
                content=ContentContribution(generation_enrichers=(ChildEnricher(),)),
            )
        ],
        actor,
    )
    published = []
    actor.bus.subscribe(ObjectGeneratedEvent, published.append)

    result = await instantiate(
        actor,
        WorldProposal(seed="stable", rooms=[RoomSpec(key="room", title="Room")]),
    )

    room = actor.world.get_entity(result.rooms["room"])
    children = [
        actor.world.get_entity(target) for _edge, target in room.get_relationships(Contains)
    ]
    assert len(children) == 1
    assert children[0].get_component(ChildMarkerComponent).label == "mailbox"
    assert published[0].entity_id == str(children[0].id)
    assert published[0].entity_key == "room:mailbox"


async def test_generation_singleton_child_is_shared_and_linked_to_each_parent():
    @dataclass(frozen=True)
    class SingletonLink(Edge):
        pass

    class SingletonChildEnricher:
        capabilities = ()

        def enrich(self, request):
            if request.entity_kind != "room":
                return GenerationDelta()
            return GenerationDelta(
                children=(
                    GenerationChild(
                        request=GenerationRequest(
                            entity_kind="region",
                            description="Shared Region",
                            source_seed=request.source_seed,
                            source_key="shared-region",
                        ),
                        parent_edge=Contains(mode=ContainmentMode.REGION),
                        additional_parent_edges=(SingletonLink(),),
                        singleton_key="shared-region",
                    ),
                )
            )

    actor = WorldActor()
    apply_plugins(
        [
            Plugin(
                id="singleton-children",
                name="Singleton Children",
                ecs=EcsContribution(edges=(SingletonLink,)),
                content=ContentContribution(generation_enrichers=(SingletonChildEnricher(),)),
            )
        ],
        actor,
    )
    result = await instantiate(
        actor,
        WorldProposal(
            seed="stable",
            rooms=[
                RoomSpec(key="one", title="One"),
                RoomSpec(key="two", title="Two"),
            ],
        ),
    )

    one = actor.world.get_entity(result.rooms["one"])
    two = actor.world.get_entity(result.rooms["two"])
    assert one.get_relationships(Contains)[0][1] == two.get_relationships(Contains)[0][1]
    assert one.get_relationships(SingletonLink)[0][1] == two.get_relationships(SingletonLink)[0][1]


async def test_generation_children_cover_room_character_portable_and_nested_plans():
    @dataclass(frozen=True)
    class ChildMarker(Component):
        value: str = "child"

    @dataclass(frozen=True)
    class ChildLink(Edge):
        label: str = "linked"

    class MixedChildrenEnricher:
        capabilities = ()

        def enrich(self, request):
            if request.entity_kind == "room" and request.parent_request_id is None:
                return GenerationDelta(
                    children=(
                        GenerationChild(
                            request=GenerationRequest(
                                entity_kind="room",
                                description="Side Room",
                                source_seed=request.source_seed,
                                source_key="side-room",
                                context={"biome": "cave", "indoor": True},
                            ),
                            parent_edge=Contains(mode=ContainmentMode.REGION),
                        ),
                        GenerationChild(
                            request=GenerationRequest(
                                entity_kind="character",
                                description="Guide",
                                source_seed=request.source_seed,
                                source_key="guide",
                                context={"species": "bunny"},
                            ),
                            parent_edge=Contains(mode=ContainmentMode.ROOM_CONTENT),
                            additional_parent_edges=(ChildLink(),),
                        ),
                        GenerationChild(
                            request=GenerationRequest(
                                entity_kind="item",
                                source_seed=request.source_seed,
                                source_key="portable-child",
                                context={"portable": True},
                            ),
                            parent_edge=Contains(mode=ContainmentMode.ROOM_CONTENT),
                            components=(ChildMarker(),),
                        ),
                    )
                )
            return GenerationDelta()

    actor = WorldActor()
    apply_plugins(
        [
            Plugin(
                id="mixed-children",
                name="Mixed Children",
                ecs=EcsContribution(components=(ChildMarker,), edges=(ChildLink,)),
                content=ContentContribution(generation_enrichers=(MixedChildrenEnricher(),)),
            )
        ],
        actor,
    )
    events = []
    actor.bus.subscribe(RoomGeneratedEvent, events.append)
    actor.bus.subscribe(CharacterGeneratedEvent, events.append)
    result = await instantiate(
        actor,
        WorldProposal(seed="mixed", rooms=[RoomSpec(key="root", title="Root")]),
    )

    root = actor.world.get_entity(result.rooms["root"])
    region_child = actor.world.get_entity(root.get_relationships(Contains)[0][1])
    assert region_child.get_component(RoomComponent).indoor
    character_id = root.get_relationships(ChildLink)[0][1]
    character = actor.world.get_entity(character_id)
    assert character.has_component(CharacterComponent)
    assert character.has_component(SuspendedComponent)
    assert character.get_relationships(ControlledBy)
    portable = next(
        actor.world.get_entity(target)
        for _edge, target in root.get_relationships(Contains)
        if actor.world.get_entity(target).has_component(ChildMarker)
    )
    assert portable.has_component(PortableComponent)
    assert {event.entity_key for event in events} >= {"side-room", "guide"}


async def test_generation_rejects_recursive_child_request_identity():
    class RecursiveChildEnricher:
        capabilities = ()

        def enrich(self, request):
            if request.parent_request_id is not None:
                return GenerationDelta()
            return GenerationDelta(
                children=(
                    GenerationChild(
                        request=GenerationRequest(
                            entity_kind="item",
                            request_id=request.request_id,
                            source_key="recursive",
                        ),
                        parent_edge=Contains(),
                    ),
                )
            )

    actor = WorldActor()
    apply_plugins(
        [
            Plugin(
                id="recursive-child",
                name="Recursive Child",
                content=ContentContribution(generation_enrichers=(RecursiveChildEnricher(),)),
            )
        ],
        actor,
    )
    with pytest.raises(GenerationError, match="recursive generation child request"):
        await instantiate(
            actor,
            WorldProposal(seed="loop", rooms=[RoomSpec(key="root", title="Root")]),
        )


async def test_builtin_generation_enrichers_enrich_from_generation_intent():
    from bunnyland.foundation.environment.mechanics import FlammableComponent
    from bunnyland.simpacks.barbariansim.mechanics import StaminaComponent, WeaponComponent
    from bunnyland.simpacks.colonysim.mechanics import (
        BodyPartHealthComponent,
        ColonyIncidentComponent,
        JobBillComponent,
        JobComponent,
        PawnProfileComponent,
        PrisonerComponent,
        ResearchProjectComponent,
        ResourceNodeComponent,
        StockpileComponent,
        SurgeryBillComponent,
        TradeOfferComponent,
    )
    from bunnyland.simpacks.daggersim.mechanics import DungeonComponent
    from bunnyland.simpacks.dinosim.mechanics import DinosaurComponent, EnclosureComponent
    from bunnyland.simpacks.dragonsim.mechanics import PointOfInterestComponent
    from bunnyland.simpacks.gardensim.mechanics import (
        CropQualityComponent,
        FarmQuestComponent,
        GeodeComponent,
        GreenhouseComponent,
        LadderComponent,
        MachineComponent,
        MailComponent,
        MineLevelComponent,
        PestComponent,
        RegrowableComponent,
        SeedComponent,
        ShippingBinComponent,
        SoilComponent,
        WeedComponent,
    )
    from bunnyland.simpacks.lifesim.mechanics import (
        CharacterProfileComponent,
        HomeObjectComponent,
        WhimComponent,
    )
    from bunnyland.simpacks.nukesim.mechanics import (
        MutationThresholdComponent,
        RadiationSourceComponent,
    )
    from bunnyland.simpacks.voidsim.mechanics import (
        HabitatModuleComponent,
        ShipComponent,
        ShipSystemComponent,
    )

    actor = WorldActor()
    apply_plugins(bunnyland_plugins(), actor)
    proposal = WorldProposal(
        seed="enriched",
        rooms=[
            RoomSpec(
                key="garden_ship",
                title="Greenhouse Ship",
                biome="greenhouse",
                indoor=True,
                generation=GenerationIntentComponent(
                    description="a greenhouse ship with a small dinosaur pen",
                    tags=("ship",),
                    wants=(
                        "bunnyland.gardensim.soil",
                        "bunnyland.gardensim.greenhouse",
                        "bunnyland.colonysim.stockpile",
                        "bunnyland.voidsim.ship",
                        "bunnyland.dragonsim.point-of-interest",
                        "bunnyland.daggersim.dungeon",
                        "bunnyland.dinosim.enclosure",
                        "bunnyland.gardensim.mine-level",
                        "bunnyland.nukesim.radiation-source",
                    ),
                    needs=("bunnyland.environment.flammable",),
                ),
            )
        ],
        objects=[
            ObjectSpec(
                key="ore",
                room_key="garden_ship",
                name="a metal ore vein",
                kind="resource",
                wants=("bunnyland.colonysim.resource-node",),
            ),
            ObjectSpec(
                key="seeds",
                room_key="garden_ship",
                name="turnip seeds",
                kind="seed",
                wants=("bunnyland.gardensim.seed",),
            ),
            ObjectSpec(
                key="default_seed",
                room_key="garden_ship",
                name="mystery packet",
                kind="seed",
                wants=("bunnyland.gardensim.seed",),
            ),
            ObjectSpec(
                key="blade",
                room_key="garden_ship",
                name="a survival sword",
                kind="weapon",
                wants=("bunnyland.barbariansim.weapon",),
            ),
            ObjectSpec(
                key="drive",
                room_key="garden_ship",
                name="a damaged drive core",
                kind="drive",
                wants=("bunnyland.voidsim.ship-system",),
            ),
            ObjectSpec(
                key="chair",
                room_key="garden_ship",
                name="a cozy home chair",
                kind="furniture",
                wants=("bunnyland.lifesim.home-object", "bunnyland.lifesim.whim"),
            ),
            ObjectSpec(
                key="work_order",
                room_key="garden_ship",
                name="a work order bill",
                kind="job",
                wants=("bunnyland.colonysim.job-bill",),
            ),
            ObjectSpec(
                key="stockpile_job",
                room_key="garden_ship",
                name="a generated assignment marker",
                kind="marker",
                wants=("bunnyland.colonysim.stockpile", "bunnyland.colonysim.job"),
            ),
            ObjectSpec(
                key="research",
                room_key="garden_ship",
                name="hydroponic research notes",
                kind="research",
                wants=("bunnyland.colonysim.research",),
            ),
            ObjectSpec(
                key="incident",
                room_key="garden_ship",
                name="minor blight incident",
                kind="incident",
                wants=("bunnyland.colonysim.incident",),
            ),
            ObjectSpec(
                key="trade",
                room_key="garden_ship",
                name="a trader's offer",
                kind="trade",
                wants=("bunnyland.colonysim.trade-offer",),
            ),
            ObjectSpec(
                key="surgery",
                room_key="garden_ship",
                name="a limb surgery order",
                kind="surgery",
                wants=("bunnyland.colonysim.surgery", "bunnyland.colonysim.body-part"),
            ),
            ObjectSpec(
                key="crop",
                room_key="garden_ship",
                name="a perennial crop",
                kind="crop",
                wants=(
                    "bunnyland.gardensim.crop-quality",
                    "bunnyland.gardensim.regrowable",
                    "bunnyland.gardensim.pest",
                    "bunnyland.gardensim.weed",
                ),
            ),
            ObjectSpec(
                key="machine",
                room_key="garden_ship",
                name="a preserves machine",
                kind="machine",
                wants=("bunnyland.gardensim.machine",),
            ),
            ObjectSpec(
                key="shipping",
                room_key="garden_ship",
                name="a shipping crate",
                kind="shipping-bin",
                wants=("bunnyland.gardensim.shipping-bin",),
            ),
            ObjectSpec(
                key="geode",
                room_key="garden_ship",
                name="a metal geode",
                kind="geode",
                wants=("bunnyland.gardensim.geode",),
            ),
            ObjectSpec(
                key="ladder",
                room_key="garden_ship",
                name="a ladder down",
                kind="ladder",
                wants=("bunnyland.gardensim.ladder",),
            ),
            ObjectSpec(
                key="mail",
                room_key="garden_ship",
                name="a welcome letter",
                kind="mail",
                wants=("bunnyland.gardensim.mail",),
            ),
            ObjectSpec(
                key="quest",
                room_key="garden_ship",
                name="an order board quest",
                kind="quest",
                wants=("bunnyland.gardensim.farm-quest",),
            ),
        ],
        characters=[
            CharacterSpec(
                key="raptor",
                name="Clever",
                room_key="garden_ship",
                species="raptor",
                wants=(
                    "bunnyland.lifesim.profile",
                    "bunnyland.colonysim.pawn-profile",
                    "bunnyland.colonysim.prisoner",
                    "bunnyland.dinosim.dinosaur",
                    "bunnyland.barbariansim.stamina",
                    "bunnyland.nukesim.mutation-threshold",
                    "bunnyland.dragonsim.faction-reputation",
                ),
            )
        ],
    )

    result = await instantiate(actor, proposal)

    room = actor.world.get_entity(result.rooms["garden_ship"])
    assert room.has_component(SoilComponent)
    assert room.has_component(GreenhouseComponent)
    assert room.has_component(MineLevelComponent)
    assert room.has_component(StockpileComponent)
    assert room.has_component(ShipComponent)
    assert room.has_component(HabitatModuleComponent)
    assert room.has_component(PointOfInterestComponent)
    assert room.has_component(DungeonComponent)
    assert room.has_component(EnclosureComponent)
    assert room.has_component(RadiationSourceComponent)
    assert room.has_component(FlammableComponent)

    assert actor.world.get_entity(result.objects["ore"]).has_component(ResourceNodeComponent)
    assert actor.world.get_entity(result.objects["seeds"]).has_component(SeedComponent)
    assert (
        actor.world.get_entity(result.objects["default_seed"])
        .get_component(SeedComponent)
        .crop_type
        == "packet"
    )
    assert actor.world.get_entity(result.objects["blade"]).has_component(WeaponComponent)
    assert actor.world.get_entity(result.objects["drive"]).has_component(ShipSystemComponent)
    assert actor.world.get_entity(result.objects["chair"]).has_component(HomeObjectComponent)
    assert actor.world.get_entity(result.objects["chair"]).has_component(WhimComponent)
    assert actor.world.get_entity(result.objects["work_order"]).has_component(JobBillComponent)
    assert actor.world.get_entity(result.objects["stockpile_job"]).has_component(StockpileComponent)
    assert actor.world.get_entity(result.objects["stockpile_job"]).has_component(JobComponent)
    assert actor.world.get_entity(result.objects["research"]).has_component(
        ResearchProjectComponent
    )
    assert actor.world.get_entity(result.objects["incident"]).has_component(ColonyIncidentComponent)
    assert actor.world.get_entity(result.objects["trade"]).has_component(TradeOfferComponent)
    assert actor.world.get_entity(result.objects["surgery"]).has_component(SurgeryBillComponent)
    assert actor.world.get_entity(result.objects["surgery"]).has_component(BodyPartHealthComponent)
    assert actor.world.get_entity(result.objects["crop"]).has_component(CropQualityComponent)
    assert actor.world.get_entity(result.objects["crop"]).has_component(RegrowableComponent)
    assert actor.world.get_entity(result.objects["crop"]).has_component(PestComponent)
    assert actor.world.get_entity(result.objects["crop"]).has_component(WeedComponent)
    assert actor.world.get_entity(result.objects["machine"]).has_component(MachineComponent)
    assert actor.world.get_entity(result.objects["shipping"]).has_component(ShippingBinComponent)
    assert actor.world.get_entity(result.objects["geode"]).has_component(GeodeComponent)
    assert actor.world.get_entity(result.objects["ladder"]).has_component(LadderComponent)
    assert actor.world.get_entity(result.objects["mail"]).has_component(MailComponent)
    assert actor.world.get_entity(result.objects["quest"]).has_component(FarmQuestComponent)

    raptor = actor.world.get_entity(result.characters["raptor"])
    assert raptor.has_component(CharacterProfileComponent)
    assert raptor.has_component(PawnProfileComponent)
    assert raptor.has_component(PrisonerComponent)
    assert raptor.has_component(DinosaurComponent)
    assert raptor.has_component(StaminaComponent)
    assert raptor.has_component(MutationThresholdComponent)


async def test_builtin_generation_enrichers_enrich_from_descriptive_mentions():
    from bunnyland.simpacks.colonysim.mechanics import (
        ColonyIncidentComponent,
        JobBillComponent,
        PawnProfileComponent,
        PrisonerComponent,
        ResearchProjectComponent,
        ResourceStackComponent,
        StockpileComponent,
        SurgeryBillComponent,
        TradeOfferComponent,
        WorkstationComponent,
    )
    from bunnyland.simpacks.gardensim.mechanics import (
        CropQualityComponent,
        FarmQuestComponent,
        FertilizerComponent,
        GeodeComponent,
        LadderComponent,
        MachineComponent,
        MailComponent,
        MineLevelComponent,
        PestComponent,
        RegrowableComponent,
        ShippingBinComponent,
        TreeComponent,
        WeedComponent,
    )
    from bunnyland.simpacks.lifesim.mechanics import (
        CharacterProfileComponent,
        HomeObjectComponent,
        WhimComponent,
    )

    actor = WorldActor()
    apply_plugins(bunnyland_plugins(), actor)
    proposal = WorldProposal(
        seed="mentions",
        rooms=[
            RoomSpec(
                key="room",
                title="Farm Warehouse Cavern",
                description="a greenhouse farm warehouse cavern",
            )
        ],
        objects=[
            ObjectSpec(
                key="wish_chair",
                room_key="room",
                name="a wish chair for the home",
                kind="furniture",
            ),
            ObjectSpec(
                key="stack",
                room_key="room",
                name="a pile of wood",
                kind="resource",
            ),
            ObjectSpec(key="forge", room_key="room", name="a metal forge", kind="bench"),
            ObjectSpec(
                key="research",
                room_key="room",
                name="technology research notes",
                kind="paper",
            ),
            ObjectSpec(key="raid", room_key="room", name="a raid incident", kind="incident"),
            ObjectSpec(key="trade", room_key="room", name="a trader offer", kind="trade"),
            ObjectSpec(
                key="surgery",
                room_key="room",
                name="a limb operation work order",
                kind="surgery",
            ),
            ObjectSpec(key="compost", room_key="room", name="a bag of compost", kind="item"),
            ObjectSpec(key="tree", room_key="room", name="a young tree", kind="tree"),
            ObjectSpec(
                key="crop",
                room_key="room",
                name="a perennial crop with pest bugs and weeds",
                kind="crop",
            ),
            ObjectSpec(key="keg", room_key="room", name="a keg machine", kind="machine"),
            ObjectSpec(
                key="shipping",
                room_key="room",
                name="a shipping bin",
                kind="shipping",
            ),
            ObjectSpec(key="geode", room_key="room", name="a stone geode", kind="geode"),
            ObjectSpec(key="ladder", room_key="room", name="a mine ladder", kind="ladder"),
            ObjectSpec(key="mail", room_key="room", name="a letter in the mail", kind="mail"),
            ObjectSpec(
                key="quest",
                room_key="room",
                name="an order board quest",
                kind="quest",
            ),
        ],
        characters=[
            CharacterSpec(
                key="pawn",
                name="Morgan",
                room_key="room",
                description="a captive worker with a backstory and routine",
                traits=("crafting",),
            )
        ],
    )

    result = await instantiate(actor, proposal)

    room = actor.world.get_entity(result.rooms["room"])
    assert room.has_component(StockpileComponent)
    assert room.has_component(MineLevelComponent)
    pawn = actor.world.get_entity(result.characters["pawn"])
    assert pawn.has_component(CharacterProfileComponent)
    assert pawn.has_component(PawnProfileComponent)
    assert pawn.has_component(PrisonerComponent)
    assert actor.world.get_entity(result.objects["wish_chair"]).has_component(HomeObjectComponent)
    assert actor.world.get_entity(result.objects["wish_chair"]).has_component(WhimComponent)
    assert actor.world.get_entity(result.objects["stack"]).has_component(ResourceStackComponent)
    assert actor.world.get_entity(result.objects["forge"]).has_component(WorkstationComponent)
    assert actor.world.get_entity(result.objects["research"]).has_component(
        ResearchProjectComponent
    )
    assert actor.world.get_entity(result.objects["raid"]).has_component(ColonyIncidentComponent)
    assert actor.world.get_entity(result.objects["trade"]).has_component(TradeOfferComponent)
    assert actor.world.get_entity(result.objects["surgery"]).has_component(SurgeryBillComponent)
    assert actor.world.get_entity(result.objects["surgery"]).has_component(JobBillComponent)
    assert actor.world.get_entity(result.objects["compost"]).has_component(FertilizerComponent)
    assert actor.world.get_entity(result.objects["tree"]).has_component(TreeComponent)
    crop = actor.world.get_entity(result.objects["crop"])
    assert crop.has_component(CropQualityComponent)
    assert crop.has_component(RegrowableComponent)
    assert crop.has_component(PestComponent)
    assert crop.has_component(WeedComponent)
    assert actor.world.get_entity(result.objects["keg"]).has_component(MachineComponent)
    assert actor.world.get_entity(result.objects["shipping"]).has_component(ShippingBinComponent)
    assert actor.world.get_entity(result.objects["geode"]).has_component(GeodeComponent)
    assert actor.world.get_entity(result.objects["ladder"]).has_component(LadderComponent)
    assert actor.world.get_entity(result.objects["mail"]).has_component(MailComponent)
    assert actor.world.get_entity(result.objects["quest"]).has_component(FarmQuestComponent)


async def test_builtin_generation_enrichers_cover_core_sim_pack_wants():
    from bunnyland.simpacks.colonysim.mechanics import (
        AllowedIn,
        BedRestComponent,
        CaravanComponent,
        ColonyWealthComponent,
        FactionRelationComponent,
        ForbiddenComponent,
        HaulableComponent,
        InfectionComponent,
        MedicalBedComponent,
        MedicineComponent,
        MentalStateComponent,
        ProstheticComponent,
        RecipeComponent,
        RoomQualityComponent,
        RoomRoleComponent,
        RoomStatComponent,
        StorageFilterComponent,
        TechUnlockComponent,
        WorkCapabilityComponent,
        WorkPriorityComponent,
    )
    from bunnyland.simpacks.gardensim.mechanics import (
        AnimalBreedingComponent,
        AnimalHomeComponent,
        AnimalProductComponent,
        BundleComponent,
        CollectionComponent,
        CropComponent,
        CropGrowthComponent,
        CropInspectionComponent,
        DailyFarmResetComponent,
        FarmAnimalComponent,
        FestivalComponent,
        FishingSpotComponent,
        ForageComponent,
        FriendshipComponent,
        GiftPreferenceComponent,
        HarvestableComponent,
        MachineBreakdownComponent,
        MiningNodeComponent,
        MuseumCollectionComponent,
        ProcessingRecipeComponent,
        RewardComponent,
        TilledComponent,
        TreeTapComponent,
        WateredComponent,
    )
    from bunnyland.simpacks.lifesim.mechanics import (
        AspirationComponent,
        BillComponent,
        BusinessOwnerComponent,
        CareerComponent,
        CustomerComponent,
        HomeComponent,
        HouseholdComponent,
        JobScheduleComponent,
        ReproductiveComponent,
        ReputationComponent,
        RoomClaimComponent,
        RoutineComponent,
        SkillSetComponent,
    )

    actor = WorldActor()
    apply_plugins(bunnyland_plugins(), actor)
    proposal = WorldProposal(
        seed="core-pack-wants",
        rooms=[
            RoomSpec(
                key="life_home",
                title="Generated Apartment",
                description="a claimed home apartment",
                wants=(
                    "bunnyland.lifesim.home",
                    "bunnyland.lifesim.room-claim",
                    "bunnyland.gardensim.daily-farm-reset",
                ),
            ),
            RoomSpec(
                key="colony_core",
                title="Clinic Barracks",
                biome="clinic",
                description="a beautiful clean comfortable impressive colony wealth room",
                wants=(
                    "bunnyland.colonysim.room-role",
                    "bunnyland.colonysim.room-stat",
                    "bunnyland.colonysim.room-quality",
                    "bunnyland.colonysim.colony-wealth",
                ),
            ),
        ],
        objects=[
            ObjectSpec(
                key="life_shop",
                room_key="life_home",
                name="corner stall bill",
                kind="shop",
                wants=("bunnyland.lifesim.bill", "bunnyland.lifesim.business-owner"),
            ),
            ObjectSpec(
                key="garden_plot",
                room_key="life_home",
                name="turnip planted crop with tapped tree",
                kind="crop",
                wants=(
                    "bunnyland.gardensim.tilled",
                    "bunnyland.gardensim.watered",
                    "bunnyland.gardensim.crop",
                    "bunnyland.gardensim.crop-growth",
                    "bunnyland.gardensim.harvestable",
                    "bunnyland.gardensim.crop-inspection",
                    "bunnyland.gardensim.tree-tap",
                ),
            ),
            ObjectSpec(
                key="garden_animal",
                room_key="life_home",
                name="chicken coop animal product",
                kind="animal",
                wants=(
                    "bunnyland.gardensim.animal-home",
                    "bunnyland.gardensim.farm-animal",
                    "bunnyland.gardensim.animal-product",
                    "bunnyland.gardensim.animal-breeding",
                ),
            ),
            ObjectSpec(
                key="garden_board",
                room_key="life_home",
                name="spring trout pond ore node festival bundle museum reward",
                kind="garden-marker",
                wants=(
                    "bunnyland.gardensim.fishing-spot",
                    "bunnyland.gardensim.mining-node",
                    "bunnyland.gardensim.forage",
                    "bunnyland.gardensim.festival",
                    "bunnyland.gardensim.bundle",
                    "bunnyland.gardensim.collection",
                    "bunnyland.gardensim.museum-collection",
                    "bunnyland.gardensim.reward",
                    "bunnyland.gardensim.machine-breakdown",
                    "bunnyland.gardensim.processing-recipe",
                ),
            ),
            ObjectSpec(
                key="colony_cache",
                room_key="colony_core",
                name="medicine caravan prosthetic recipe cache",
                kind="colony-cache",
                wants=(
                    "bunnyland.colonysim.storage-filter",
                    "bunnyland.colonysim.haulable",
                    "bunnyland.colonysim.forbidden",
                    "bunnyland.colonysim.recipe",
                    "bunnyland.colonysim.tech-unlock",
                    "bunnyland.colonysim.faction-relation",
                    "bunnyland.colonysim.caravan",
                    "bunnyland.colonysim.medicine",
                    "bunnyland.colonysim.medical-bed",
                    "bunnyland.colonysim.prosthetic",
                ),
            ),
        ],
        characters=[
            CharacterSpec(
                key="resident",
                name="Resident",
                room_key="life_home",
                species="bunny",
                description="a skilled friend with an aspiration career household and routine",
                traits=("gardening",),
                wants=(
                    "bunnyland.lifesim.aspiration",
                    "bunnyland.lifesim.career",
                    "bunnyland.lifesim.job-schedule",
                    "bunnyland.lifesim.customer",
                    "bunnyland.lifesim.household",
                    "bunnyland.lifesim.routine",
                    "bunnyland.lifesim.reputation",
                    "bunnyland.lifesim.skill-set",
                    "bunnyland.lifesim.reproductive",
                    "bunnyland.gardensim.gift-preference",
                    "bunnyland.gardensim.friendship",
                    "bunnyland.gardensim.collection",
                    "bunnyland.colonysim.work-priority",
                    "bunnyland.colonysim.work-capability",
                    "bunnyland.colonysim.allowed-area",
                    "bunnyland.colonysim.bed-rest",
                    "bunnyland.colonysim.infection",
                    "bunnyland.colonysim.mental-state",
                ),
            )
        ],
    )

    result = await instantiate(actor, proposal)

    life_home = actor.world.get_entity(result.rooms["life_home"])
    assert life_home.has_component(HomeComponent)
    assert life_home.has_component(RoomClaimComponent)
    assert life_home.has_component(DailyFarmResetComponent)

    resident = actor.world.get_entity(result.characters["resident"])
    for component_type in (
        AspirationComponent,
        CareerComponent,
        JobScheduleComponent,
        CustomerComponent,
        HouseholdComponent,
        RoutineComponent,
        ReputationComponent,
        SkillSetComponent,
        ReproductiveComponent,
        GiftPreferenceComponent,
        FriendshipComponent,
        CollectionComponent,
        WorkPriorityComponent,
        WorkCapabilityComponent,
        BedRestComponent,
        InfectionComponent,
        MentalStateComponent,
    ):
        assert resident.has_component(component_type)
    assert resident.get_relationships(AllowedIn) == [(AllowedIn(), life_home.id)]
    assert resident.get_component(ReproductiveComponent).species_group == "bunny"

    life_shop = actor.world.get_entity(result.objects["life_shop"])
    assert life_shop.has_component(BillComponent)
    assert life_shop.has_component(BusinessOwnerComponent)

    garden_plot = actor.world.get_entity(result.objects["garden_plot"])
    for component_type in (
        TilledComponent,
        WateredComponent,
        CropComponent,
        CropGrowthComponent,
        HarvestableComponent,
        CropInspectionComponent,
        TreeTapComponent,
    ):
        assert garden_plot.has_component(component_type)

    garden_animal = actor.world.get_entity(result.objects["garden_animal"])
    for component_type in (
        AnimalHomeComponent,
        FarmAnimalComponent,
        AnimalProductComponent,
        AnimalBreedingComponent,
    ):
        assert garden_animal.has_component(component_type)
    assert garden_animal.get_component(FarmAnimalComponent).species == "chicken"

    garden_board = actor.world.get_entity(result.objects["garden_board"])
    for component_type in (
        FishingSpotComponent,
        MiningNodeComponent,
        ForageComponent,
        FestivalComponent,
        BundleComponent,
        CollectionComponent,
        MuseumCollectionComponent,
        RewardComponent,
        MachineBreakdownComponent,
        ProcessingRecipeComponent,
    ):
        assert garden_board.has_component(component_type)
    assert garden_board.get_component(FishingSpotComponent).fish_type == "trout"

    colony_core = actor.world.get_entity(result.rooms["colony_core"])
    for component_type in (
        RoomRoleComponent,
        RoomStatComponent,
        RoomQualityComponent,
        ColonyWealthComponent,
    ):
        assert colony_core.has_component(component_type)
    assert colony_core.get_component(RoomRoleComponent).role == "clinic"

    colony_cache = actor.world.get_entity(result.objects["colony_cache"])
    for component_type in (
        StorageFilterComponent,
        HaulableComponent,
        ForbiddenComponent,
        RecipeComponent,
        TechUnlockComponent,
        FactionRelationComponent,
        CaravanComponent,
        MedicineComponent,
        MedicalBedComponent,
        ProstheticComponent,
    ):
        assert colony_cache.has_component(component_type)


async def test_builtin_generation_enrichers_cover_tier_2_sim_pack_wants():
    from bunnyland.simpacks.barbariansim.mechanics import (
        ArmorComponent,
        BaseClaimComponent,
        BlessingComponent,
        BossComponent,
        BuildingComponent,
        ClimbingGateComponent,
        ClimbingSkillComponent,
        CorruptionComponent,
        CurseComponent,
        DangerZoneComponent,
        DurabilityComponent,
        FortificationComponent,
        KeyComponent,
        PoisonComponent,
        PurgeWaveComponent,
        RitualComponent,
        ShelterComponent,
        ShrineComponent,
        SiegeReadinessComponent,
        StaminaComponent,
        SurvivalGapComponent,
        TemperatureExposureComponent,
        TemperatureResistanceComponent,
        TrapComponent,
        TreasureComponent,
        WeaponComponent,
    )
    from bunnyland.simpacks.daggersim.mechanics import (
        AfflictionStigmaComponent,
        AutomapComponent,
        BankComponent,
        BountyComponent,
        CampingComponent,
        ClassTemplateComponent,
        ConversationToneComponent,
        CreatureLanguageComponent,
        CureRequestComponent,
        CustomClassComponent,
        CustomSpellComponent,
        DialogueApproachComponent,
        DungeonObjectiveComponent,
        EnchantedItemComponent,
        EtiquetteSkillComponent,
        FeedingNeedComponent,
        HasLegalStandingInRegion,
        HasStandingInRegion,
        HasStandingWithInstitution,
        HostilityComponent,
        IngredientComponent,
        InstitutionComponent,
        InstitutionDuesComponent,
        InstitutionServiceComponent,
        LanguageSkillComponent,
        LawRegionComponent,
        LodgingComponent,
        OriginatesFromSource,
        PotionMakerComponent,
        ProceduralSiteComponent,
        PropertyDeedComponent,
        RecallAnchorComponent,
        RechargeServiceComponent,
        RefersToSubject,
        RestRiskComponent,
        RumorComponent,
        RumorReliabilityComponent,
        SecretDoorComponent,
        SocialRegisterComponent,
        SpellTemplateComponent,
        StreetwiseSkillComponent,
        SupernaturalAfflictionComponent,
        TravelHubComponent,
        TravelInterruptionComponent,
        TravelModeComponent,
        TravelSupplyComponent,
        UnrealizedLocationComponent,
    )
    from bunnyland.simpacks.dragonsim.mechanics import (
        AncientBeastComponent,
        ArtifactComponent,
        CarvableComponent,
        DiscoveryComponent,
        EncounterZoneComponent,
        FactionComponent,
        GreatSoulComponent,
        GuardComponent,
        HasStandingWithFaction,
        JailComponent,
        LockDifficultyComponent,
        LoreBookComponent,
        MagicComponent,
        MapMarkerComponent,
        PerkComponent,
        PersuasionComponent,
        PointOfInterestComponent,
        PotionComponent,
        PotionRecipeComponent,
        QuestComponent,
        QuestObjectiveComponent,
        QuestProvenanceComponent,
        QuestRewardComponent,
        QuestStateComponent,
        SneakingComponent,
        SpellComponent,
        SpellCooldownComponent,
        SurrenderComponent,
        VoiceInscriptionComponent,
        WantedByFaction,
        WordOfPowerComponent,
    )
    from bunnyland.simpacks.dragonsim.quests import QuestTemplateComponent

    actor = WorldActor()
    apply_plugins(bunnyland_plugins(), actor)
    proposal = WorldProposal(
        seed="tier-2-pack-wants",
        rooms=[
            RoomSpec(
                key="barbarian_base",
                title="Purge Camp Ruin",
                biome="ruin",
                description="a siege camp with a shortage and warlord boss",
                wants=(
                    "bunnyland.barbariansim.shelter",
                    "bunnyland.barbariansim.base-claim",
                    "bunnyland.barbariansim.survival-gap",
                    "bunnyland.barbariansim.building",
                    "bunnyland.barbariansim.siege-readiness",
                    "bunnyland.barbariansim.purge-wave",
                    "bunnyland.barbariansim.danger-zone",
                    "bunnyland.barbariansim.boss",
                ),
            ),
            RoomSpec(
                key="dagger_city",
                title="Cartographer Bank Guild",
                biome="city",
                description="an unrealized bank guild with lodging and a travel interruption",
                wants=(
                    "bunnyland.daggersim.procedural-site",
                    "bunnyland.daggersim.unrealized-location",
                    "bunnyland.daggersim.expansion-hook",
                    "bunnyland.daggersim.travel-hub",
                    "bunnyland.daggersim.travel-mode",
                    "bunnyland.daggersim.institution",
                    "bunnyland.daggersim.institution-service",
                    "bunnyland.daggersim.institution-dues",
                    "bunnyland.daggersim.bank",
                    "bunnyland.daggersim.law-region",
                    "bunnyland.daggersim.property-deed",
                    "bunnyland.daggersim.lodging",
                    "bunnyland.daggersim.camping",
                    "bunnyland.daggersim.travel-supply",
                    "bunnyland.daggersim.travel-interruption",
                    "bunnyland.daggersim.rest-risk",
                ),
            ),
            RoomSpec(
                key="dragon_ruin",
                title="Marked Faction Ruin Quest",
                biome="ruin",
                description="a landmark map marker with a lore book and word of power",
                wants=(
                    "bunnyland.dragonsim.point-of-interest",
                    "bunnyland.dragonsim.discovery",
                    "bunnyland.dragonsim.map-marker",
                    "bunnyland.dragonsim.encounter-zone",
                    "bunnyland.dragonsim.faction",
                    "bunnyland.dragonsim.quest",
                    "bunnyland.dragonsim.quest-stage",
                    "bunnyland.dragonsim.quest-objective",
                    "bunnyland.dragonsim.quest-reward",
                    "bunnyland.dragonsim.guard",
                    "bunnyland.dragonsim.jail",
                    "bunnyland.dragonsim.perk",
                    "bunnyland.dragonsim.word-of-power",
                    "bunnyland.dragonsim.lock-difficulty",
                    "bunnyland.dragonsim.lore-book",
                    "bunnyland.dragonsim.spell",
                    "bunnyland.dragonsim.potion-recipe",
                    "bunnyland.dragonsim.potion",
                    "bunnyland.dragonsim.artifact",
                    "bunnyland.dragonsim.carvable",
                    "bunnyland.dragonsim.voice-inscription",
                ),
            ),
        ],
        objects=[
            ObjectSpec(
                key="barbarian_cache",
                room_key="barbarian_base",
                name="cursed shrine treasure key axe",
                kind="cache",
                wants=(
                    "bunnyland.barbariansim.weapon",
                    "bunnyland.barbariansim.armor",
                    "bunnyland.barbariansim.durability",
                    "bunnyland.barbariansim.durable-fortification",
                    "bunnyland.barbariansim.trap",
                    "bunnyland.barbariansim.shrine",
                    "bunnyland.barbariansim.ritual",
                    "bunnyland.barbariansim.blessing",
                    "bunnyland.barbariansim.curse",
                    "bunnyland.core.key",
                    "bunnyland.barbariansim.treasure",
                    "bunnyland.barbariansim.climbing-gate",
                ),
            ),
            ObjectSpec(
                key="dagger_board",
                room_key="dagger_city",
                name="rumor quest board secret door spell service",
                kind="board",
                wants=(
                    "bunnyland.daggersim.rumor",
                    "bunnyland.daggersim.rumor-source",
                    "bunnyland.daggersim.rumor-reliability",
                    "bunnyland.daggersim.rumor-target",
                    "bunnyland.dragonsim.quest-template",
                    "bunnyland.dragonsim.generated-quest",
                    "bunnyland.dragonsim.quest-deadline",
                    "bunnyland.dragonsim.quest-reward",
                    "bunnyland.daggersim.spell-template",
                    "bunnyland.daggersim.custom-spell",
                    "bunnyland.daggersim.enchanted-item",
                    "bunnyland.daggersim.potion-maker",
                    "bunnyland.daggersim.recharge-service",
                    "bunnyland.daggersim.ingredient",
                    "bunnyland.daggersim.creature-language",
                    "bunnyland.daggersim.hostility",
                    "bunnyland.daggersim.dungeon-objective",
                    "bunnyland.daggersim.secret-door",
                    "bunnyland.daggersim.automap",
                ),
            ),
        ],
        characters=[
            CharacterSpec(
                key="barbarian_climber",
                name="Skalda",
                room_key="barbarian_base",
                species="bunny",
                description="a poisoned corrupted climber warrior",
                wants=(
                    "bunnyland.barbariansim.temperature-resistance",
                    "bunnyland.barbariansim.temperature-exposure",
                    "bunnyland.barbariansim.poison",
                    "bunnyland.barbariansim.corruption",
                    "bunnyland.barbariansim.stamina",
                    "bunnyland.barbariansim.blessing",
                    "bunnyland.barbariansim.curse",
                    "bunnyland.barbariansim.climbing-skill",
                ),
            ),
            CharacterSpec(
                key="dagger_scholar",
                name="Archivist",
                room_key="dagger_city",
                species="bunny",
                traits=("etiquette",),
                description="a streetwise court scholar with a supernatural affliction",
                wants=(
                    "bunnyland.daggersim.bounty",
                    "bunnyland.daggersim.regional-reputation",
                    "bunnyland.daggersim.institution-reputation",
                    "bunnyland.daggersim.legal-reputation",
                    "bunnyland.daggersim.service-access",
                    "bunnyland.daggersim.class-template",
                    "bunnyland.daggersim.custom-class",
                    "bunnyland.daggersim.language-skill",
                    "bunnyland.daggersim.supernatural-affliction",
                    "bunnyland.daggersim.affliction-stigma",
                    "bunnyland.daggersim.cure-request",
                    "bunnyland.daggersim.feeding-need",
                    "bunnyland.daggersim.recall-anchor",
                    "bunnyland.daggersim.dialogue-approach",
                    "bunnyland.daggersim.etiquette-skill",
                    "bunnyland.daggersim.streetwise-skill",
                    "bunnyland.daggersim.social-register",
                    "bunnyland.daggersim.conversation-tone",
                ),
            ),
            CharacterSpec(
                key="dragon_mage",
                name="Veyra",
                room_key="dragon_ruin",
                species="bunny",
                description="a stealthy ancient beast guard with magic",
                wants=(
                    "bunnyland.dragonsim.faction-reputation",
                    "bunnyland.dragonsim.guard",
                    "bunnyland.dragonsim.jail",
                    "bunnyland.dragonsim.great-soul",
                    "bunnyland.dragonsim.stealth",
                    "bunnyland.dragonsim.wanted",
                    "bunnyland.dragonsim.magic",
                    "bunnyland.dragonsim.spell-cooldown",
                    "bunnyland.dragonsim.persuasion",
                    "bunnyland.dragonsim.surrender",
                    "bunnyland.dragonsim.ancient-beast",
                ),
            ),
        ],
    )

    result = await instantiate(actor, proposal)

    barbarian_base = actor.world.get_entity(result.rooms["barbarian_base"])
    for component_type in (
        ShelterComponent,
        BaseClaimComponent,
        SurvivalGapComponent,
        BuildingComponent,
        SiegeReadinessComponent,
        PurgeWaveComponent,
        DangerZoneComponent,
        BossComponent,
    ):
        assert barbarian_base.has_component(component_type)
    assert barbarian_base.get_component(BaseClaimComponent).clan == "barbarian_base"

    barbarian_cache = actor.world.get_entity(result.objects["barbarian_cache"])
    for component_type in (
        WeaponComponent,
        ArmorComponent,
        DurabilityComponent,
        FortificationComponent,
        TrapComponent,
        ShrineComponent,
        RitualComponent,
        BlessingComponent,
        CurseComponent,
        KeyComponent,
        TreasureComponent,
        ClimbingGateComponent,
    ):
        assert barbarian_cache.has_component(component_type)

    barbarian_climber = actor.world.get_entity(result.characters["barbarian_climber"])
    for component_type in (
        TemperatureResistanceComponent,
        TemperatureExposureComponent,
        PoisonComponent,
        CorruptionComponent,
        StaminaComponent,
        BlessingComponent,
        CurseComponent,
        ClimbingSkillComponent,
    ):
        assert barbarian_climber.has_component(component_type)

    dagger_city = actor.world.get_entity(result.rooms["dagger_city"])
    for component_type in (
        ProceduralSiteComponent,
        UnrealizedLocationComponent,
        TravelHubComponent,
        TravelModeComponent,
        InstitutionComponent,
        InstitutionServiceComponent,
        InstitutionDuesComponent,
        BankComponent,
        LawRegionComponent,
        PropertyDeedComponent,
        LodgingComponent,
        CampingComponent,
        TravelSupplyComponent,
        TravelInterruptionComponent,
        RestRiskComponent,
    ):
        assert dagger_city.has_component(component_type)
    assert dagger_city.get_component(ProceduralSiteComponent).site_type == "city"

    dagger_board = actor.world.get_entity(result.objects["dagger_board"])
    for component_type in (
        RumorComponent,
        RumorReliabilityComponent,
        QuestTemplateComponent,
        QuestComponent,
        QuestStateComponent,
        QuestProvenanceComponent,
        QuestRewardComponent,
        SpellTemplateComponent,
        CustomSpellComponent,
        EnchantedItemComponent,
        PotionMakerComponent,
        RechargeServiceComponent,
        IngredientComponent,
        CreatureLanguageComponent,
        HostilityComponent,
        DungeonObjectiveComponent,
        SecretDoorComponent,
        AutomapComponent,
    ):
        assert dagger_board.has_component(component_type)
    assert dagger_board.get_relationships(OriginatesFromSource) == [
        (OriginatesFromSource(), dagger_city.id)
    ]
    assert dagger_board.get_relationships(RefersToSubject) == [(RefersToSubject(), dagger_city.id)]

    dagger_scholar = actor.world.get_entity(result.characters["dagger_scholar"])
    for component_type in (
        BountyComponent,
        ClassTemplateComponent,
        CustomClassComponent,
        LanguageSkillComponent,
        SupernaturalAfflictionComponent,
        AfflictionStigmaComponent,
        CureRequestComponent,
        FeedingNeedComponent,
        RecallAnchorComponent,
        DialogueApproachComponent,
        EtiquetteSkillComponent,
        StreetwiseSkillComponent,
        SocialRegisterComponent,
        ConversationToneComponent,
    ):
        assert dagger_scholar.has_component(component_type)
    assert dagger_scholar.get_relationships(HasStandingInRegion) == [
        (HasStandingInRegion(score=1), dagger_city.id)
    ]
    assert dagger_scholar.get_relationships(HasLegalStandingInRegion) == [
        (HasLegalStandingInRegion(), dagger_city.id)
    ]
    assert not dagger_scholar.get_relationships(HasStandingWithInstitution)

    dragon_ruin = actor.world.get_entity(result.rooms["dragon_ruin"])
    for component_type in (
        PointOfInterestComponent,
        DiscoveryComponent,
        MapMarkerComponent,
        EncounterZoneComponent,
        FactionComponent,
        QuestComponent,
        QuestStateComponent,
        QuestObjectiveComponent,
        QuestRewardComponent,
        GuardComponent,
        JailComponent,
        PerkComponent,
        WordOfPowerComponent,
        LockDifficultyComponent,
        LoreBookComponent,
        SpellComponent,
        PotionRecipeComponent,
        PotionComponent,
        ArtifactComponent,
        CarvableComponent,
        VoiceInscriptionComponent,
    ):
        assert dragon_ruin.has_component(component_type)
    assert dragon_ruin.get_component(QuestComponent).quest_id == "dragon_ruin"

    dragon_mage = actor.world.get_entity(result.characters["dragon_mage"])
    for component_type in (
        GuardComponent,
        JailComponent,
        GreatSoulComponent,
        SneakingComponent,
        MagicComponent,
        SpellCooldownComponent,
        PersuasionComponent,
        SurrenderComponent,
        AncientBeastComponent,
    ):
        assert dragon_mage.has_component(component_type)
    assert not dragon_mage.get_relationships(HasStandingWithFaction)
    assert not dragon_mage.get_relationships(WantedByFaction)


async def test_builtin_generation_enrichers_cover_cross_package_mention_branches():
    from bunnyland.foundation.environment.mechanics import FireComponent, FlammableComponent
    from bunnyland.simpacks.barbariansim.mechanics import (
        ArmorComponent,
        FortificationComponent,
        ShelterComponent,
        StaminaComponent,
    )
    from bunnyland.simpacks.daggersim.mechanics import (
        DungeonComponent,
        DungeonRoomComponent,
        InstitutionComponent,
        ProceduralSiteComponent,
        RumorComponent,
        TravelHubComponent,
    )
    from bunnyland.simpacks.dinosim.mechanics import (
        DinosaurComponent,
        EggComponent,
        FertilityComponent,
        FossilFragmentComponent,
        SpeciesComponent,
    )
    from bunnyland.simpacks.dragonsim.mechanics import (
        FactionComponent,
        PointOfInterestComponent,
        QuestComponent,
    )
    from bunnyland.simpacks.dragonsim.quests import QuestTemplateComponent
    from bunnyland.simpacks.nukesim.mechanics import (
        DecontaminationComponent,
        JunkComponent,
        LootTableComponent,
        MutationThresholdComponent,
        RadiationDoseComponent,
        RadiationSourceComponent,
        RadMedicineComponent,
        RadProtectionComponent,
        ScavengeSiteComponent,
    )
    from bunnyland.simpacks.voidsim.mechanics import (
        AirlockComponent,
        DistressSignalComponent,
        FuelComponent,
        HabitatModuleComponent,
        JumpDriveComponent,
        LifeSupportComponent,
        OxygenComponent,
        PowerGridComponent,
        PressurizedComponent,
        SensorComponent,
        ShipComponent,
        StarSystemComponent,
        StationComponent,
    )

    actor = WorldActor()
    apply_plugins(bunnyland_plugins(), actor)
    proposal = WorldProposal(
        seed="cross-package",
        rooms=[
            RoomSpec(
                key="hub",
                title="Shelter Camp Guild Vault Station",
                biome="vault",
                description=(
                    "a shelter camp guild dungeon crossroads bank ship station airlock "
                    "reactor ruin cache"
                ),
                wants=(
                    "bunnyland.daggersim.procedural-site",
                    "bunnyland.dragonsim.quest",
                    "bunnyland.voidsim.star-system",
                ),
            )
        ],
        objects=[
            ObjectSpec(
                key="firewood",
                room_key="hub",
                name="burning wood fuel",
                kind="fuel",
                wants=("bunnyland.environment.fire",),
            ),
            ObjectSpec(
                key="barricade",
                room_key="hub",
                name="armor shield barricade wall",
                kind="fortification",
            ),
            ObjectSpec(
                key="shrine",
                room_key="hub",
                name="quest shrine landmark faction guild",
                kind="shrine",
                wants=("bunnyland.dragonsim.quest",),
            ),
            ObjectSpec(
                key="rumor",
                room_key="hub",
                name="a rumor parchment",
                kind="paper",
                description="rumor of a hidden vault",
            ),
            ObjectSpec(
                key="template",
                room_key="hub",
                name="quest template notice",
                kind="paper",
                wants=("bunnyland.dragonsim.quest-template",),
            ),
            ObjectSpec(
                key="fossil_egg",
                room_key="hub",
                name="amber fossil egg",
                kind="relic",
            ),
            ObjectSpec(
                key="ship_parts",
                room_key="hub",
                name="jump drive fuel sensor distress signal",
                kind="ship-system",
            ),
            ObjectSpec(
                key="rad_kit",
                room_key="hub",
                name="junk reactor cache",
                kind="rad-kit",
                wants=(
                    "bunnyland.nukesim.rad-protection",
                    "bunnyland.nukesim.decontamination",
                    "bunnyland.nukesim.rad-medicine",
                    "bunnyland.nukesim.junk",
                ),
            ),
        ],
        characters=[
            CharacterSpec(
                key="fighter",
                name="Clever Fighter",
                room_key="hub",
                species="raptor",
                description="a warrior fighter raptor",
                wants=(
                    "bunnyland.nukesim.radiation-dose",
                    "bunnyland.nukesim.mutation-threshold",
                    "bunnyland.dragonsim.faction-reputation",
                ),
            )
        ],
    )

    result = await instantiate(actor, proposal)

    room = actor.world.get_entity(result.rooms["hub"])
    assert room.has_component(ShelterComponent)
    assert room.has_component(ProceduralSiteComponent)
    assert room.has_component(DungeonComponent)
    assert room.has_component(DungeonRoomComponent)
    assert room.has_component(TravelHubComponent)
    assert room.has_component(InstitutionComponent)
    assert room.has_component(QuestComponent)
    assert room.has_component(ShipComponent)
    assert room.has_component(PowerGridComponent)
    assert room.has_component(StationComponent)
    assert room.has_component(HabitatModuleComponent)
    assert room.has_component(PressurizedComponent)
    assert room.has_component(LifeSupportComponent)
    assert room.has_component(OxygenComponent)
    assert room.has_component(AirlockComponent)
    assert room.has_component(StarSystemComponent)
    assert room.has_component(RadiationSourceComponent)
    assert room.has_component(ScavengeSiteComponent)
    assert room.has_component(LootTableComponent)

    assert actor.world.get_entity(result.objects["firewood"]).has_component(FlammableComponent)
    assert actor.world.get_entity(result.objects["firewood"]).has_component(FireComponent)
    assert actor.world.get_entity(result.objects["barricade"]).has_component(ArmorComponent)
    assert actor.world.get_entity(result.objects["barricade"]).has_component(FortificationComponent)
    shrine = actor.world.get_entity(result.objects["shrine"])
    assert shrine.has_component(PointOfInterestComponent)
    assert shrine.has_component(FactionComponent)
    assert shrine.has_component(QuestComponent)
    assert actor.world.get_entity(result.objects["rumor"]).has_component(RumorComponent)
    assert actor.world.get_entity(result.objects["template"]).has_component(QuestTemplateComponent)
    fossil = actor.world.get_entity(result.objects["fossil_egg"])
    assert fossil.has_component(FossilFragmentComponent)
    assert fossil.has_component(EggComponent)
    ship_parts = actor.world.get_entity(result.objects["ship_parts"])
    assert ship_parts.has_component(JumpDriveComponent)
    assert ship_parts.has_component(FuelComponent)
    assert ship_parts.has_component(SensorComponent)
    assert ship_parts.has_component(DistressSignalComponent)
    rad_kit = actor.world.get_entity(result.objects["rad_kit"])
    assert rad_kit.has_component(RadProtectionComponent)
    assert rad_kit.has_component(DecontaminationComponent)
    assert rad_kit.has_component(RadMedicineComponent)
    assert rad_kit.has_component(JunkComponent)
    assert rad_kit.has_component(RadiationSourceComponent)
    assert rad_kit.has_component(ScavengeSiteComponent)

    fighter = actor.world.get_entity(result.characters["fighter"])
    assert fighter.has_component(StaminaComponent)
    assert fighter.has_component(DinosaurComponent)
    assert fighter.has_component(SpeciesComponent)
    assert fighter.has_component(FertilityComponent)
    assert fighter.has_component(RadiationDoseComponent)
    assert fighter.has_component(MutationThresholdComponent)


async def test_builtin_generation_enrichers_cover_sim_pack_expansion_wants():
    from bunnyland.simpacks.daggersim.mechanics import (
        ExpansionHookComponent,
        ProceduralSiteComponent,
        UnrealizedLocationComponent,
    )
    from bunnyland.simpacks.dinosim.mechanics import (
        AncientSampleComponent,
        ApexPredatorComponent,
        ArmorPlateComponent,
        BaitComponent,
        BoneComponent,
        ChargeComponent,
        CreatureAttackComponent,
        CreatureNeedComponent,
        CreatureProductComponent,
        DinosaurComponent,
        EggComponent,
        EnclosureComponent,
        EscapeRiskComponent,
        FossilFragmentComponent,
        FossilSurveyComponent,
        HerdComponent,
        HideComponent,
        KaijuComponent,
        NestComponent,
        RoarComponent,
        ScentComponent,
        TerritoryComponent,
        ToxinComponent,
        TrackComponent,
        TrampleComponent,
        TranquilizerComponent,
        WaterCreatureComponent,
        WeakPointComponent,
    )
    from bunnyland.simpacks.nukesim.mechanics import (
        BeaconComponent,
        ChemComponent,
        ChemRecipeComponent,
        FactionSalvageComponent,
        FieldRepairComponent,
        GeneratorComponent,
        HotspotMarkerComponent,
        ItemModComponent,
        LockedCrateComponent,
        MutationComponent,
        MutationResistanceComponent,
        OldWorldTechComponent,
        RaiderPressureComponent,
        SampleComponent,
        SchematicComponent,
        SettlementComponent,
        SettlementSalvageComponent,
        SuppressantComponent,
        TechLeadComponent,
        TerminalComponent,
        TraderRouteComponent,
        WastelandArtifactComponent,
        WaterPurifierComponent,
        WaterPurityComponent,
    )
    from bunnyland.simpacks.voidsim.mechanics import (
        AlienArtifactComponent,
        AlienSpeciesComponent,
        AstrogationComponent,
        AwayTeamComponent,
        BlueprintComponent,
        BoardingThreatComponent,
        CargoComponent,
        ContractComponent,
        CustomsHoldComponent,
        DataSalvageComponent,
        DiplomaticMissionComponent,
        DroneComponent,
        EmergencyComponent,
        FabricatorComponent,
        FirstContactComponent,
        GravityComponent,
        InsurancePolicyComponent,
        MiningSiteComponent,
        MoraleComponent,
        MortgageComponent,
        MutinyComponent,
        NavigationRouteComponent,
        OrbitalBodyComponent,
        OrbitComponent,
        PassengerComponent,
        QuarantineComponent,
        ReactorComponent,
        SalvageClaimComponent,
        ShipAIComponent,
        ShipUpgradeComponent,
        SmugglingCompartmentComponent,
        SurveySiteComponent,
        TradeProtocolComponent,
        TranslationMatrixComponent,
        XenobiologySampleComponent,
    )

    actor = WorldActor()
    apply_plugins(bunnyland_plugins(), actor)
    proposal = WorldProposal(
        seed="sim-pack-expansion",
        rooms=[
            RoomSpec(
                key="stub_site",
                title="Unrealized Road Hamlet",
                description="an unrealized location carried by a rumor",
                biome="hamlet",
                wants=(
                    "bunnyland.daggersim.procedural-site",
                    "bunnyland.daggersim.unrealized-location",
                    "bunnyland.daggersim.expansion-hook",
                    "bunnyland.daggersim.rumor",
                ),
            ),
            RoomSpec(
                key="void_frontier",
                title="Derelict Asteroid Survey Site",
                description="a derelict asteroid survey site with salvage and a reactor emergency",
                wants=(
                    "bunnyland.voidsim.orbital-body",
                    "bunnyland.voidsim.survey-site",
                    "bunnyland.voidsim.mining-site",
                    "bunnyland.voidsim.salvage-claim",
                    "bunnyland.voidsim.contract",
                    "bunnyland.voidsim.reactor",
                    "bunnyland.voidsim.gravity",
                ),
            ),
            RoomSpec(
                key="nuke_settlement",
                title="Radio Beacon Settlement",
                description="a settlement with a pre-war terminal and trader route",
                wants=(
                    "bunnyland.nukesim.settlement",
                    "bunnyland.nukesim.settlement-salvage",
                    "bunnyland.nukesim.water-purifier",
                    "bunnyland.nukesim.generator",
                    "bunnyland.nukesim.beacon",
                    "bunnyland.nukesim.trader-route",
                    "bunnyland.nukesim.raider-pressure",
                    "bunnyland.nukesim.terminal",
                    "bunnyland.nukesim.old-world-tech",
                    "bunnyland.nukesim.tech-lead",
                    "bunnyland.nukesim.water-purity",
                ),
            ),
            RoomSpec(
                key="dino_field",
                title="Raptor Track Territory",
                description="tracks cross a herd nest inside a fenced enclosure",
                wants=(
                    "bunnyland.dinosim.enclosure",
                    "bunnyland.dinosim.track",
                    "bunnyland.dinosim.territory",
                    "bunnyland.dinosim.herd",
                    "bunnyland.dinosim.nest",
                    "bunnyland.dinosim.scent",
                ),
            ),
        ],
        objects=[
            ObjectSpec(
                key="void_cache",
                room_key="void_frontier",
                name="frontier fabrication cache",
                kind="cache",
                wants=(
                    "bunnyland.voidsim.fabricator",
                    "bunnyland.voidsim.blueprint",
                    "bunnyland.voidsim.ship-upgrade",
                    "bunnyland.voidsim.cargo",
                    "bunnyland.voidsim.alien-species",
                    "bunnyland.voidsim.first-contact",
                    "bunnyland.voidsim.translation-matrix",
                    "bunnyland.voidsim.quarantine",
                    "bunnyland.voidsim.diplomatic-mission",
                    "bunnyland.voidsim.alien-artifact",
                    "bunnyland.voidsim.xenobiology-sample",
                    "bunnyland.voidsim.trade-protocol",
                    "bunnyland.voidsim.drone",
                    "bunnyland.voidsim.ship-ai",
                    "bunnyland.voidsim.data-salvage",
                    "bunnyland.voidsim.away-team",
                    "bunnyland.voidsim.morale",
                    "bunnyland.voidsim.mutiny",
                    "bunnyland.voidsim.boarding-threat",
                    "bunnyland.voidsim.passenger",
                    "bunnyland.voidsim.customs-hold",
                    "bunnyland.voidsim.smuggling-compartment",
                    "bunnyland.voidsim.insurance-policy",
                    "bunnyland.voidsim.mortgage",
                    "bunnyland.voidsim.orbit",
                    "bunnyland.voidsim.navigation-route",
                    "bunnyland.voidsim.astrogation",
                ),
            ),
            ObjectSpec(
                key="nuke_cache",
                room_key="nuke_settlement",
                name="wasteland repair cache",
                kind="cache",
                wants=(
                    "bunnyland.nukesim.mutation",
                    "bunnyland.nukesim.mutation-resistance",
                    "bunnyland.nukesim.suppressant",
                    "bunnyland.nukesim.sample",
                    "bunnyland.nukesim.locked-crate",
                    "bunnyland.nukesim.wasteland-artifact",
                    "bunnyland.nukesim.faction-salvage",
                    "bunnyland.nukesim.schematic",
                    "bunnyland.nukesim.item-mod",
                    "bunnyland.nukesim.field-repair",
                    "bunnyland.nukesim.chem",
                    "bunnyland.nukesim.chem-recipe",
                    "bunnyland.nukesim.hotspot-marker",
                ),
            ),
            ObjectSpec(
                key="dino_cache",
                room_key="dino_field",
                name="raptor fossil egg sample",
                kind="fossil",
                wants=(
                    "bunnyland.dinosim.fossil",
                    "bunnyland.dinosim.fossil-survey",
                    "bunnyland.dinosim.ancient-sample",
                    "bunnyland.dinosim.bait",
                    "bunnyland.dinosim.tranquilizer",
                    "bunnyland.dinosim.creature-product",
                    "bunnyland.dinosim.hide",
                    "bunnyland.dinosim.bone",
                    "bunnyland.dinosim.toxin",
                    "bunnyland.dinosim.egg",
                ),
            ),
        ],
        characters=[
            CharacterSpec(
                key="kaiju",
                name="Thunderstep",
                room_key="dino_field",
                species="raptor",
                description="a roaring aquatic kaiju raptor",
                wants=(
                    "bunnyland.dinosim.dinosaur",
                    "bunnyland.dinosim.water-creature",
                    "bunnyland.dinosim.creature-need",
                    "bunnyland.dinosim.kaiju",
                    "bunnyland.dinosim.creature-attack",
                    "bunnyland.dinosim.roar",
                    "bunnyland.dinosim.charge",
                    "bunnyland.dinosim.trample",
                    "bunnyland.dinosim.armor-plate",
                    "bunnyland.dinosim.weak-point",
                    "bunnyland.dinosim.apex-predator",
                ),
            )
        ],
    )

    result = await instantiate(actor, proposal)

    stub_site = actor.world.get_entity(result.rooms["stub_site"])
    assert stub_site.has_component(ProceduralSiteComponent)
    assert stub_site.has_component(UnrealizedLocationComponent)
    assert stub_site.get_component(ExpansionHookComponent).trigger == "rumor"

    void_frontier = actor.world.get_entity(result.rooms["void_frontier"])
    assert void_frontier.has_component(OrbitalBodyComponent)
    assert void_frontier.has_component(SurveySiteComponent)
    assert void_frontier.has_component(MiningSiteComponent)
    assert void_frontier.has_component(SalvageClaimComponent)
    assert void_frontier.has_component(ContractComponent)
    assert void_frontier.has_component(EmergencyComponent)
    assert void_frontier.has_component(ReactorComponent)
    assert void_frontier.has_component(GravityComponent)

    nuke_settlement = actor.world.get_entity(result.rooms["nuke_settlement"])
    assert nuke_settlement.has_component(SettlementComponent)
    assert nuke_settlement.has_component(SettlementSalvageComponent)
    assert nuke_settlement.has_component(WaterPurifierComponent)
    assert nuke_settlement.has_component(GeneratorComponent)
    assert nuke_settlement.has_component(BeaconComponent)
    assert nuke_settlement.has_component(TraderRouteComponent)
    assert nuke_settlement.has_component(RaiderPressureComponent)
    assert nuke_settlement.has_component(TerminalComponent)
    assert nuke_settlement.has_component(OldWorldTechComponent)
    assert nuke_settlement.has_component(TechLeadComponent)
    assert nuke_settlement.has_component(WaterPurityComponent)

    dino_field = actor.world.get_entity(result.rooms["dino_field"])
    assert dino_field.has_component(EnclosureComponent)
    assert dino_field.has_component(EscapeRiskComponent)
    assert dino_field.has_component(TrackComponent)
    assert dino_field.has_component(TerritoryComponent)
    assert dino_field.has_component(HerdComponent)
    assert dino_field.has_component(NestComponent)
    assert dino_field.has_component(ScentComponent)

    void_cache = actor.world.get_entity(result.objects["void_cache"])
    for component_type in (
        FabricatorComponent,
        BlueprintComponent,
        ShipUpgradeComponent,
        CargoComponent,
        AlienSpeciesComponent,
        FirstContactComponent,
        TranslationMatrixComponent,
        QuarantineComponent,
        DiplomaticMissionComponent,
        AlienArtifactComponent,
        XenobiologySampleComponent,
        TradeProtocolComponent,
        DroneComponent,
        ShipAIComponent,
        DataSalvageComponent,
        AwayTeamComponent,
        MoraleComponent,
        MutinyComponent,
        BoardingThreatComponent,
        PassengerComponent,
        CustomsHoldComponent,
        SmugglingCompartmentComponent,
        InsurancePolicyComponent,
        MortgageComponent,
        OrbitComponent,
        NavigationRouteComponent,
        AstrogationComponent,
    ):
        assert void_cache.has_component(component_type)

    nuke_cache = actor.world.get_entity(result.objects["nuke_cache"])
    for component_type in (
        MutationComponent,
        MutationResistanceComponent,
        SuppressantComponent,
        SampleComponent,
        LockedCrateComponent,
        WastelandArtifactComponent,
        FactionSalvageComponent,
        SchematicComponent,
        ItemModComponent,
        FieldRepairComponent,
        ChemComponent,
        ChemRecipeComponent,
        HotspotMarkerComponent,
    ):
        assert nuke_cache.has_component(component_type)

    dino_cache = actor.world.get_entity(result.objects["dino_cache"])
    for component_type in (
        FossilFragmentComponent,
        FossilSurveyComponent,
        AncientSampleComponent,
        BaitComponent,
        TranquilizerComponent,
        CreatureProductComponent,
        HideComponent,
        BoneComponent,
        ToxinComponent,
        EggComponent,
    ):
        assert dino_cache.has_component(component_type)

    kaiju = actor.world.get_entity(result.characters["kaiju"])
    for component_type in (
        DinosaurComponent,
        WaterCreatureComponent,
        CreatureNeedComponent,
        KaijuComponent,
        CreatureAttackComponent,
        RoarComponent,
        ChargeComponent,
        TrampleComponent,
        ArmorPlateComponent,
        WeakPointComponent,
        ApexPredatorComponent,
    ):
        assert kaiju.has_component(component_type)


async def test_generated_world_is_playable_via_plugins():
    # Apply the core verbs, then drive a generated character through a move.
    actor = WorldActor()
    apply_plugins(bunnyland_plugins(), actor)
    result = await instantiate(actor, await StubWorldBuilder().propose("seed"))

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


def _has_component(actor, component_type) -> bool:
    return bool(list(actor.world.query().with_all([component_type]).execute_entities()))


async def test_neon_generation_enricher_enriches_from_intent():
    from bunnyland.simpacks.neonsim.mechanics import (
        AccessLevelComponent,
        BlackMarketComponent,
        CameraComponent,
        CheckpointComponent,
        ClinicComponent,
        CyberpunkSiteComponent,
        DataBrokerComponent,
        FixerComponent,
        HackableComponent,
        RunnerContractComponent,
        SafehouseComponent,
        SecurityZoneComponent,
    )

    actor = WorldActor()
    apply_plugins(bunnyland_plugins(), actor)
    proposal = WorldProposal(
        seed="neon",
        rooms=[
            RoomSpec(
                key="strip",
                title="Neon Strip",
                biome="city",
                generation=GenerationIntentComponent(
                    description="a neon strip",
                    wants=("bunnyland.neonsim.cyberpunk-site", "bunnyland.neonsim.security-zone"),
                ),
            )
        ],
        objects=[
            ObjectSpec(
                key="gate",
                room_key="strip",
                name="a turnstile",
                kind="checkpoint",
                wants=("bunnyland.neonsim.checkpoint",),
            ),
            ObjectSpec(
                key="flop",
                room_key="strip",
                name="a flop",
                kind="safehouse",
                wants=("bunnyland.neonsim.safehouse",),
            ),
            ObjectSpec(
                key="cam",
                room_key="strip",
                name="a dome",
                kind="device",
                wants=("bunnyland.neonsim.camera",),
            ),
            ObjectSpec(
                key="term",
                room_key="strip",
                name="a console",
                kind="device",
                wants=("bunnyland.neonsim.terminal",),
            ),
            ObjectSpec(
                key="stall",
                room_key="strip",
                name="a stall",
                kind="vendor",
                wants=("bunnyland.neonsim.black-market",),
            ),
            ObjectSpec(
                key="fence",
                room_key="strip",
                name="a fence",
                kind="vendor",
                wants=("bunnyland.neonsim.data-broker",),
            ),
            ObjectSpec(
                key="doc",
                room_key="strip",
                name="a booth",
                kind="clinic",
                wants=("bunnyland.neonsim.clinic",),
            ),
            ObjectSpec(
                key="gig",
                room_key="strip",
                name="a job",
                kind="contract",
                wants=("bunnyland.neonsim.contract",),
            ),
        ],
        characters=[
            CharacterSpec(
                key="padre",
                name="Padre",
                room_key="strip",
                controller="suspended",
                generation=GenerationIntentComponent(
                    description="a fixer and netrunner",
                    wants=("bunnyland.neonsim.fixer", "bunnyland.neonsim.netrunner"),
                ),
            ),
        ],
    )
    await instantiate(actor, proposal)

    for component in (
        CyberpunkSiteComponent,
        SecurityZoneComponent,
        CheckpointComponent,
        SafehouseComponent,
        CameraComponent,
        HackableComponent,
        BlackMarketComponent,
        DataBrokerComponent,
        ClinicComponent,
        RunnerContractComponent,
        FixerComponent,
        AccessLevelComponent,
    ):
        assert _has_component(actor, component), component.__name__


async def test_neon_generation_enricher_enriches_from_mentions():
    from bunnyland.simpacks.neonsim.mechanics import (
        BlackMarketComponent,
        CameraComponent,
        CheckpointComponent,
        ClinicComponent,
        CyberpunkSiteComponent,
        FixerComponent,
        HackableComponent,
        SafehouseComponent,
    )

    actor = WorldActor()
    apply_plugins(bunnyland_plugins(), actor)
    proposal = WorldProposal(
        seed="neon-mentions",
        rooms=[RoomSpec(key="corp", title="Corp Arcology Plaza", biome="corp")],
        objects=[
            ObjectSpec(key="gate", room_key="corp", name="a checkpoint turnstile", kind="gate"),
            ObjectSpec(key="flop", room_key="corp", name="a back-alley hideout", kind="room"),
            ObjectSpec(key="cam", room_key="corp", name="a cctv camera", kind="device"),
            ObjectSpec(key="term", room_key="corp", name="a records server", kind="device"),
            ObjectSpec(key="stall", room_key="corp", name="a black market dealer", kind="npc"),
            ObjectSpec(key="doc", room_key="corp", name="a ripperdoc surgeon", kind="npc"),
        ],
        characters=[
            CharacterSpec(key="rk", name="a street fixer", room_key="corp", controller="suspended"),
        ],
    )
    await instantiate(actor, proposal)

    for component in (
        CyberpunkSiteComponent,
        CheckpointComponent,
        SafehouseComponent,
        CameraComponent,
        HackableComponent,
        BlackMarketComponent,
        ClinicComponent,
        FixerComponent,
    ):
        assert _has_component(actor, component), component.__name__


def test_enrichment_helper_fallbacks():
    """The neutral request helpers cover explicit values and their deterministic fallbacks."""
    from bunnyland.core.generation import GenerationRequest
    from bunnyland.worldgen.enrichment import (
        GenerationContext,
        generation_animal_species,
        generation_expansion_trigger,
        generation_fish_type,
        generation_orbital_body_type,
        generation_season,
        generation_trade_faction,
    )

    def context(description="", *, wants=(), entity_kind="object"):
        return GenerationContext.from_request(
            GenerationRequest(
                entity_kind=entity_kind,
                description=description,
                capabilities=wants,
                source_key="item",
                request_id="request-id",
            )
        )

    assert generation_expansion_trigger(context(wants=("bunnyland.dragonsim.quest",))) == "quest"
    assert generation_expansion_trigger(context(wants=("bunnyland.daggersim.rumor",))) == "rumor"
    assert generation_expansion_trigger(context()) == "worldgen"
    assert generation_orbital_body_type(context("a pale moon")) == "moon"
    assert generation_orbital_body_type(context("a docking station")) == "station"
    assert generation_orbital_body_type(context("a green planet")) == "planet"
    assert generation_orbital_body_type(context("an asteroid")) == "asteroid-belt"
    assert generation_trade_faction(context("a trader caravan")) == "generated-trader"
    assert generation_trade_faction(context("a rival faction")) == "generated-faction"
    assert generation_trade_faction(context("a quiet hut")) == "generated-colony"
    assert generation_animal_species(context("a brown cow")) == "cow"
    assert generation_animal_species(context("a strange critter")) == "animal"
    assert generation_animal_species(context("a strange critter", entity_kind="beast")) == "beast"
    assert generation_fish_type(context("a fat bass")) == "bass"
    assert generation_fish_type(context("a fish")) == "trout"
    assert generation_season(context("a winter scene")) == "winter"
    assert generation_season(context("a timeless place")) == "spring"


async def test_enrichment_object_only_component_branches():
    """Object and character requests receive their pack-owned declarative components."""
    from bunnyland.simpacks.daggersim.mechanics import BankComponent, ExpansionHookComponent
    from bunnyland.simpacks.dragonsim.mechanics import AncientBeastComponent
    from bunnyland.simpacks.nukesim.mechanics import MutationResistanceComponent
    from bunnyland.simpacks.voidsim.mechanics import (
        EmergencyComponent,
        GravityComponent,
        MiningSiteComponent,
        OrbitalBodyComponent,
        SalvageClaimComponent,
        SurveySiteComponent,
    )

    actor = WorldActor()
    apply_plugins(bunnyland_plugins(), actor)
    result = await instantiate(
        actor,
        WorldProposal(
            seed="object-only-enrichment",
            rooms=[RoomSpec(key="room", title="Room")],
            objects=[
                ObjectSpec(
                    key="void-object",
                    room_key="room",
                    name="survey salvage site",
                    kind="device",
                    wants=(
                        "bunnyland.voidsim.salvage-claim",
                        "bunnyland.voidsim.emergency",
                        "bunnyland.voidsim.gravity",
                        "bunnyland.voidsim.survey-site",
                        "bunnyland.voidsim.mining-site",
                        "bunnyland.voidsim.orbital-body",
                    ),
                ),
                ObjectSpec(
                    key="dragon-object",
                    room_key="room",
                    name="ancient beast",
                    kind="relic",
                    wants=("bunnyland.dragonsim.ancient-beast",),
                ),
                ObjectSpec(
                    key="dagger-object",
                    room_key="room",
                    name="bank expansion",
                    kind="site",
                    wants=("bunnyland.daggersim.expansion-hook", "bunnyland.daggersim.bank"),
                ),
            ],
            characters=[
                CharacterSpec(
                    key="mutant",
                    name="Mutant",
                    room_key="room",
                    wants=("bunnyland.nukesim.mutation-resistance",),
                )
            ],
        ),
    )

    void_object = actor.world.get_entity(result.objects["void-object"])
    for component_type in (
        SalvageClaimComponent,
        EmergencyComponent,
        GravityComponent,
        SurveySiteComponent,
        MiningSiteComponent,
        OrbitalBodyComponent,
    ):
        assert void_object.has_component(component_type)
    assert actor.world.get_entity(result.objects["dragon-object"]).has_component(
        AncientBeastComponent
    )
    dagger_object = actor.world.get_entity(result.objects["dagger-object"])
    assert dagger_object.has_component(ExpansionHookComponent)
    assert dagger_object.has_component(BankComponent)
    assert actor.world.get_entity(result.characters["mutant"]).has_component(
        MutationResistanceComponent
    )


def test_relationship_generation_requires_targets_and_emits_configured_access():
    from bunnyland.core import GenerationEdge, GenerationTarget
    from bunnyland.simpacks.colonysim.generation import ColonyGenerationEnricher
    from bunnyland.simpacks.daggersim.generation import DaggerGenerationEnricher
    from bunnyland.simpacks.daggersim.mechanics import (
        HasAccessToService,
        HasLegalStandingInRegion,
        HasStandingInRegion,
        HasStandingWithInstitution,
    )
    from bunnyland.simpacks.dragonsim.generation import DragonGenerationEnricher
    from bunnyland.simpacks.dragonsim.mechanics import HasStandingWithFaction, WantedByFaction

    colony = ColonyGenerationEnricher().enrich(
        GenerationRequest(
            entity_kind="character",
            capabilities=("bunnyland.colonysim.allowed-area",),
        )
    )
    assert colony.edges == ()

    dagger = DaggerGenerationEnricher()
    access = dagger.enrich(
        GenerationRequest(
            entity_kind="character",
            capabilities=("bunnyland.daggersim.service-access",),
            context={"service_id": "entity_1"},
        )
    )
    assert access.edges == (GenerationEdge(HasAccessToService(), "entity_1"),)

    standing = dagger.enrich(
        GenerationRequest(
            entity_kind="character",
            capabilities=(
                "bunnyland.daggersim.regional-reputation",
                "bunnyland.daggersim.institution-reputation",
                "bunnyland.daggersim.legal-reputation",
            ),
            context={"room_id": "room", "institution_id": "guild"},
        )
    )
    assert standing.edges == (
        GenerationEdge(HasStandingInRegion(score=1), GenerationTarget("room")),
        GenerationEdge(HasStandingWithInstitution(score=1), GenerationTarget("guild")),
        GenerationEdge(HasLegalStandingInRegion(), GenerationTarget("room")),
    )
    unscoped_standing = dagger.enrich(
        GenerationRequest(
            entity_kind="character",
            capabilities=(
                "bunnyland.daggersim.regional-reputation",
                "bunnyland.daggersim.institution-reputation",
                "bunnyland.daggersim.legal-reputation",
            ),
        )
    )
    assert unscoped_standing.edges == ()

    dragon_standing = DragonGenerationEnricher().enrich(
        GenerationRequest(
            entity_kind="character",
            capabilities=(
                "bunnyland.dragonsim.faction-reputation",
                "bunnyland.dragonsim.wanted",
            ),
            context={"faction_id": "faction"},
        )
    )
    assert dragon_standing.edges == (
        GenerationEdge(HasStandingWithFaction(), GenerationTarget("faction")),
        GenerationEdge(WantedByFaction(amount=10), GenerationTarget("faction")),
    )

    unscoped_rumor = dagger.enrich(
        GenerationRequest(
            entity_kind="object",
            capabilities=(
                "bunnyland.daggersim.rumor-source",
                "bunnyland.daggersim.rumor-target",
            ),
        )
    )
    assert unscoped_rumor.edges == ()
