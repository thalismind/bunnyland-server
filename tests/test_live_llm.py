"""Optional live LLM integration tests.

These tests are intentionally skipped by default. Enable them with ``BUNNYLAND_LIVE_LLM=1``
and provider-specific connection environment variables.
"""

from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path

import pytest

from bunnyland.core import (
    ActionArgument,
    ActionDefinition,
    ActionPointsComponent,
    CharacterComponent,
    ContainmentMode,
    Contains,
    DoorComponent,
    ExitTo,
    FocusPointsComponent,
    IdentityComponent,
    InitiativeComponent,
    MoveHandler,
    PortableComponent,
    RoomComponent,
    SayHandler,
    TakeHandler,
    WorldActor,
    container_of,
    spawn_entity,
)
from bunnyland.core.controllers import LLMControllerComponent
from bunnyland.core.events import SpeechSaidEvent
from bunnyland.llm_agents import ControllerDispatch, OllamaAgent, OpenRouterAgent
from bunnyland.plugins import apply_plugins, bunnyland_plugins
from bunnyland.prompts.builder import PromptBuilder
from bunnyland.server.models import (
    WorldCharacterGenerationRequest,
    WorldEventGenerationRequest,
    WorldItemGenerationRequest,
    WorldRoomGenerationRequest,
)
from bunnyland.server.patches import apply_world_patch
from bunnyland.server.worldgen import (
    generate_character_patch,
    generate_event_patch,
    generate_item_patch,
    generate_room_patch,
)
from bunnyland.worldgen import (
    GenOptions,
    OllamaWorldAgent,
    OpenRouterWorldAgent,
    oneshot_generator,
    recursive_generator,
)

OLLAMA_CLOUD_HOST = "https://ollama.com"
PROVIDERS = ("ollama", "openrouter")


def _load_dotenv(path: Path = Path(".env")) -> None:
    """Load simple KEY=VALUE entries for live tests without overriding the shell."""

    if not path.exists():
        return
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'\"")
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv()

pytestmark = pytest.mark.live_llm


def _live_enabled() -> None:
    if os.environ.get("BUNNYLAND_LIVE_LLM") != "1":
        pytest.skip("set BUNNYLAND_LIVE_LLM=1 to run live LLM tests")


def _ollama_connection() -> tuple[str | None, str | None]:
    _live_enabled()
    host = os.environ.get("OLLAMA_HOST")
    api_key = os.environ.get("OLLAMA_CLOUD_API_KEY")
    if not (host or api_key):
        pytest.skip("set OLLAMA_HOST or OLLAMA_CLOUD_API_KEY to run live Ollama tests")
    if api_key and not host:
        host = OLLAMA_CLOUD_HOST
    return host, api_key


def _openrouter_connection() -> tuple[str, str | None]:
    _live_enabled()
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        pytest.skip("set OPENROUTER_API_KEY to run live OpenRouter tests")
    return api_key, os.environ.get("OPENROUTER_SERVER_URL")


def _character_agent(provider: str):
    if provider == "ollama":
        host, api_key = _ollama_connection()
        model = os.environ.get("BUNNYLAND_LIVE_OLLAMA_MODEL", "deepseek-v4-flash")
        return OllamaAgent(model=model, host=host, api_key=api_key)
    if provider == "openrouter":
        api_key, server_url = _openrouter_connection()
        model = os.environ.get("BUNNYLAND_LIVE_OPENROUTER_MODEL", "openai/gpt-4.1-mini")
        return OpenRouterAgent(model=model, api_key=api_key, server_url=server_url)
    raise AssertionError(f"unknown provider {provider!r}")


def _world_agent(provider: str):
    if provider == "ollama":
        host, api_key = _ollama_connection()
        model = os.environ.get("BUNNYLAND_LIVE_OLLAMA_WORLD_MODEL", "deepseek-v4-pro")
        return OllamaWorldAgent(model=model, host=host, api_key=api_key)
    if provider == "openrouter":
        api_key, server_url = _openrouter_connection()
        model = os.environ.get("BUNNYLAND_LIVE_OPENROUTER_WORLD_MODEL", "openai/gpt-4.1")
        return OpenRouterWorldAgent(model=model, api_key=api_key, server_url=server_url)
    raise AssertionError(f"unknown provider {provider!r}")


def _world_options(provider: str, *, max_rooms: int = 2) -> GenOptions:
    if provider == "ollama":
        host, api_key = _ollama_connection()
        model = os.environ.get("BUNNYLAND_LIVE_OLLAMA_WORLD_MODEL", "deepseek-v4-pro")
        return GenOptions(
            llm=True,
            provider=provider,
            model=model,
            host=host,
            api_key=api_key,
            max_rooms=max_rooms,
        )
    if provider == "openrouter":
        api_key, server_url = _openrouter_connection()
        model = os.environ.get("BUNNYLAND_LIVE_OPENROUTER_WORLD_MODEL", "openai/gpt-4.1")
        return GenOptions(
            llm=True,
            provider=provider,
            model=model,
            api_key=api_key,
            server_url=server_url,
            max_rooms=max_rooms,
        )
    raise AssertionError(f"unknown provider {provider!r}")


