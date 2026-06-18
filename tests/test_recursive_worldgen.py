"""Tests for the recursive, breadth-first world generator."""

from __future__ import annotations

import sys
import types
from types import SimpleNamespace

import pytest

import bunnyland.worldgen.generators as generator_module
from bunnyland.core import (
    CharacterComponent,
    ContainerComponent,
    ControlledBy,
    DoorComponent,
    RoomComponent,
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
    DoorProposal,
    GenOptions,
    InstantiatedWorld,
    OllamaWorldAgent,
    OpenRouterWorldAgent,
    RecursiveWorldGenerator,
    RoomNodeProposal,
    StubWorldAgent,
    StubWorldBuilder,
    oneshot_generator,
    recursive_generator,
)
from bunnyland.worldgen.recursive_builder import _message_to_history


def _exits(world, room_id):
    room = world.get_entity(room_id)
    return {edge.direction: target for edge, target in room.get_relationships(ExitTo)}


async def test_bfs_respects_the_room_budget():
    actor = WorldActor()
    gen = RecursiveWorldGenerator(actor, StubWorldAgent(), max_rooms=2)
    result = await gen.generate("a quiet marsh")

    assert len(result.rooms) == 2
    assert gen.stats["rooms"] == 2


async def test_doors_are_bidirectional_unless_marked_one_way():
    actor = WorldActor()
    # Budget of 3 expands the north tunnel and the one-way slide (BFS order).
    gen = RecursiveWorldGenerator(actor, StubWorldAgent(), max_rooms=3)
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
    gen = RecursiveWorldGenerator(actor, StubWorldAgent(), max_rooms=3)
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
    gen = RecursiveWorldGenerator(actor, StubWorldAgent(), max_rooms=2)
    result = await gen.generate("seed")
    world = actor.world

    # Every exit still resolves to a real, distinct room (no clobbered edges).
    for room_id in result.rooms.values():
        for _edge, target in world.get_entity(room_id).get_relationships(ExitTo):
            assert world.has_entity(target)


class _DuplicateRoomTitleAgent(StubWorldAgent):
    def __init__(self) -> None:
        self._door_calls = 0

    async def propose_room(self, *args, **kwargs) -> RoomNodeProposal:
        return RoomNodeProposal(
            title="Neon Platform, Midnight Rain",
            biome="city",
            indoor=False,
            description="a rain-slick platform under neon billboards",
        )

    async def propose_doors(self, *args, **kwargs):
        self._door_calls += 1
        if self._door_calls == 1:
            return [
                DoorProposal(direction="north", beyond_hint="Transit Stairs"),
                DoorProposal(direction="east", beyond_hint="Signal Canopy"),
            ]
        return []


async def test_room_titles_are_unique_during_recursive_generation():
    actor = WorldActor()
    gen = RecursiveWorldGenerator(actor, _DuplicateRoomTitleAgent(), max_rooms=3)
    result = await gen.generate("neon rain")
    world = actor.world

    titles = [
        world.get_entity(room_id).get_component(RoomComponent).title
        for room_id in result.rooms.values()
    ]

    assert titles == [
        "Neon Platform, Midnight Rain",
        "Neon Platform, Midnight Rain 2",
        "Neon Platform, Midnight Rain 3",
    ]
    assert [spec.title for spec in gen._room_specs.values()] == titles


async def test_rooms_are_populated_with_objects_and_characters():
    actor = WorldActor()
    gen = RecursiveWorldGenerator(actor, StubWorldAgent(), max_rooms=2)
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
    gen = RecursiveWorldGenerator(actor, StubWorldAgent(), max_rooms=2)
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
    gen = RecursiveWorldGenerator(actor, StubWorldAgent(), max_rooms=2)
    result = await gen.generate("seed")

    assert events
    assert events[0].room_count == len(result.rooms)
    assert events[0].character_count == len(result.characters)


def test_dangling_resolution_defaults_to_seal():
    assert DanglingResolution().action == "seal"


