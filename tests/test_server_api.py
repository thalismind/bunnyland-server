from __future__ import annotations

import asyncio
import json
import sys
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

import bunnyland.server.worldgen as server_worldgen
from bunnyland.content import load_content_library
from bunnyland.core import (
    CharacterComponent,
    ContainerComponent,
    ContainmentMode,
    Contains,
    ControlledBy,
    DoorComponent,
    ExitTo,
    IdentityComponent,
    RoomComponent,
    SuspendedComponent,
    WebControllerComponent,
    WorldPauseStatusChangedEvent,
    parse_entity_id,
    spawn_entity,
)
from bunnyland.core.commands import CommandCost, Lane, OnInsufficientPoints
from bunnyland.core.controllers import ClaimTimeoutComponent
from bunnyland.core.events import (
    ActorMovedEvent,
    WorldGenerationCompletedEvent,
    WorldGenerationStartedEvent,
)
from bunnyland.engine import GameLoop
from bunnyland.llm_agents import ControllerDispatch, ScriptedAgent
from bunnyland.mechanics.storyteller import IncidentComponent
from bunnyland.persistence import WorldMeta, load_world
from bunnyland.plugins import bunnyland_plugins, select
from bunnyland.prompts.builder import PromptBuilder
from bunnyland.server import CommandRequest, EventStream, serialize_event, serialize_world
from bunnyland.server import app as server_app
from bunnyland.server.admin import (
    generate_replacement_world,
    save_configured_world,
    start_world_generation,
)
from bunnyland.server.app import create_app, next_websocket_update
from bunnyland.server.models import (
    WebControllerClaimRequest,
    WebControllerFallbackRequest,
    WorldCharacterGenerationRequest,
    WorldEventGenerationRequest,
    WorldGenerateRequest,
    WorldItemGenerationRequest,
    WorldPatchRequest,
    WorldRoomGenerationRequest,
)
from bunnyland.server.patches import WorldPatchError, apply_world_patch
from bunnyland.server.runtime import run_loop_with_api
from bunnyland.server.schema import world_schema
from bunnyland.server.worldgen import (
    generate_character_patch,
    generate_event_patch,
    generate_item_patch,
    generate_room_patch,
)
from bunnyland.worldgen import (
    CharacterProposal,
    DoorProposal,
    GenOptions,
    ItemProposal,
    RoomContentsProposal,
    RoomNodeProposal,
    StoryEventProposal,
    collect_generators,
)


def test_world_snapshot_serializes_entities_relationships_and_metadata(scenario):
    meta = WorldMeta(seed="moss", generator="oneshot", plugins=("bunnyland.core_verbs",))

    snapshot = serialize_world(scenario.actor, meta)

    assert snapshot["world_epoch"] == scenario.actor.epoch
    assert snapshot["metadata"]["seed"] == "moss"
    entities = {entity["id"]: entity for entity in snapshot["entities"]}
    room = entities[str(scenario.room_a)]
    character = entities[str(scenario.character)]
    assert room["components"]["RoomComponent"]["title"] == "Mosslit Burrow"
    assert character["components"]["IdentityComponent"]["name"] == "Juniper"
    assert any(
        edge["target_id"] == str(scenario.character)
        for edge in room["relationships"]["Contains"]
    )


def test_editor_display_component_serializes_emoji_for_clients(scenario):
    from bunnyland.core import EditorDisplayComponent

    scenario.actor.world.get_entity(scenario.character).add_component(
        EditorDisplayComponent(emoji="🦊")
    )

    snapshot = serialize_world(scenario.actor)

    entities = {entity["id"]: entity for entity in snapshot["entities"]}
    character = entities[str(scenario.character)]
    assert character["components"]["EditorDisplayComponent"]["emoji"] == "🦊"


def test_command_request_builds_submitted_command():
    request = CommandRequest(
        character_id="entity_1",
        controller_id="entity_2",
        controller_generation=3,
        command_type="move",
        payload={"direction": "north"},
        cost={"action": 1},
        lane=Lane.WORLD,
        on_insufficient_points=OnInsufficientPoints.DENY,
    )

    command = request.to_submitted(submitted_at_epoch=42)

    assert command.character_id == "entity_1"
    assert command.command_type == "move"
    assert command.payload == {"direction": "north"}
    assert command.cost == CommandCost(action=1, focus=0)
    assert command.submitted_at_epoch == 42