class _InstructionPromptBuilder(PromptBuilder):
    def __init__(self, *args, instruction: str, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.instruction = instruction

    def build(self, character_id, *, epoch: int = 0):
        context = super().build(character_id, epoch=epoch)
        return replace(context, warnings=(*context.warnings, self.instruction))


@pytest.mark.asyncio
async def test_live_ollama_character_agent_can_call_wait_tool():
    agent = _character_agent("ollama")

    call = await agent.decide(
        "Call exactly one tool: wait. Do not call any other tool.",
        None,
        character_id="live-ollama",
    )

    assert call is not None
    assert call.name == "wait"


@pytest.mark.asyncio
async def test_live_ollama_world_agent_can_propose_room():
    agent = _world_agent("ollama")

    room = await agent.propose_room("a tiny live-test moss room", behind=None, known_rooms={})

    assert room.title
    assert room.description


@pytest.mark.asyncio
async def test_live_openrouter_character_agent_can_call_wait_tool():
    agent = _character_agent("openrouter")

    call = await agent.decide(
        "Call exactly one tool: wait. Do not call any other tool.",
        None,
        character_id="live-openrouter",
    )

    assert call is not None
    assert call.name == "wait"


@pytest.mark.asyncio
async def test_live_openrouter_world_agent_can_propose_room():
    agent = _world_agent("openrouter")

    room = await agent.propose_room("a tiny live-test moss room", behind=None, known_rooms={})

    assert room.title
    assert room.description


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", PROVIDERS)
async def test_live_recursive_generator_instantiates_world(provider):
    actor = WorldActor()
    apply_plugins(bunnyland_plugins(), actor)
    options = _world_options(provider, max_rooms=2)

    result = await recursive_generator(
        actor,
        "live test: make a compact playable meadow with at least one character and one object",
        options,
    )

    assert result.prompt
    assert len(result.rooms) >= 1
    for room_id in result.rooms.values():
        assert actor.world.get_entity(room_id).has_component(RoomComponent)
    for character_id in result.characters.values():
        assert actor.world.get_entity(character_id).has_component(CharacterComponent)
    if len(result.rooms) > 1:
        assert any(
            actor.world.get_entity(room_id).get_relationships(ExitTo)
            for room_id in result.rooms.values()
        )


@pytest.mark.asyncio
async def test_live_ollama_oneshot_generator_instantiates_playable_world():
    actor = WorldActor()
    apply_plugins(bunnyland_plugins(), actor)

    result = await oneshot_generator(
        actor,
        "live test: small connected world with food, water, paper, and two characters",
        _world_options("ollama", max_rooms=2),
    )

    assert result.prompt
    assert len(result.rooms) >= 2
    assert result.objects
    assert result.characters
    assert any(
        actor.world.get_entity(room_id).get_relationships(ExitTo)
        for room_id in result.rooms.values()
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", PROVIDERS)
async def test_live_world_agent_generates_applicable_server_patches(provider):
    actor = WorldActor()
    apply_plugins(bunnyland_plugins(), actor)

    room = spawn_entity(
        actor.world,
        [RoomComponent(title="Live Patch Lab", biome="test-lab", indoor=True)],
    )
    door = spawn_entity(
        actor.world,
        [
            IdentityComponent(name="a sealed north door", kind="door"),
            DoorComponent(open=False, open_on_use=False),
        ],
    )
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), door.id)
    options = _world_options(provider, max_rooms=1)

    item_response = await generate_item_patch(
        actor,
        WorldItemGenerationRequest(
            container_entity_id=str(room.id),
            prompt="a portable live-test tool for exploring a room",
        ),
        options=options,
    )
    assert item_response.generated_name
    assert apply_world_patch(actor, item_response.patch).changed_entities

    character_response = await generate_character_patch(
        actor,
        WorldCharacterGenerationRequest(
            room_entity_id=str(room.id),
            prompt="a suspended live-test helper character",
        ),
        options=options,
    )
    assert character_response.generated_name
    assert apply_world_patch(actor, character_response.patch).changed_entities

    event_response = await generate_event_patch(
        actor,
        WorldEventGenerationRequest(
            room_entity_id=str(room.id),
            prompt="a harmless live-test incident that leaves an inspectable clue",
        ),
        options=options,
    )
    assert event_response.generated_title
    assert apply_world_patch(actor, event_response.patch).changed_entities

    room_response = await generate_room_patch(
        actor,
        WorldRoomGenerationRequest(
            door_entity_id=str(door.id),
            direction="north",
            prompt="a tiny live-test annex with one useful object",
        ),
        options=options,
    )
    assert room_response.generated_title
    assert apply_world_patch(actor, room_response.patch).changed_entities


