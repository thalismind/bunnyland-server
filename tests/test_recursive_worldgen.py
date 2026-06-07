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

    def propose_room(self, *args, **kwargs) -> RoomNodeProposal:
        return RoomNodeProposal(
            title="Neon Platform, Midnight Rain",
            biome="city",
            indoor=False,
            description="a rain-slick platform under neon billboards",
        )

    def propose_doors(self, *args, **kwargs):
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

        def propose(self, seed):
            return StubWorldBuilder().propose(seed)

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

    def chat(self, *, model, format, messages):
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


def test_ollama_world_agent_parses_json_response(monkeypatch):
    fake_module = types.ModuleType("ollama")
    fake_module.Client = _FakeOllamaClient
    monkeypatch.setitem(sys.modules, "ollama", fake_module)

    agent = OllamaWorldAgent(model="deepseek-v4-pro", host="https://ollama.example", api_key="key")
    room = agent.propose_room("seed", behind=None, known_rooms={})

    assert room.title == "Sky Atrium"
    assert agent._client.kwargs == {
        "host": "https://ollama.example",
        "headers": {"Authorization": "Bearer key"},
    }
    assert agent._client.calls[0]["model"] == "deepseek-v4-pro"
    assert agent._client.calls[0]["format"] == "json"


def test_ollama_world_agent_preserves_history(monkeypatch):
    fake_module = types.ModuleType("ollama")
    fake_module.Client = _FakeOllamaClient
    monkeypatch.setitem(sys.modules, "ollama", fake_module)

    agent = OllamaWorldAgent(model="deepseek-v4-pro")
    agent.propose_room("seed", behind=None, known_rooms={})
    agent.propose_room("seed", behind=None, known_rooms={})

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


def test_openrouter_world_agent_parses_json_response(monkeypatch):
    fake_module = types.ModuleType("openrouter")
    fake_module.OpenRouter = _FakeOpenRouterClient
    monkeypatch.setitem(sys.modules, "openrouter", fake_module)

    agent = OpenRouterWorldAgent(model="openai/gpt-4.1", api_key="key")
    room = agent.propose_room("seed", behind=None, known_rooms={})

    assert room.title == "Sky Atrium"
    assert agent._client.kwargs == {"api_key": "key"}
    assert agent._client.chat.calls[0]["model"] == "openai/gpt-4.1"
    assert agent._client.chat.calls[0]["response_format"] == {"type": "json_object"}


def test_openrouter_world_agent_preserves_history(monkeypatch):
    fake_module = types.ModuleType("openrouter")
    fake_module.OpenRouter = _FakeOpenRouterClient
    monkeypatch.setitem(sys.modules, "openrouter", fake_module)

    agent = OpenRouterWorldAgent(model="openai/gpt-4.1", api_key="key")
    agent.propose_room("seed", behind=None, known_rooms={})
    agent.propose_room("seed", behind=None, known_rooms={})

    second = agent._client.chat.calls[1]["messages"]
    assert second[0]["role"] == "system"
    assert second[1]["role"] == "user"
    assert second[2]["role"] == "assistant"
    assert second[3]["role"] == "user"