async def test_event_stream_records_recent_events_and_fans_out_to_subscribers(scenario):
    stream = EventStream(scenario.actor)
    subscription = stream.subscribe()
    await scenario.actor.submit(
        CommandRequest(
            character_id=str(scenario.character),
            controller_id=str(scenario.controller),
            controller_generation=scenario.generation,
            command_type="move",
            payload={"direction": "north"},
            cost={"action": 1},
        ).to_submitted(submitted_at_epoch=scenario.actor.epoch)
    )

    await scenario.actor.tick(0.0)

    moved = None
    for _ in range(6):
        message = await asyncio.wait_for(subscription.queue.get(), timeout=1.0)
        if message["data"]["event_type"] == "ActorMovedEvent":
            moved = message
            break
    subscription.close()

    assert moved is not None
    assert moved["type"] == "event"
    assert moved["data"]["event"]["to_room_id"] == str(scenario.room_b)
    assert any(
        message["data"]["event_type"] == "ActorMovedEvent"
        for message in stream.recent_messages()
    )


def test_event_serialization_includes_type_and_json_fields(scenario):
    event = ActorMovedEvent(
        event_id="evt",
        world_epoch=7,
        created_at=datetime.now(UTC),
        actor_id=str(scenario.character),
        from_room_id=str(scenario.room_a),
        to_room_id=str(scenario.room_b),
    )

    serialized = serialize_event(event)

    assert serialized["event_type"] == "ActorMovedEvent"
    assert serialized["event"]["world_epoch"] == 7
    assert serialized["event"]["created_at"] is not None


def test_fastapi_app_factory_registers_client_routes_when_extra_is_installed(scenario):
    pytest.importorskip("fastapi")

    loop = GameLoop(
        scenario.actor,
        ControllerDispatch(
            scenario.actor,
            PromptBuilder(scenario.actor.world),
            ScriptedAgent([]),
        ),
    )
    app = create_app(scenario.actor, loop=loop)

    paths = {route.path for route in app.routes}
    assert "/health" in paths
    assert "/world/snapshot" in paths
    assert "/world/schema" in paths
    assert "/world/library" in paths
    assert "/world/events/recent" in paths
    assert "/world/commands" in paths
    assert "/world/controllers/web/claim" in paths
    assert "/world/controllers/web/fallback" in paths
    assert "/admin/world" in paths
    assert "/admin/world/generators" in paths
    assert "/admin/world/generate" in paths
    assert "/admin/world/generate-room" in paths
    assert "/admin/world/generate-character" in paths
    assert "/admin/world/generate-item" in paths
    assert "/admin/world/generate-event" in paths
    assert "/admin/world/save" in paths
    assert "/admin/runtime" in paths
    assert "/admin/pause" in paths
    assert "/admin/resume" in paths
    assert "/world/updates" in paths


async def test_run_loop_with_api_stops_server_when_game_loop_finishes(
    monkeypatch,
    scenario,
):
    servers = []

    class FakeLoop:
        paused = False
        running = True

        async def run(self, *, max_ticks=None):
            self.max_ticks = max_ticks
            return 7

        def stop(self):
            raise AssertionError("server should not stop the loop in this path")

    class FakeServer:
        def __init__(self, config):
            self.config = config
            self.should_exit = False
            self.exited_after_signal = False
            servers.append(self)

        async def serve(self):
            while not self.should_exit:
                await asyncio.sleep(0)
            self.exited_after_signal = True

    monkeypatch.setitem(
        sys.modules,
        "uvicorn",
        SimpleNamespace(Config=lambda app, **kwargs: {"app": app, **kwargs}, Server=FakeServer),
    )
    loop = FakeLoop()

    ticks = await run_loop_with_api(
        loop,
        scenario.actor,
        WorldMeta(seed="runtime"),
        host="127.0.0.1",
        port=8765,
        max_ticks=7,
    )

    assert ticks == 7
    assert loop.max_ticks == 7
    assert servers[0].config["host"] == "127.0.0.1"
    assert servers[0].config["port"] == 8765
    assert servers[0].exited_after_signal is True


async def test_run_loop_with_api_stops_game_when_server_finishes(monkeypatch, scenario):
    class FakeLoop:
        paused = False
        running = True

        def __init__(self) -> None:
            self.stopped = False

        async def run(self, *, max_ticks=None):
            while not self.stopped:
                await asyncio.sleep(0)
            return 3

        def stop(self):
            self.stopped = True

    class FakeServer:
        should_exit = False

        def __init__(self, _config):
            pass

        async def serve(self):
            return None

    monkeypatch.setitem(
        sys.modules,
        "uvicorn",
        SimpleNamespace(Config=lambda app, **kwargs: {"app": app, **kwargs}, Server=FakeServer),
    )
    loop = FakeLoop()

    ticks = await run_loop_with_api(
        loop,
        scenario.actor,
        WorldMeta(seed="runtime"),
        host="127.0.0.1",
        port=8765,
    )

    assert ticks == 3
    assert loop.stopped is True