def _character_model(provider: str) -> str:
    if provider == "ollama":
        return os.environ.get("BUNNYLAND_LIVE_OLLAMA_MODEL", "deepseek-v4-flash")
    if provider == "openrouter":
        return os.environ.get("BUNNYLAND_LIVE_OPENROUTER_MODEL", "openai/gpt-4.1-mini")
    raise AssertionError(f"unknown provider {provider!r}")


def _gameplay_actor(provider: str) -> tuple[WorldActor, object, object, object, int]:
    actor = WorldActor()
    actor.register_handler(MoveHandler())
    actor.register_handler(TakeHandler())
    actor.register_handler(SayHandler())
    actor.register_action_definition(
        ActionDefinition(
            command_type="move",
            tool_name="move",
            description="Move through a visible exit by direction.",
            arguments={"direction": ActionArgument(required=True)},
        )
    )
    actor.register_action_definition(
        ActionDefinition(
            command_type="take",
            tool_name="take",
            description="Take a reachable item.",
            arguments={"item_id": ActionArgument(kind="entity", required=True)},
        )
    )
    actor.register_action_definition(
        ActionDefinition(
            command_type="say",
            tool_name="say",
            description="Say text aloud in the current room.",
            arguments={"text": ActionArgument(required=True)},
        )
    )

    room_a = spawn_entity(actor.world, [RoomComponent(title="Live Gameplay Burrow")])
    room_b = spawn_entity(actor.world, [RoomComponent(title="Live Gameplay Tunnel")])
    room_a.add_relationship(ExitTo(direction="north"), room_b.id)
    room_b.add_relationship(ExitTo(direction="south"), room_a.id)

    character = spawn_entity(
        actor.world,
        [
            IdentityComponent(name="Juniper", kind="character"),
            CharacterComponent(species="bunny"),
            ActionPointsComponent(current=5.0, maximum=5.0, regen_per_hour=5.0),
            FocusPointsComponent(current=3.0, maximum=3.0, regen_per_hour=3.0),
            InitiativeComponent(score=1.0),
        ],
    )
    room_a.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), character.id)

    item = spawn_entity(
        actor.world,
        [
            IdentityComponent(name="a brass live-test key", kind="item"),
            PortableComponent(can_pick_up=True),
        ],
    )
    room_b.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), item.id)

    controller = spawn_entity(actor.world)
    controller.add_component(
        LLMControllerComponent(
            profile_name="live-test",
            model=_character_model(provider),
            provider=provider,
        )
    )
    generation = actor.assign_controller(character.id, controller.id)
    return actor, room_b.id, character.id, item.id, generation


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", PROVIDERS)
async def test_live_character_agent_can_play_basic_gameplay_loops(provider):
    actor, destination_id, character_id, item_id, _generation = _gameplay_actor(provider)
    agent = _character_agent(provider)
    speech_events: list[SpeechSaidEvent] = []
    actor.bus.subscribe(SpeechSaidEvent, speech_events.append)

    move_builder = _InstructionPromptBuilder(
        actor.world,
        instruction=(
            "Live test instruction: call exactly one tool named move with direction north. "
            "Do not use exit_id and do not call any other tool."
        ),
    )
    move_dispatch = ControllerDispatch(actor, move_builder, agent)
    await move_dispatch.run_once()
    move_decisions = await move_dispatch.await_pending()
    await actor.tick(1.0)

    assert move_decisions and move_decisions[0].tool == "move"
    assert container_of(actor.world.get_entity(character_id)) == destination_id

    take_builder = _InstructionPromptBuilder(
        actor.world,
        instruction=(
            "Live test instruction: call exactly one tool named take with "
            "item_id 'a brass live-test key'. Do not call any other tool."
        ),
    )
    take_dispatch = ControllerDispatch(actor, take_builder, agent)
    await take_dispatch.run_once()
    take_decisions = await take_dispatch.await_pending()
    await actor.tick(1.0)

    assert take_decisions and take_decisions[0].tool == "take"
    assert container_of(actor.world.get_entity(item_id)) == character_id

    await actor.tick(3600.0)  # speech costs focus as well as action.
    say_builder = _InstructionPromptBuilder(
        actor.world,
        instruction=(
            "Live test instruction: call exactly one tool named say with text "
            "'live loop hello'. Do not call any other tool."
        ),
    )
    say_dispatch = ControllerDispatch(actor, say_builder, agent)
    await say_dispatch.run_once()
    say_decisions = await say_dispatch.await_pending()
    await actor.tick(1.0)

    assert say_decisions and say_decisions[0].tool == "say"
    assert any(event.text == "live loop hello" for event in speech_events)
