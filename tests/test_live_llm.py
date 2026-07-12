"""Optional live LLM integration tests.

These tests are intentionally skipped by default. Enable them with ``BUNNYLAND_LIVE_LLM=1``
and provider-specific connection environment variables.
"""

from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path

import pytest

from bunnyland import telemetry
from bunnyland.core import (
    ActionPointsComponent,
    CharacterComponent,
    ContainmentMode,
    Contains,
    DoorComponent,
    ExitTo,
    FocusPointsComponent,
    IdentityComponent,
    InitiativeComponent,
    MemoryProfileComponent,
    PortableComponent,
    RoomComponent,
    WorldActor,
    container_of,
    spawn_entity,
)
from bunnyland.core.controllers import LLMControllerComponent
from bunnyland.core.events import SpeechSaidEvent
from bunnyland.foundation.persona.mechanics import (
    GoalComponent,
    PersonaProfileComponent,
    PreferenceComponent,
    TraitSetComponent,
)
from bunnyland.llm_agents import ControllerDispatch, OllamaAgent, OpenRouterAgent, tool_schemas
from bunnyland.llm_agents.agent import CHARACTER_SYSTEM_PROMPT
from bunnyland.plugins import apply_plugins, bunnyland_plugins, collect_persona_fragments
from bunnyland.plugins.ids import CORE_VERBS, MEMORY
from bunnyland.prompts.builder import PromptBuilder, render_prompt
from bunnyland.server.app import create_app
from bunnyland.server.character_chat import ALLOWED_CHAT_TOOLS, build_character_chat_service
from bunnyland.server.models import (
    CharacterChatRequest,
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


@pytest.fixture
def live_otel_capture(monkeypatch):
    pytest.importorskip("opentelemetry.sdk")
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import InMemoryMetricReader
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    monkeypatch.setenv("BUNNYLAND_OTEL_ENABLED", "1")
    resource = Resource.create({"service.name": "bunnyland-live-llm-test"})
    span_exporter = InMemorySpanExporter()
    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(SimpleSpanProcessor(span_exporter))
    metric_reader = InMemoryMetricReader()
    meter_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])

    telemetry.reset_for_tests()
    assert telemetry.init_telemetry(providers=(tracer_provider, meter_provider)) is True
    yield span_exporter, metric_reader
    telemetry.reset_for_tests()


def _spans_named(span_exporter, name: str):
    return [span for span in span_exporter.get_finished_spans() if span.name == name]


def _metric_points(reader) -> dict[str, list]:
    points: dict[str, list] = {}
    data = reader.get_metrics_data()
    if data is None:
        return points
    for resource_metric in data.resource_metrics:
        for scope_metric in resource_metric.scope_metrics:
            for metric in scope_metric.metrics:
                points.setdefault(metric.name, []).extend(metric.data.data_points)
    return points


def _wait_tool_schema() -> list[dict]:
    core = next(plugin for plugin in bunnyland_plugins() if plugin.id == CORE_VERBS)
    return [
        schema
        for schema in tool_schemas(core.commands.action_definitions)
        if schema["function"]["name"] == "wait"
    ]


def _assert_llm_usage_trace_attrs(attrs, provider: str, model: str, request_kind: str) -> None:
    assert attrs["provider"] == provider
    assert attrs["model"] == model
    assert attrs["llm.request.kind"] == request_kind
    assert attrs["llm.history.messages"] >= 2
    assert attrs["llm.system_prompt_chars"] > 0