async def test_web_controller_claim_replaces_llm_controller_and_reuses_client(
    scenario,
):
    app = create_app(scenario.actor)
    route = next(route for route in app.routes if route.path == "/world/controllers/web/claim")

    first = await route.endpoint(
        WebControllerClaimRequest(
            character_id=str(scenario.character),
            client_id="client-a",
            label="toon",
            fallback_controller="llm",
            timeout_seconds=600,
        )
    )
    second = await route.endpoint(
        WebControllerClaimRequest(
            character_id=str(scenario.character),
            client_id="client-a",
            label="toon",
        )
    )

    assert first.controller_id == second.controller_id
    assert first.controller_generation == second.controller_generation
    assert first.controller_generation == scenario.generation + 1

    controller = scenario.actor.world.get_entity(parse_entity_id(first.controller_id))
    assert controller.get_component(WebControllerComponent).client_id == "client-a"
    claim = controller.get_component(ClaimTimeoutComponent)
    assert claim.fallback_controller == "llm"
    assert claim.timeout_seconds == 600
    character = scenario.actor.world.get_entity(scenario.character)
    edge, controller_id = character.get_relationships(ControlledBy)[0]
    assert str(controller_id) == first.controller_id
    assert edge.generation == first.controller_generation


async def test_web_controller_claim_unsuspends_character(scenario):
    app = create_app(scenario.actor)
    route = next(route for route in app.routes if route.path == "/world/controllers/web/claim")
    character = scenario.actor.world.get_entity(scenario.character)
    character.add_component(SuspendedComponent(reason="offline"))

    await route.endpoint(
        WebControllerClaimRequest(
            character_id=str(scenario.character),
            client_id="client-a",
            label="toon",
        )
    )

    assert not character.has_component(SuspendedComponent)


async def test_web_controller_fallback_endpoint_updates_existing_claim(scenario):
    app = create_app(scenario.actor)
    claim_route = next(
        route for route in app.routes if route.path == "/world/controllers/web/claim"
    )
    fallback_route = next(
        route for route in app.routes if route.path == "/world/controllers/web/fallback"
    )

    claimed = await claim_route.endpoint(
        WebControllerClaimRequest(
            character_id=str(scenario.character),
            client_id="client-a",
            label="toon",
        )
    )
    updated = await fallback_route.endpoint(
        WebControllerFallbackRequest(
            character_id=str(scenario.character),
            client_id="client-a",
            fallback_controller="llm",
            llm_model="claim-model",
            timeout_seconds=900,
        )
    )

    assert updated.controller_id == claimed.controller_id
    assert updated.controller_generation == claimed.controller_generation
    assert updated.fallback_controller == "llm"
    assert updated.timeout_seconds == 900
    controller = scenario.actor.world.get_entity(parse_entity_id(updated.controller_id))
    claim = controller.get_component(ClaimTimeoutComponent)
    assert claim.llm_model == "claim-model"


async def test_web_controller_fallback_endpoint_reports_bad_requests(scenario):
    app = create_app(scenario.actor)
    claim_route = next(
        route for route in app.routes if route.path == "/world/controllers/web/claim"
    )
    fallback_route = next(
        route for route in app.routes if route.path == "/world/controllers/web/fallback"
    )
    other = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="Hazel", kind="character"), CharacterComponent()],
    )

    with pytest.raises(Exception) as missing_character:
        await fallback_route.endpoint(
            WebControllerFallbackRequest(character_id="entity_999", client_id="client-a")
        )
    assert missing_character.value.status_code == 404
    assert missing_character.value.detail == "character does not exist"

    with pytest.raises(Exception) as blank_client:
        await fallback_route.endpoint(
            WebControllerFallbackRequest(
                character_id=str(scenario.character),
                client_id=" ",
            )
        )
    assert blank_client.value.status_code == 400
    assert blank_client.value.detail == "client_id must not be blank"

    with pytest.raises(Exception) as missing_controller:
        await fallback_route.endpoint(
            WebControllerFallbackRequest(
                character_id=str(scenario.character),
                client_id="client-a",
            )
        )
    assert missing_controller.value.status_code == 404
    assert missing_controller.value.detail == "web controller does not exist"

    await claim_route.endpoint(
        WebControllerClaimRequest(
            character_id=str(scenario.character),
            client_id="client-a",
        )
    )
    with pytest.raises(Exception) as wrong_character:
        await fallback_route.endpoint(
            WebControllerFallbackRequest(
                character_id=str(other.id),
                client_id="client-a",
            )
        )
    assert wrong_character.value.status_code == 409
    assert wrong_character.value.detail == "web controller is not controlling this character"


def test_admin_save_uses_configured_path_and_meta(scenario, tmp_path):
    path = tmp_path / "admin-save.json"

    response = save_configured_world(
        scenario.actor,
        path,
        meta=WorldMeta(seed="moss", generator="oneshot"),
    )

    assert response.ok is True
    assert response.path == str(path)
    assert response.saved_at_epoch == scenario.actor.epoch
    reloaded, meta = load_world(path)
    assert reloaded.epoch == scenario.actor.epoch
    assert meta.seed == "moss"


