from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

import bunnyland.server.worldgen as server_worldgen
from bunnyland.content import load_content_library
from bunnyland.core import (
    CharacterComponent,
    ContainerComponent,
    ContainmentMode,
    Contains,
    DoorComponent,
    ExitTo,
    IdentityComponent,
    RoomComponent,
    WorldPauseStatusChangedEvent,
    spawn_entity,
)
from bunnyland.core.commands import CommandCost, Lane, OnInsufficientPoints
from bunnyland.core.events import ActorMovedEvent
from bunnyland.engine import GameLoop
from bunnyland.llm_agents import ControllerDispatch, ScriptedAgent
from bunnyland.mechanics.storyteller import IncidentComponent
from bunnyland.persistence import WorldMeta, load_world
from bunnyland.prompts.builder import PromptBuilder
from bunnyland.server import CommandRequest, EventStream, serialize_event, serialize_world
from bunnyland.server import app as server_app
from bunnyland.server.admin import save_configured_world
from bunnyland.server.app import create_app, next_websocket_update
from bunnyland.server.models import (
    WorldCharacterGenerationRequest,
    WorldEventGenerationRequest,
    WorldItemGenerationRequest,
    WorldPatchRequest,
    WorldRoomGenerationRequest,
)
from bunnyland.server.patches import apply_world_patch
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
    assert "/admin/world" in paths
    assert "/admin/world/generate-room" in paths
    assert "/admin/world/generate-character" in paths
    assert "/admin/world/generate-item" in paths
    assert "/admin/world/generate-event" in paths
    assert "/admin/world/save" in paths
    assert "/admin/runtime" in paths
    assert "/admin/pause" in paths
    assert "/admin/resume" in paths
    assert "/world/updates" in paths


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
