from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from bunnyland.core import (
    CharacterComponent,
    ContainerComponent,
    ContainmentMode,
    Contains,
    DoorComponent,
    ExitTo,
    IdentityComponent,
    RoomComponent,
    spawn_entity,
)
from bunnyland.core.commands import CommandCost, Lane, OnInsufficientPoints
from bunnyland.core.events import ActorMovedEvent
from bunnyland.engine import GameLoop
from bunnyland.llm_agents import ControllerDispatch, ScriptedAgent
from bunnyland.persistence import WorldMeta, load_world
from bunnyland.prompts.builder import PromptBuilder
from bunnyland.server import CommandRequest, EventStream, serialize_event, serialize_world
from bunnyland.server import app as server_app
from bunnyland.server.admin import save_configured_world
from bunnyland.server.app import create_app
from bunnyland.server.models import (
    WorldCharacterGenerationRequest,
    WorldItemGenerationRequest,
    WorldPatchRequest,
    WorldRoomGenerationRequest,
)
from bunnyland.server.patches import apply_world_patch
from bunnyland.server.worldgen import (
    generate_character_patch,
    generate_item_patch,
    generate_room_patch,
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
    assert "/world/events/recent" in paths
    assert "/world/commands" in paths
    assert "/admin/world" in paths
    assert "/admin/world/generate-room" in paths
    assert "/admin/world/generate-character" in paths
    assert "/admin/world/generate-item" in paths
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


def test_websocket_updates_send_snapshot_and_heartbeat(scenario, monkeypatch):
    pytest.importorskip("fastapi")
    testclient = pytest.importorskip("fastapi.testclient")
    monkeypatch.setattr(server_app, "WEBSOCKET_HEARTBEAT_SECONDS", 0.01)

    app = create_app(scenario.actor)

    with testclient.TestClient(app) as client:
        with client.websocket_connect("/world/updates") as websocket:
            snapshot = websocket.receive_json()
            heartbeat = websocket.receive_json()

    assert snapshot["type"] == "snapshot"
    assert snapshot["data"]["world_epoch"] == scenario.actor.epoch
    assert heartbeat == {"type": "heartbeat", "data": {"world_epoch": scenario.actor.epoch}}