async def test_admin_runtime_endpoints_require_attached_loop(scenario):
    app = create_app(scenario.actor)

    for path in ("/admin/runtime", "/admin/pause", "/admin/resume"):
        route = next(route for route in app.routes if route.path == path)
        with pytest.raises(Exception) as exc:
            await route.endpoint()
        assert exc.value.status_code == 409
        assert exc.value.detail == "server runtime is not attached"


async def test_admin_save_endpoint_requires_configured_path(scenario):
    app = create_app(scenario.actor)
    route = next(route for route in app.routes if route.path == "/admin/world/save")

    with pytest.raises(Exception) as exc:
        await route.endpoint()

    assert exc.value.status_code == 409
    assert exc.value.detail == "server was not started with --save"


async def test_admin_world_generate_replaces_world_and_updates_metadata(scenario):
    plugins = select(bunnyland_plugins(), ["bunnyland.worldgen"])
    registry = collect_generators(plugins)
    meta = WorldMeta(seed="old seed", generator="oneshot")
    request = WorldGenerateRequest(seed="crystal cellar", generator="oneshot")
    old_world = scenario.actor.world

    assert request.confirm_reset is False

    response = await generate_replacement_world(
        scenario.actor,
        plugins=plugins,
        generator=registry["oneshot"],
        seed=request.seed,
        options=GenOptions(),
        meta=meta,
    )

    assert response.seed == "crystal cellar"
    assert response.generator == "oneshot"
    assert response.status == "succeeded"
    assert meta.seed == "crystal cellar"
    assert meta.generator == "oneshot"
    assert meta.plugins == ("bunnyland.worldgen",)
    assert scenario.actor.world is not old_world
    assert len(list(scenario.actor.world.query().with_all([RoomComponent]).execute_entities())) == 2
    assert (
        len(
            list(
                scenario.actor.world.query()
                .with_all([CharacterComponent])
                .execute_entities()
            )
        )
        == 2
    )


async def test_admin_world_generate_can_create_empty_world(scenario):
    plugins = select(bunnyland_plugins(), ["bunnyland.worldgen"])
    registry = collect_generators(plugins)
    meta = WorldMeta(seed="old seed", generator="oneshot")

    response = await generate_replacement_world(
        scenario.actor,
        plugins=plugins,
        generator=registry["empty"],
        seed="blank slate",
        options=GenOptions(),
        meta=meta,
    )

    assert response.seed == "blank slate"
    assert response.generator == "empty"
    assert response.status == "succeeded"
    assert scenario.actor.epoch == 0
    assert len(list(scenario.actor.world.query().execute_entities())) == 1


async def test_admin_world_generation_job_starts_and_publishes_completion(scenario):
    plugins = select(bunnyland_plugins(), ["bunnyland.worldgen"])
    registry = collect_generators(plugins)
    meta = WorldMeta(seed="old seed", generator="oneshot")
    started: list[WorldGenerationStartedEvent] = []
    completed: list[WorldGenerationCompletedEvent] = []
    scenario.actor.bus.subscribe(WorldGenerationStartedEvent, started.append)
    scenario.actor.bus.subscribe(WorldGenerationCompletedEvent, completed.append)

    job = await start_world_generation(
        scenario.actor,
        plugins=plugins,
        generator=registry["recursive"],
        seed="slow moss",
        options=GenOptions(max_rooms=3),
        meta=meta,
    )

    assert job.status == "running"
    assert job.response(scenario.actor).status == "running"
    assert started and started[0].job_id == job.job_id
    assert len(list(scenario.actor.world.query().execute_entities())) == 1

    assert job.task is not None
    await job.task

    assert job.status == "succeeded"
    assert job.rooms == 3
    assert job.characters == 2
    assert completed and completed[-1].job_id == job.job_id
    assert job.status_response(scenario.actor).status == "succeeded"


def test_admin_world_generators_lists_enabled_generators(scenario):
    plugins = select(bunnyland_plugins(), ["bunnyland.worldgen"])
    registry = collect_generators(plugins)
    app = create_app(scenario.actor, plugins=plugins)
    paths = {route.path for route in app.routes}
    route = next(route for route in app.routes if route.path == "/admin/world/generators")
    response = asyncio.run(route.endpoint())
    generators = {item.name: item for item in response.generators}

    assert "/admin/world/generators" in paths
    assert "/admin/world/generation" in paths
    assert {"empty", "oneshot", "recursive"} <= set(registry)
    assert generators["empty"].uses_seed is False
    assert generators["oneshot"].uses_seed is True
    assert generators["recursive"].uses_seed is True