def test_recursive_message_to_history_uses_model_dump_or_message_attributes():
    class DumpableMessage:
        def model_dump(self, **kwargs):
            assert kwargs == {"mode": "json", "exclude_none": True}
            return {"role": "assistant", "content": "dumped"}

    assert _message_to_history(DumpableMessage()) == {
        "role": "assistant",
        "content": "dumped",
    }
    assert _message_to_history(SimpleNamespace(role="tool", content="done")) == {
        "role": "tool",
        "content": "done",
    }
    assert _message_to_history(SimpleNamespace(role="assistant")) == {
        "role": "assistant",
    }


async def test_builtin_generator_functions_produce_worlds_offline():
    options = GenOptions(llm=False, max_rooms=3)

    one = await oneshot_generator(WorldActor(), "seed", options)
    assert one.rooms and one.characters

    many = await recursive_generator(WorldActor(), "seed", options)
    assert len(many.rooms) == 3 and many.characters


async def test_oneshot_generator_rejects_openrouter_and_uses_ollama_builder(monkeypatch):
    import bunnyland.worldgen.ollama_builder as ollama_builder

    captured = {}

    class FakeOllamaWorldBuilder:
        system_prompt = "fake prompt"

        def __init__(self, **kwargs):
            captured.update(kwargs)

        async def propose(self, seed):
            return await StubWorldBuilder().propose(seed)

    monkeypatch.setattr(ollama_builder, "OllamaWorldBuilder", FakeOllamaWorldBuilder)

    with pytest.raises(RuntimeError, match="recursive generator"):
        await oneshot_generator(
            WorldActor(),
            "seed",
            GenOptions(llm=True, provider="openrouter"),
        )

    result = await oneshot_generator(
        WorldActor(),
        "seed",
        GenOptions(llm=True, provider="ollama", model="world", host="host", api_key="key"),
    )

    assert result.rooms
    assert result.prompt == "fake prompt"
    assert captured == {"model": "world", "host": "host", "api_key": "key"}


async def test_recursive_generator_selects_llm_provider_builders(monkeypatch):
    import bunnyland.worldgen.recursive_builder as recursive_builder

    captured = {}

    class FakeOpenRouterWorldAgent(StubWorldAgent):
        system_prompt = "openrouter prompt"

        def __init__(self, **kwargs):
            captured["openrouter"] = kwargs

    class FakeOllamaWorldAgent(StubWorldAgent):
        system_prompt = "ollama prompt"

        def __init__(self, **kwargs):
            captured["ollama"] = kwargs

    class FakeRecursiveWorldGenerator:
        def __init__(self, actor, builder, *, max_rooms):
            self.actor = actor
            self.builder = builder
            self.max_rooms = max_rooms

        async def generate(self, seed):
            del seed
            return InstantiatedWorld()

    monkeypatch.setattr(recursive_builder, "OpenRouterWorldAgent", FakeOpenRouterWorldAgent)
    monkeypatch.setattr(recursive_builder, "OllamaWorldAgent", FakeOllamaWorldAgent)
    monkeypatch.setattr(generator_module, "RecursiveWorldGenerator", FakeRecursiveWorldGenerator)

    openrouter = await recursive_generator(
        WorldActor(),
        "seed",
        GenOptions(
            llm=True,
            provider="openrouter",
            model="world",
            api_key="key",
            server_url="https://openrouter.example",
        ),
    )
    ollama = await recursive_generator(
        WorldActor(),
        "seed",
        GenOptions(llm=True, provider="ollama", model="world", host="host", api_key="key"),
    )

    assert openrouter.prompt == "openrouter prompt"
    assert ollama.prompt == "ollama prompt"
    assert captured["openrouter"] == {
        "model": "world",
        "api_key": "key",
        "server_url": "https://openrouter.example",
    }
    assert captured["ollama"] == {"model": "world", "host": "host", "api_key": "key"}


async def test_generators_record_the_dm_system_prompt():
    from bunnyland.worldgen.ollama_builder import _SYSTEM_PROMPT, OllamaWorldBuilder
    from bunnyland.worldgen.recursive_builder import OllamaWorldAgent

    # Offline stub builders carry no LLM prompt.
    one = await oneshot_generator(WorldActor(), "seed", GenOptions(llm=False))
    assert one.prompt == ""
    many = await recursive_generator(WorldActor(), "seed", GenOptions(llm=False, max_rooms=2))
    assert many.prompt == ""

    # The LLM builders expose their literal DM system prompt (captured into metadata).
    assert OllamaWorldBuilder.system_prompt == _SYSTEM_PROMPT
    assert "world-builder" in OllamaWorldBuilder.system_prompt
    assert "DM" in OllamaWorldAgent.system_prompt