def _assert_token_metrics_are_consistent(points: dict[str, list], provider: str, model: str):
    prompt = points.get("bunnyland.llm.tokens.prompt", [])
    completion = points.get("bunnyland.llm.tokens.completion", [])
    total = points.get("bunnyland.llm.tokens.total", [])
    token_points = [*prompt, *completion, *total]
    assert token_points, f"{provider} did not expose token usage for {model}"
    for point in token_points:
        assert point.attributes == {"provider": provider, "model": model}
        assert point.value > 0
    if prompt and completion and total:
        assert total[0].value >= prompt[0].value + completion[0].value
    return token_points


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
        tools=_wait_tool_schema(),
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
        tools=_wait_tool_schema(),
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
async def test_live_character_agent_records_prompt_tools_metrics_and_traces(
    provider, live_otel_capture
):
    span_exporter, metric_reader = live_otel_capture
    agent = _character_agent(provider)
    model = _character_model(provider)

    with telemetry.span("live.character.decide"):
        call = await agent.decide(
            "Call exactly one tool: wait. Do not call any other tool.",
            None,
            character_id=f"live-{provider}-telemetry",
            tools=_wait_tool_schema(),
        )

    assert call is not None
    assert call.name == "wait"

    attempt = _spans_named(span_exporter, "llm.provider.attempt")[-1]
    _assert_llm_usage_trace_attrs(attempt.attributes, provider, model, "character")
    assert attempt.attributes["llm.tools.count"] == 1
    assert attempt.attributes["llm.system_prompt_chars"] == len(CHARACTER_SYSTEM_PROMPT)

    decide = _spans_named(span_exporter, "live.character.decide")[-1]
    assert decide.attributes["llm.tokens.available"] is True
    assert "llm.tokens.prompt" in decide.attributes
    assert "llm.tokens.completion" in decide.attributes
    assert "llm.tokens.total" in decide.attributes
    assert "llm.cost.available" in decide.attributes

    points = _metric_points(metric_reader)
    _assert_token_metrics_are_consistent(points, provider, model)
    if decide.attributes["llm.cost.available"]:
        assert points["bunnyland.llm.cost"][0].attributes == {
            "provider": provider,
            "model": model,
        }
        assert points["bunnyland.llm.cost"][0].value > 0
    else:
        assert "bunnyland.llm.cost" not in points


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", PROVIDERS)
async def test_live_world_agent_records_history_metrics_and_traces(provider, live_otel_capture):
    span_exporter, metric_reader = live_otel_capture
    agent = _world_agent(provider)
    model = _world_options(provider, max_rooms=1).model

    room = await agent.propose_room(
        "live telemetry test: one tiny room with a short name",
        behind=None,
        known_rooms={},
    )

    assert room.title
    assert room.description

    request = _spans_named(span_exporter, "worldgen.llm.request")[-1]
    _assert_llm_usage_trace_attrs(request.attributes, provider, model, "worldgen")
    assert request.attributes["llm.tools.count"] == 0
    assert request.attributes["instruction.chars"] > 0
    assert request.attributes["llm.tokens.available"] is True
    assert "llm.tokens.prompt" in request.attributes
    assert "llm.tokens.completion" in request.attributes
    assert "llm.tokens.total" in request.attributes
    assert "llm.cost.available" in request.attributes

    points = _metric_points(metric_reader)
    assert "bunnyland.worldgen.request.duration" in points
    _assert_token_metrics_are_consistent(points, provider, model)
    if request.attributes["llm.cost.available"]:
        assert points["bunnyland.llm.cost"][0].attributes == {
            "provider": provider,
            "model": model,
        }
        assert points["bunnyland.llm.cost"][0].value > 0
    else:
        assert "bunnyland.llm.cost" not in points


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
    apply_plugins([plugin for plugin in bunnyland_plugins() if plugin.id == CORE_VERBS], actor)

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


def _chat_endpoint_actor(provider: str) -> tuple[WorldActor, object]:
    actor = WorldActor()
    apply_plugins(
        [plugin for plugin in bunnyland_plugins() if plugin.id in (CORE_VERBS, MEMORY)], actor
    )

    room = spawn_entity(
        actor.world,
        [
            IdentityComponent(name="Live Chat Burrow", kind="room"),
            RoomComponent(
                title="Live Chat Burrow",
                description="A quiet live-test room with soft moss and one patient listener.",
            ),
        ],
    )
    character = spawn_entity(
        actor.world,
        [
            IdentityComponent(name="Juniper", kind="character"),
            CharacterComponent(species="bunny"),
            MemoryProfileComponent(vector_collection="juniper-live-chat"),
            ActionPointsComponent(current=5.0, maximum=5.0, regen_per_hour=5.0),
            FocusPointsComponent(current=3.0, maximum=3.0, regen_per_hour=3.0),
            InitiativeComponent(score=1.0),
        ],
    )
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), character.id)

    controller = spawn_entity(actor.world)
    controller.add_component(
        LLMControllerComponent(
            profile_name="live-chat-test",
            model=_character_model(provider),
            provider=provider,
        )
    )
    actor.assign_controller(character.id, controller.id)
    return actor, character.id