async def test_admin_world_generate_defaults_to_recursive_when_available(scenario):
    plugins = select(bunnyland_plugins(), ["bunnyland.worldgen"])
    meta = WorldMeta(seed="old seed", generator="oneshot")
    app = create_app(scenario.actor, meta=meta, plugins=plugins)
    route = next(route for route in app.routes if route.path == "/admin/world/generate")

    response = await route.endpoint(
        WorldGenerateRequest(confirm_reset=True, seed="rain port")
    )

    assert response.generator == "recursive"


async def test_admin_world_generate_endpoint_reports_precondition_errors(scenario):
    app_without_plugins = create_app(scenario.actor)
    route_without_plugins = next(
        route for route in app_without_plugins.routes if route.path == "/admin/world/generate"
    )

    with pytest.raises(Exception) as unconfirmed:
        await route_without_plugins.endpoint(WorldGenerateRequest())
    assert unconfirmed.value.status_code == 400
    assert unconfirmed.value.detail == "confirm_reset must be true"

    with pytest.raises(Exception) as no_registry:
        await route_without_plugins.endpoint(WorldGenerateRequest(confirm_reset=True))
    assert no_registry.value.status_code == 409
    assert no_registry.value.detail == "server was not started with a world generator registry"

    plugins = select(bunnyland_plugins(), ["bunnyland.worldgen"])
    app = create_app(scenario.actor, plugins=plugins)
    route = next(route for route in app.routes if route.path == "/admin/world/generate")

    with pytest.raises(Exception) as unknown:
        await route.endpoint(WorldGenerateRequest(confirm_reset=True, generator="missing"))
    assert unknown.value.status_code == 400
    assert "unknown generator 'missing'" in unknown.value.detail


async def test_admin_patch_endpoint_translates_patch_errors_to_http_400(scenario):
    app = create_app(scenario.actor)
    route = next(route for route in app.routes if route.path == "/admin/world")

    with pytest.raises(Exception) as exc:
        await route.endpoint(
            WorldPatchRequest.model_validate(
                {"operations": [{"op": "delete_entity", "entity_id": "entity_999"}]}
            )
        )

    assert exc.value.status_code == 400
    assert exc.value.detail == "entity 'entity_999' does not exist"


@pytest.mark.parametrize(
    ("path", "payload", "message"),
    [
        (
            "/admin/world/generate-room",
            WorldRoomGenerationRequest(door_entity_id="entity_999"),
            "door entity 'entity_999' does not exist",
        ),
        (
            "/admin/world/generate-character",
            WorldCharacterGenerationRequest(room_entity_id="entity_999"),
            "room entity 'entity_999' does not exist",
        ),
        (
            "/admin/world/generate-item",
            WorldItemGenerationRequest(container_entity_id="entity_999"),
            "container entity 'entity_999' does not exist",
        ),
        (
            "/admin/world/generate-event",
            WorldEventGenerationRequest(room_entity_id="entity_999"),
            "room entity 'entity_999' does not exist",
        ),
    ],
)
async def test_admin_entity_generation_endpoints_translate_patch_errors(
    scenario,
    path,
    payload,
    message,
):
    app = create_app(scenario.actor)
    route = next(route for route in app.routes if route.path == path)

    with pytest.raises(Exception) as exc:
        await route.endpoint(payload)

    assert exc.value.status_code == 400
    assert exc.value.detail == message


def test_world_schema_includes_available_types_and_live_usage(scenario):
    schema = world_schema(scenario.actor)

    assert schema.ok is True
    assert schema.world_epoch == scenario.actor.epoch
    assert "RoomComponent" in schema.components
    assert "IdentityComponent" in schema.components
    assert "Contains" in schema.edges
    room_schema = schema.components["RoomComponent"].json_schema
    assert room_schema["properties"]["title"]["type"] == "string"
    assert "title" in room_schema["required"]
    assert schema.components["RoomComponent"].used is True
    assert schema.components["RoomComponent"].count == 2
    assert schema.edges["Contains"].used is True
    assert schema.edges["Contains"].count == 1


def test_content_library_fragments_are_valid_world_patches(scenario):
    library = load_content_library()

    assert library.fragments
    assert any(fragment.id == "item/three-berries" for fragment in library.fragments)
    for fragment in library.fragments:
        operations = [*fragment.operations]
        if fragment.root_client_id and fragment.attach_edge is not None:
            operations.append(
                {
                    "op": "set_edge",
                    "source_id": str(scenario.room_a),
                    "target_id": fragment.root_client_id,
                    "edge": fragment.attach_edge.model_dump(mode="json"),
                }
            )
        response = apply_world_patch(
            scenario.actor,
            WorldPatchRequest.model_validate({"operations": operations}),
        )
        assert response.ok is True
        assert response.changed_entities