class _FakeOllamaClient:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs
        self.calls: list[dict] = []

    async def chat(self, *, model, format, messages):
        self.calls.append(
            {
                "model": model,
                "format": format,
                "messages": [dict(message) for message in messages],
            }
        )
        return {
            "message": {
                "role": "assistant",
                "content": '{"title":"Sky Atrium","biome":"city","indoor":true,'
                '"light":0.8,"celsius":21,"description":"a glassy atrium"}',
            }
        }


async def test_ollama_world_agent_parses_json_response(monkeypatch):
    fake_module = types.ModuleType("ollama")
    fake_module.AsyncClient = _FakeOllamaClient
    monkeypatch.setitem(sys.modules, "ollama", fake_module)

    agent = OllamaWorldAgent(model="deepseek-v4-pro", host="https://ollama.example", api_key="key")
    room = await agent.propose_room("seed", behind=None, known_rooms={})

    assert room.title == "Sky Atrium"
    assert agent._client.kwargs == {
        "host": "https://ollama.example",
        "headers": {"Authorization": "Bearer key"},
    }
    assert agent._client.calls[0]["model"] == "deepseek-v4-pro"
    assert agent._client.calls[0]["format"] == "json"


async def test_ollama_world_agent_preserves_history(monkeypatch):
    fake_module = types.ModuleType("ollama")
    fake_module.AsyncClient = _FakeOllamaClient
    monkeypatch.setitem(sys.modules, "ollama", fake_module)

    agent = OllamaWorldAgent(model="deepseek-v4-pro")
    await agent.propose_room("seed", behind=None, known_rooms={})
    await agent.propose_room("seed", behind=None, known_rooms={})

    second = agent._client.calls[1]["messages"]
    assert second[0]["role"] == "system"
    assert second[1]["role"] == "user"
    assert second[2]["role"] == "assistant"
    assert second[3]["role"] == "user"


class _FakeOpenRouterChat:
    def __init__(self):
        self.calls: list[dict] = []

    def send(self, *, model, messages, response_format):
        self.calls.append(
            {
                "model": model,
                "messages": [dict(message) for message in messages],
                "response_format": response_format,
            }
        )
        message = types.SimpleNamespace(
            role="assistant",
            content='{"title":"Sky Atrium","biome":"city","indoor":true,'
            '"light":0.8,"celsius":21,"description":"a glassy atrium"}',
            model_dump=lambda **_: {
                "role": "assistant",
                "content": '{"title":"Sky Atrium"}',
            },
        )
        return types.SimpleNamespace(choices=[types.SimpleNamespace(message=message)])


class _FakeOpenRouterClient:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.chat = _FakeOpenRouterChat()


async def test_openrouter_world_agent_parses_json_response(monkeypatch):
    fake_module = types.ModuleType("openrouter")
    fake_module.OpenRouter = _FakeOpenRouterClient
    monkeypatch.setitem(sys.modules, "openrouter", fake_module)

    agent = OpenRouterWorldAgent(model="openai/gpt-4.1", api_key="key")
    room = await agent.propose_room("seed", behind=None, known_rooms={})

    assert room.title == "Sky Atrium"
    assert agent._client.kwargs == {"api_key": "key"}
    assert agent._client.chat.calls[0]["model"] == "openai/gpt-4.1"
    assert agent._client.chat.calls[0]["response_format"] == {"type": "json_object"}


async def test_openrouter_world_agent_preserves_history(monkeypatch):
    fake_module = types.ModuleType("openrouter")
    fake_module.OpenRouter = _FakeOpenRouterClient
    monkeypatch.setitem(sys.modules, "openrouter", fake_module)

    agent = OpenRouterWorldAgent(model="openai/gpt-4.1", api_key="key")
    await agent.propose_room("seed", behind=None, known_rooms={})
    await agent.propose_room("seed", behind=None, known_rooms={})

    second = agent._client.chat.calls[1]["messages"]
    assert second[0]["role"] == "system"
    assert second[1]["role"] == "user"
    assert second[2]["role"] == "assistant"
    assert second[3]["role"] == "user"