def _contextual_chat_actor(provider: str) -> tuple[WorldActor, object]:
    actor = WorldActor()
    apply_plugins([plugin for plugin in bunnyland_plugins() if plugin.id == CORE_VERBS], actor)

    room = spawn_entity(
        actor.world,
        [
            IdentityComponent(name="Azure Fern Observatory", kind="room"),
            RoomComponent(
                title="Azure Fern Observatory",
                description=(
                    "A glass-roofed live-test observatory filled with blue ferns "
                    "and careful map notes."
                ),
            ),
        ],
    )
    character = spawn_entity(
        actor.world,
        [
            IdentityComponent(name="Juniper", kind="character"),
            CharacterComponent(species="bunny"),
            PersonaProfileComponent(voice="measured and map-minded", role="cartographer"),
            TraitSetComponent(traits=("observant",)),
            PreferenceComponent(likes=("blue ferns",)),
            GoalComponent(active_goals=("chart the moonlit paths",)),
            ActionPointsComponent(current=5.0, maximum=5.0, regen_per_hour=5.0),
            FocusPointsComponent(current=3.0, maximum=3.0, regen_per_hour=3.0),
            InitiativeComponent(score=1.0),
        ],
    )
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), character.id)
    item = spawn_entity(
        actor.world,
        [
            IdentityComponent(name="brass astrolabe", kind="item"),
            PortableComponent(can_pick_up=True),
        ],
    )
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), item.id)

    controller = spawn_entity(actor.world)
    controller.add_component(
        LLMControllerComponent(
            profile_name="live-chat-context-test",
            model=_character_model(provider),
            provider=provider,
        )
    )
    actor.assign_controller(character.id, controller.id)
    return actor, character.id


@pytest.mark.parametrize("provider", PROVIDERS)
def test_live_character_chat_endpoints_use_real_llm(provider):
    testclient = pytest.importorskip("fastapi.testclient")
    actor, character_id = _chat_endpoint_actor(provider)
    service = build_character_chat_service(
        actor,
        PromptBuilder(actor.world),
        _character_agent(provider),
    )
    client = testclient.TestClient(create_app(actor, character_chat=service))

    status = client.get("/world/chat/status")
    assert status.status_code == 200
    status_body = status.json()
    assert status_body["enabled"] is True
    assert set(status_body["allowed_tools"]) == ALLOWED_CHAT_TOOLS
    assert {"remember", "take_note", "reflect", "forget"}.issubset(status_body["allowed_tools"])

    response = client.post(
        f"/world/character/{character_id}/chat",
        json={
            "client_id": f"live-{provider}",
            "message": (
                "Reply in character with one short sentence. Prefer no tool unless "
                "Juniper would naturally choose one."
            ),
            "history_summary": "The human greeted Juniper before this live endpoint test.",
            "history": [
                {"role": "user", "text": "hello"},
                {"role": "character", "text": "quietly, hello"},
            ],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["schema_version"] == 1
    assert body["character_id"] == str(character_id)
    assert body["reply"].strip()
    assert body["action"]["status"] in {
        "none",
        "queued",
        "executed",
        "rejected",
        "unresolved",
        "failed",
    }
    if body["action"]["tool"]:
        assert body["action"]["tool"] in ALLOWED_CHAT_TOOLS


@pytest.mark.parametrize("provider", PROVIDERS)
def test_live_character_chat_take_note_prompt_calls_tool(provider):
    testclient = pytest.importorskip("fastapi.testclient")
    actor, character_id = _chat_endpoint_actor(provider)
    service = build_character_chat_service(
        actor,
        PromptBuilder(actor.world),
        _character_agent(provider),
    )
    client = testclient.TestClient(create_app(actor, character_chat=service))

    response = client.post(
        f"/world/character/{character_id}/chat",
        json={
            "client_id": f"live-note-{provider}",
            "message": (
                "This is critical info. Use your take_note tool now to record exactly this: "
                "the pale plants are a hybrid of human and alien vines that will, given time, "
                "take over the greenhouse. Do not merely describe writing a note; call the "
                "take_note tool."
            ),
            "history_summary": "",
            "history": [],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["action"]["tool"] == "take_note", body["reply"]
    assert body["action"]["status"] in {"queued", "executed"}


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", PROVIDERS)
async def test_live_character_chat_initial_prompt_mentions_room_item_and_profile(provider):
    actor, character_id = _contextual_chat_actor(provider)
    builder = PromptBuilder(
        actor.world,
        persona_providers=collect_persona_fragments(bunnyland_plugins()),
    )
    context_prompt = render_prompt(builder.build(character_id))
    assert "Azure Fern Observatory" in context_prompt
    assert "brass astrolabe" in context_prompt
    assert "Your current role: cartographer." in context_prompt
    assert "You are observant." in context_prompt

    service = build_character_chat_service(actor, builder, _character_agent(provider))
    messages = service._messages(
        context_prompt,
        CharacterChatRequest(
            client_id=f"live-context-{provider}",
            message=(
                "This starts a new conversation. Using only your starting character "
                "context, answer in one sentence containing the exact room name "
                "'Azure Fern Observatory', the exact visible item name "
                "'brass astrolabe', and your exact role 'cartographer'."
            ),
        ),
    )

    reply = await _character_agent(provider).chat(
        messages,
        character_id=str(character_id),
        model=_character_model(provider),
        provider=provider,
        tools=[],
    )
    text = reply.content.lower()

    assert "azure fern observatory" in text
    assert "brass astrolabe" in text
    assert "cartographer" in text


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