def test_worldgen_passes_live_schema_context_to_dm_entity_generation(scenario, monkeypatch):
    captured = {}

    class CapturingBuilder:
        def propose_room(
            self,
            seed,
            *,
            behind,
            known_rooms,
            schema_context="",
        ):
            del seed, behind, known_rooms
            captured["room"] = schema_context
            return RoomNodeProposal(title="Schema Room")

        def propose_contents(self, room, *, known_rooms, schema_context=""):
            del room, known_rooms
            captured["contents"] = schema_context
            return RoomContentsProposal()

        def propose_doors(self, room, *, schema_context=""):
            del room
            captured["doors"] = schema_context
            return [DoorProposal(direction="north")]

        def propose_character(self, room, *, prompt, known_rooms, schema_context=""):
            del room, prompt, known_rooms
            captured["character"] = schema_context
            return CharacterProposal(name="Schema Bun")

        def propose_item(
            self,
            *,
            container_name,
            container_kind,
            prompt,
            known_rooms,
            schema_context="",
        ):
            del container_name, container_kind, prompt, known_rooms
            captured["item"] = schema_context
            return ItemProposal(name="schema bell")

        def propose_event(self, room, *, prompt, known_rooms, schema_context=""):
            del room, prompt, known_rooms
            captured["event"] = schema_context
            return StoryEventProposal(title="Schema Event")

    monkeypatch.setattr(server_worldgen, "_builder", lambda options: CapturingBuilder())

    door = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="schema east door", kind="door"),
            DoorComponent(open=False),
        ],
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), door.id
    )

    generate_room_patch(
        scenario.actor,
        WorldRoomGenerationRequest(door_entity_id=str(door.id), direction="east"),
        options=GenOptions(llm=True),
    )
    generate_character_patch(
        scenario.actor,
        WorldCharacterGenerationRequest(room_entity_id=str(scenario.room_a), prompt="bun"),
        options=GenOptions(llm=True),
    )
    generate_item_patch(
        scenario.actor,
        WorldItemGenerationRequest(container_entity_id=str(scenario.room_a), prompt="bell"),
        options=GenOptions(llm=True),
    )
    generate_event_patch(
        scenario.actor,
        WorldEventGenerationRequest(room_entity_id=str(scenario.room_a), prompt="rustle"),
        options=GenOptions(llm=True),
    )

    for key in ["room", "contents", "doors", "character", "item", "event"]:
        assert '"RoomComponent"' in captured[key]
        assert '"IdentityComponent"' in captured[key]
        assert '"Contains"' in captured[key]
        assert "item/three-berries" in captured[key]


def test_worldgen_builder_selects_openrouter_world_agent(monkeypatch):
    import bunnyland.worldgen as worldgen
    from bunnyland.server import worldgen as server_worldgen

    captured = {}

    class FakeOpenRouterWorldAgent:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(worldgen, "OpenRouterWorldAgent", FakeOpenRouterWorldAgent)

    builder = server_worldgen._builder(
        GenOptions(
            llm=True,
            provider="openrouter",
            model="openai/gpt-4.1",
            api_key="key",
            server_url="https://example.invalid",
        )
    )

    assert isinstance(builder, FakeOpenRouterWorldAgent)
    assert captured == {
        "model": "openai/gpt-4.1",
        "api_key": "key",
        "server_url": "https://example.invalid",
    }


def test_worldgen_builder_selects_ollama_world_agent(monkeypatch):
    import bunnyland.worldgen as worldgen
    from bunnyland.server import worldgen as server_worldgen

    captured = {}

    class FakeOllamaWorldAgent:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(worldgen, "OllamaWorldAgent", FakeOllamaWorldAgent)

    builder = server_worldgen._builder(
        GenOptions(
            llm=True,
            provider="ollama",
            model="deepseek-v4-pro",
            host="https://ollama.example",
            api_key="key",
        )
    )

    assert isinstance(builder, FakeOllamaWorldAgent)
    assert captured == {
        "model": "deepseek-v4-pro",
        "host": "https://ollama.example",
        "api_key": "key",
    }


def test_world_patch_updates_component_and_edge(scenario):
    response = apply_world_patch(
        scenario.actor,
        WorldPatchRequest.model_validate(
            {
                "operations": [
                    {
                        "op": "set_component",
                        "entity_id": str(scenario.character),
                        "component": {
                            "type": "IdentityComponent",
                            "fields": {
                                "name": "Hazel",
                                "kind": "character",
                                "tags": ["editor"],
                            },
                        },
                    },
                    {
                        "op": "set_edge",
                        "source_id": str(scenario.room_a),
                        "target_id": str(scenario.room_b),
                        "edge": {
                            "type": "ExitTo",
                            "fields": {"direction": "east", "label": "arch"},
                        },
                    },
                ]
            }
        ),
    )

    assert response.ok is True
    character = scenario.actor.world.get_entity(scenario.character)
    identity = character.get_component(IdentityComponent)
    assert identity.name == "Hazel"
    assert identity.tags == ("editor",)
    exits = scenario.actor.world.get_entity(scenario.room_a).get_relationships(ExitTo)
    assert any(edge.direction == "east" and target == scenario.room_b for edge, target in exits)