async def test_ollama_world_agent_builds_each_proposal_from_json(monkeypatch):
    from bunnyland.worldgen.proposal import CharacterProposal, ItemProposal, StoryEventProposal

    calls: list[str] = []
    responses = [
        {
            "title": "Root",
            "biome": "marsh",
            "indoor": True,
            "light": 0.4,
            "celsius": 18,
            "description": "root room",
        },
        {
            "title": "Blue Hall",
            "biome": "cave",
            "indoor": True,
            "light": 0.2,
            "celsius": 14,
            "description": "a blue hall",
        },
        {
            "doors": [
                {"direction": "north", "beyond_hint": "Blue Hall"},
                {"direction": "down", "bidirectional": False},
            ]
        },
        {"action": "link", "target_room_key": "room_0"},
        {
            "objects": [{"name": "lamp", "kind": "tool"}],
            "characters": [{"name": "Mira", "species": "bunny", "controller": "suspended"}],
        },
        {"name": "Guide", "species": "fox", "controller": "llm", "llm_profile": "sage"},
        {"name": "silver key", "kind": "key", "portable": True},
        {
            "title": "Bell Rings",
            "kind": "story_event",
            "summary": "A bell rings.",
            "severity": 2,
            "budget_spent": 1,
            "objects": [{"name": "brass bell"}],
            "characters": [{"name": "Bellkeeper"}],
        },
        {"objects": [{"name": "pocket watch", "kind": "tool", "portable": True}]},
        {"objects": [{"name": "folded map", "kind": "paper", "portable": True}]},
    ]

    agent = object.__new__(OllamaWorldAgent)

    async def fake_ask(self, instruction):
        del self
        calls.append(instruction)
        return responses.pop(0)

    monkeypatch.setattr(agent, "_ask", fake_ask.__get__(agent, OllamaWorldAgent))

    root = await agent.propose_room(
        "seed",
        behind=None,
        known_rooms={},
        schema_context="RoomComponent",
    )
    behind = DoorProposal(direction="north", beyond_hint="Blue Hall")
    room = await agent.propose_room(
        "seed",
        behind=behind,
        known_rooms={"room_0": "Root"},
    )
    doors = await agent.propose_doors(room)
    resolution = await agent.resolve_dangling_door(
        doors[0],
        room=room,
        candidates={"room_0": "Root"},
    )
    contents = await agent.propose_contents(
        room,
        known_rooms={"room_0": "Root", "room_1": "Blue Hall"},
    )
    character = await agent.propose_character(
        room,
        prompt="a guide",
        known_rooms={"room_0": "Root"},
        schema_context="CharacterComponent",
    )
    item = await agent.propose_item(
        container_name="chest",
        container_kind="container",
        prompt="a key",
        known_rooms={"room_0": "Root"},
    )
    event = await agent.propose_event(
        room,
        prompt="a bell",
        known_rooms={"room_0": "Root"},
    )
    inventory = await agent.propose_inventory(name="Guide", species="fox")
    container_contents = await agent.propose_container_contents(name="chest")

    assert isinstance(root, RoomNodeProposal)
    assert root.title == "Root"
    assert room.title == "Blue Hall"
    assert [door.direction for door in doors] == ["north", "down"]
    assert resolution.target_room_key == "room_0"
    assert contents.objects[0].name == "lamp"
    assert isinstance(character, CharacterProposal)
    assert character.llm_profile == "sage"
    assert isinstance(item, ItemProposal)
    assert item.name == "silver key"
    assert isinstance(event, StoryEventProposal)
    assert event.objects[0].name == "brass bell"
    assert inventory[0].name == "pocket watch"
    assert container_contents[0].name == "folded map"
    assert "Live ECS JSON schemas" in calls[0]
    assert "Through the north door" in calls[1]
    assert "Rooms so far: Root" in calls[5]