def test_world_patch_adds_and_deletes_entity(scenario):
    add_response = apply_world_patch(
        scenario.actor,
        WorldPatchRequest.model_validate(
            {
                "operations": [
                    {
                        "op": "add_entity",
                        "components": [
                            {
                                "type": "IdentityComponent",
                                "fields": {"name": "Lantern", "kind": "item"},
                            }
                        ],
                    }
                ]
            }
        ),
    )
    entity_id = add_response.changed_entities[0]["id"]

    delete_response = apply_world_patch(
        scenario.actor,
        WorldPatchRequest.model_validate(
            {"operations": [{"op": "delete_entity", "entity_id": entity_id}]}
        ),
    )

    assert add_response.ok is True
    assert delete_response.ok is True
    assert entity_id in delete_response.deleted_entities


def test_world_patch_can_reference_client_ids_within_one_request(scenario):
    response = apply_world_patch(
        scenario.actor,
        WorldPatchRequest.model_validate(
            {
                "operations": [
                    {
                        "op": "add_entity",
                        "client_id": "$room",
                        "components": [
                            {
                                "type": "RoomComponent",
                                "fields": {"title": "Moonlit Cellar"},
                            }
                        ],
                    },
                    {
                        "op": "set_edge",
                        "source_id": str(scenario.room_a),
                        "target_id": "$room",
                        "edge": {"type": "ExitTo", "fields": {"direction": "down"}},
                    },
                ]
            }
        ),
    )

    assert response.ok is True
    assert len(response.changed_entities) == 2
    exits = scenario.actor.world.get_entity(scenario.room_a).get_relationships(ExitTo)
    assert any(edge.direction == "down" for edge, _target in exits)


@pytest.mark.parametrize(
    ("operation", "message"),
    [
        (
            {"op": "delete_entity", "entity_id": "entity_999"},
            "entity 'entity_999' does not exist",
        ),
        (
            {
                "op": "add_entity",
                "components": [{"type": "MissingComponent", "fields": {}}],
            },
            "unknown component 'MissingComponent'",
        ),
        (
            {
                "op": "add_entity",
                "components": [
                    {"type": "IdentityComponent", "fields": {"name": "bad"}}
                ],
            },
            "invalid IdentityComponent",
        ),
        (
            {
                "op": "remove_component",
                "entity_id": "$character",
                "component_type": "MissingComponent",
            },
            "unknown component 'MissingComponent'",
        ),
        (
            {
                "op": "set_edge",
                "source_id": "$room",
                "target_id": "$character",
                "edge": {"type": "MissingEdge", "fields": {}},
            },
            "unknown edge 'MissingEdge'",
        ),
        (
            {
                "op": "set_edge",
                "source_id": "$room",
                "target_id": "$character",
                "edge": {"type": "Contains", "fields": {"mode": "somewhere"}},
            },
            "invalid Contains",
        ),
        (
            {
                "op": "remove_edge",
                "source_id": "$room",
                "target_id": "$character",
                "edge_type": "MissingEdge",
            },
            "unknown edge 'MissingEdge'",
        ),
    ],
)
def test_world_patch_reports_validation_errors(scenario, operation, message):
    aliases = {
        "$room": str(scenario.room_a),
        "$character": str(scenario.character),
    }
    rendered = json.loads(json.dumps(operation))
    for key in ("entity_id", "source_id", "target_id"):
        if rendered.get(key) in aliases:
            rendered[key] = aliases[rendered[key]]

    with pytest.raises(WorldPatchError, match=message):
        apply_world_patch(
            scenario.actor,
            WorldPatchRequest.model_validate({"operations": [rendered]}),
        )


def test_world_patch_rejects_duplicate_client_entity_ids(scenario):
    with pytest.raises(WorldPatchError, match="duplicate client entity id '\\$new'"):
        apply_world_patch(
            scenario.actor,
            WorldPatchRequest.model_validate(
                {
                    "operations": [
                        {"op": "add_entity", "client_id": "$new"},
                        {"op": "add_entity", "client_id": "$new"},
                    ]
                }
            ),
        )


def test_worldgen_room_patch_expands_selected_door(scenario):
    door = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="east door", kind="door"),
            DoorComponent(open=False),
        ],
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), door.id
    )

    generated = generate_room_patch(
        scenario.actor,
        WorldRoomGenerationRequest(
            door_entity_id=str(door.id),
            prompt="Moonlit Cellar",
        ),
    )
    response = apply_world_patch(scenario.actor, generated.patch)

    assert generated.generated_title == "Moonlit Cellar"
    assert response.ok is True
    assert scenario.actor.world.get_entity(door.id).get_component(DoorComponent).open is True
    exits = scenario.actor.world.get_entity(scenario.room_a).get_relationships(ExitTo)
    target_ids = [target for edge, target in exits if edge.direction == "east"]
    assert target_ids
    assert scenario.actor.world.get_entity(target_ids[0]).has_component(RoomComponent)


def test_worldgen_character_patch_places_character_in_selected_room(scenario):
    generated = generate_character_patch(
        scenario.actor,
        WorldCharacterGenerationRequest(
            room_entity_id=str(scenario.room_a),
            prompt="Mossy Sage",
        ),
    )
    response = apply_world_patch(scenario.actor, generated.patch)

    assert generated.generated_name == "Mossy Sage"
    room_contains = scenario.actor.world.get_entity(scenario.room_a).get_relationships(
        Contains
    )
    character_ids = [
        target
        for edge, target in room_contains
        if edge.mode == ContainmentMode.ROOM_CONTENT
        and scenario.actor.world.get_entity(target).has_component(CharacterComponent)
    ]
    assert response.ok is True
    assert len(character_ids) == 2


def test_worldgen_item_patch_accepts_room_character_and_container_destinations(scenario):
    chest = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="oak chest", kind="container"),
            ContainerComponent(open=True),
        ],
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), chest.id
    )

    for container_id, prompt, mode in [
        (scenario.room_a, "a sun coin", ContainmentMode.ROOM_CONTENT),
        (scenario.character, "a pocket map", ContainmentMode.INVENTORY),
        (chest.id, "a brass key", ContainmentMode.CONTAINER),
    ]:
        generated = generate_item_patch(
            scenario.actor,
            WorldItemGenerationRequest(
                container_entity_id=str(container_id),
                prompt=prompt,
            ),
        )
        apply_world_patch(scenario.actor, generated.patch)
        relationships = scenario.actor.world.get_entity(container_id).get_relationships(Contains)
        assert any(
            edge.mode == mode
            and scenario.actor.world.get_entity(target).get_component(IdentityComponent).name
            == generated.generated_name
            for edge, target in relationships
        )


def test_worldgen_event_patch_frames_story_event_as_ecs(scenario):
    generated = generate_event_patch(
        scenario.actor,
        WorldEventGenerationRequest(
            room_entity_id=str(scenario.room_a),
            prompt="a bell rings",
        ),
    )
    response = apply_world_patch(scenario.actor, generated.patch)

    assert generated.generated_title == "a bell rings"
    assert response.ok is True
    room_contains = scenario.actor.world.get_entity(scenario.room_a).get_relationships(
        Contains
    )
    incidents = [
        scenario.actor.world.get_entity(target)
        for _edge, target in room_contains
        if scenario.actor.world.get_entity(target).has_component(IncidentComponent)
    ]
    assert incidents
    incident = incidents[0].get_component(IncidentComponent)
    assert incident.room_id == str(scenario.room_a)
    assert incident.kind == "story_event"
    assert any(
        scenario.actor.world.get_entity(target).get_component(IdentityComponent).name
        == "a dropped clue"
        for _edge, target in room_contains
        if scenario.actor.world.get_entity(target).has_component(IdentityComponent)
    )


async def test_websocket_updates_send_snapshot_and_heartbeat(scenario, monkeypatch):
    monkeypatch.setattr(server_app, "WEBSOCKET_HEARTBEAT_SECONDS", 0.01)

    stream = EventStream(scenario.actor)
    subscription = stream.subscribe()
    try:
        snapshot = {"type": "snapshot", "data": serialize_world(scenario.actor)}
        heartbeat = await next_websocket_update(scenario.actor, subscription)
    finally:
        subscription.close()

    assert snapshot["type"] == "snapshot"
    assert snapshot["data"]["world_epoch"] == scenario.actor.epoch
    assert heartbeat == {"type": "heartbeat", "data": {"world_epoch": scenario.actor.epoch}}


async def test_event_stream_fans_out_pause_status_events(scenario):
    loop = GameLoop(
        scenario.actor,
        ControllerDispatch(
            scenario.actor,
            PromptBuilder(scenario.actor.world),
            ScriptedAgent([]),
        ),
    )
    stream = EventStream(scenario.actor)
    subscription = stream.subscribe()
    try:
        publish = loop.pause()
        if publish is not None:
            await publish
        message = await asyncio.wait_for(subscription.queue.get(), timeout=1.0)
    finally:
        subscription.close()

    assert message["type"] == "event"
    assert message["data"]["event_type"] == "WorldPauseStatusChangedEvent"
    assert message["data"]["event"]["paused"] is True
    assert message["data"]["event"]["message"] == "World paused."
    assert any(
        recent["data"]["event_type"] == WorldPauseStatusChangedEvent.__name__
        for recent in stream.recent_messages()
    )
