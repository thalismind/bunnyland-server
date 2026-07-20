from __future__ import annotations

import asyncio
import json
import sys
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import urlsplit

import httpx
import pytest
from conftest import build_scenario

import bunnyland.server.worldgen as server_worldgen
from bunnyland.claims import (
    ClaimSecretRegistry,
    add_claim,
    current_controller,
    remove_claim,
    transfer_claim,
)
from bunnyland.content import load_content_library
from bunnyland.core import (
    ActionArgument,
    ActionDefinition,
    BehaviorControllerComponent,
    CharacterComponent,
    ClaimedComponent,
    ContainerComponent,
    ContainmentMode,
    Contains,
    ControlledBy,
    DescriptionComponent,
    DiscordControllerComponent,
    DoorComponent,
    DropHandler,
    ExitTo,
    Holding,
    IdentityComponent,
    LLMControllerComponent,
    LockableComponent,
    MCPControllerComponent,
    MemoryProfileComponent,
    MutationPlan,
    PerceptionComponent,
    PortableComponent,
    PutHandler,
    RoomComponent,
    ScriptedControllerComponent,
    StealthComponent,
    SuspendedComponent,
    SuspendedControllerComponent,
    TakeHandler,
    TellHandler,
    Wearing,
    WebControllerComponent,
    WorldActor,
    WorldPauseStatusChangedEvent,
    build_submitted_command,
    parse_entity_id,
    replace_component,
    spawn_entity,
)
from bunnyland.core.commands import CommandCost, Lane, OnInsufficientPoints
from bunnyland.core.components import (
    AffectComponent,
    AffectDelta,
    AffectVector,
    BleedingComponent,
    BodyPlanComponent,
    DeadComponent,
    DownedComponent,
    HealthComponent,
    InjuryComponent,
    PainComponent,
    SleepingComponent,
    ThoughtComponent,
    WeightComponent,
)
from bunnyland.core.controllers import ClaimTimeoutComponent
from bunnyland.core.edges import HasInjury, HasThought
from bunnyland.core.events import (
    ActorMovedEvent,
    WorldGenerationCompletedEvent,
    WorldGenerationFailedEvent,
    WorldGenerationStartedEvent,
)
from bunnyland.core.handlers import planned
from bunnyland.discord.components import DiscordRoomFeedComponent
from bunnyland.engine import GameLoop
from bunnyland.foundation.meters.mechanics import Meter
from bunnyland.foundation.needs.mechanics import HungerComponent, ThirstComponent
from bunnyland.foundation.persona.mechanics import (
    GoalComponent,
    PersonaProfileComponent,
    PreferenceComponent,
    TraitSetComponent,
)
from bunnyland.foundation.social.mechanics import SocialBond, create_obligation
from bunnyland.foundation.social.queries import SOCIAL_PERSPECTIVE_QUERIES
from bunnyland.foundation.storyteller.mechanics import IncidentComponent
from bunnyland.imagegen.service import ImageGenJob
from bunnyland.imagegen.spec import ImagePurpose
from bunnyland.llm_agents import ControllerDispatch, ScriptedAgent
from bunnyland.llm_agents.specs import BehaviorNodeSpec, BehaviorTreeSpec, ScriptSpec, ToolCallSpec
from bunnyland.memory import InMemoryStore, install_memory
from bunnyland.persistence import WorldMeta, load_world
from bunnyland.plugins import (
    HttpContribution,
    HttpZone,
    Plugin,
    PluginRegistry,
    RuntimeContribution,
    bunnyland_plugins,
    select,
)
from bunnyland.plugins.ids import MCP
from bunnyland.prompts.builder import PromptBuilder
from bunnyland.server import (
    CommandRequest,
    EventStream,
    serialize_character_projection,
    serialize_character_queued_commands,
    serialize_dm_projection,
    serialize_event,
    serialize_room_projection,
    serialize_world,
)
from bunnyland.server import admin as server_admin
from bunnyland.server import app as server_app
from bunnyland.server.admin import (
    generate_replacement_world,
    save_configured_world,
    start_world_generation,
)
from bunnyland.server.app import (
    AuthorizationSurface,
    classify_authorization_surface,
    next_player_update,
    next_websocket_update,
    player_update_for_message,
    recent_player_updates,
    route_surface_matrix,
)
from bunnyland.server.app import (
    create_app as _create_app,
)
from bunnyland.server.auth import WORLD_ADMIN_SCOPE, WORLD_PLAY_SCOPE, TokenStore
from bunnyland.server.client_ids import CLIENT_ID_HEADER
from bunnyland.server.models import (
    CharacterChatResponse,
    ClientTargetView,
    MemoryDocumentUpdateRequest,
    WorldCharacterGenerationRequest,
    WorldEventGenerationRequest,
    WorldGenerateRequest,
    WorldItemGenerationRequest,
    WorldPatchRequest,
    WorldRoomGenerationRequest,
    WorldRoomGenerationResponse,
)
from bunnyland.server.patches import WorldPatchError, apply_world_patch
from bunnyland.server.rate_limit import FixedWindowRateLimiter
from bunnyland.server.runtime import run_loop_with_api
from bunnyland.server.schema import _type_schema, world_schema
from bunnyland.server.serialization import jsonable, serialize_world_overview
from bunnyland.server.v1_models import (
    ChatJobRequest,
    CheckpointRequest,
    ClaimCommandRequest,
    ClaimControlUpdate,
    ClaimCreateRequest,
    ClaimFallbackUpdate,
    ControllerAssignment,
    ControllerDefinitionRequest,
    GenerateCharacterRequest,
    GenerateEventRequest,
    GenerateImageRequest,
    GenerateItemRequest,
    GenerateRoomRequest,
    GenerateWorldRequest,
    RuntimePatchRequest,
)
from bunnyland.server.worldgen import (
    _room_description,
    build_character_generation_response,
    build_event_generation_response,
    build_room_generation_response,
    collect_container_selection_context,
    collect_room_expansion_context,
    collect_room_selection_context,
    generate_character_patch,
    generate_event_patch,
    generate_item_patch,
    generate_room_patch,
)
from bunnyland.simpacks.lifesim.mechanics import (
    AgeComponent,
    AspirationComponent,
    CareerComponent,
    CharacterProfileComponent,
    HouseholdComponent,
    LifeStageComponent,
    PregnancyComponent,
    ReputationComponent,
    SkillSetComponent,
    WellRestedComponent,
    WhimComponent,
)
from bunnyland.simpacks.toonsim.mechanics import (
    SpriteBoundsComponent,
    SpriteImageComponent,
    SpriteLayerComponent,
    SpritePositionComponent,
    SpriteScaleComponent,
    ToonRoomComponent,
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


class _SyncASGIClient:
    """Small HTTP-only ASGI test client that avoids Starlette TestClient's portal startup."""

    def __init__(self, app, headers: dict[str, str] | None = None, **_kwargs) -> None:
        self.app = app
        self.headers = _bearer_test_headers(headers)
        self._websocket_clients = []

    def __enter__(self):
        return self

    def __exit__(self, *_exc_info):
        return False

    def request(self, method: str, url: str, **kwargs):
        if "headers" in kwargs:
            kwargs["headers"] = _bearer_test_headers(kwargs["headers"])

        async def run_request():
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=self.app),
                base_url="http://testserver",
                headers=self.headers,
            ) as client:
                return await client.request(method, url, **kwargs)

        return asyncio.run(run_request())

    def get(self, url: str, **kwargs):
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs):
        return self.request("POST", url, **kwargs)

    def put(self, url: str, **kwargs):
        return self.request("PUT", url, **kwargs)

    def patch(self, url: str, **kwargs):
        return self.request("PATCH", url, **kwargs)

    def delete(self, url: str, **kwargs):
        return self.request("DELETE", url, **kwargs)

    def options(self, url: str, **kwargs):
        return self.request("OPTIONS", url, **kwargs)

    def websocket_connect(self, *args, **kwargs):
        if _FASTAPI_TESTCLIENT is None:
            pytest.importorskip("fastapi.testclient")
        client = _FASTAPI_TESTCLIENT(self.app, headers=self.headers)
        self._websocket_clients.append(client)
        return client.websocket_connect(*args, **kwargs)


try:
    import fastapi.testclient as _fastapi_testclient

    _FASTAPI_TESTCLIENT = _fastapi_testclient.TestClient
except ImportError:
    _FASTAPI_TESTCLIENT = None


@pytest.fixture(autouse=True)
def _use_sync_asgi_test_client(monkeypatch):
    if _FASTAPI_TESTCLIENT is None:
        return
    import fastapi.testclient as fastapi_testclient

    monkeypatch.setattr(fastapi_testclient, "TestClient", _SyncASGIClient)


async def _websocket_outputs(
    app,
    path: str,
    *,
    headers: dict[str, str] | None = None,
    messages: list[dict] | None = None,
):
    from asgiref.testing import ApplicationCommunicator

    split = urlsplit(path)
    scope = {
        "type": "websocket",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "scheme": "ws",
        "path": split.path,
        "raw_path": split.path.encode(),
        "query_string": split.query.encode(),
        "headers": [
            (key.lower().encode(), value.encode())
            for key, value in _bearer_test_headers(headers).items()
        ],
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
        "subprotocols": [],
    }
    communicator = ApplicationCommunicator(app, scope)
    await communicator.send_input({"type": "websocket.connect"})
    outputs = [await communicator.receive_output(timeout=1)]
    if outputs[0]["type"] == "websocket.accept":
        for message in messages or ():
            await communicator.send_input(
                {"type": "websocket.receive", "text": json.dumps(message)}
            )
        outputs.append(await communicator.receive_output(timeout=1))
        await communicator.send_input({"type": "websocket.disconnect", "code": 1000})
    await communicator.wait(timeout=1)
    return outputs


# Test helper for routes that need an operator principal. Product code has no alternate
# credential path: authenticated embeddings receive the same opaque tokens as clients.
_ADMIN_HEADERS: dict[str, str] = {}
_ADMIN_CLIENT_HEADERS = {
    CLIENT_ID_HEADER: "admin-a",
}


def _bearer_test_headers(headers: dict[str, str] | None) -> dict[str, str]:
    return dict(headers or {})


def create_app(*args, **kwargs):
    use_admin = kwargs.pop("with_admin", False)
    if use_admin and kwargs.get("token_store") is None:
        store = TokenStore(":memory:")
        token, _principal = store.issue(
            "test-operator",
            (WORLD_PLAY_SCOPE, WORLD_ADMIN_SCOPE),
            automatic_rotation=False,
        )
        kwargs["token_store"] = store
        _ADMIN_HEADERS.clear()
        _ADMIN_HEADERS["Authorization"] = f"Bearer {token}"
        _ADMIN_HEADERS[CLIENT_ID_HEADER] = "admin-a"
        _ADMIN_CLIENT_HEADERS.clear()
        _ADMIN_CLIENT_HEADERS.update(_ADMIN_HEADERS)
        _ADMIN_CLIENT_HEADERS[CLIENT_ID_HEADER] = "admin-a"
    elif kwargs.get("token_store") is None:
        # This module exercises route behavior as an explicit unauthenticated library
        # embedding. Authentication behavior itself is covered in tests/test_auth.py.
        kwargs["allow_unauthenticated_embedding"] = True
    app = _create_app(*args, **kwargs)
    if use_admin:
        player_token, _principal = kwargs["token_store"].issue(
            "test-player", (WORLD_PLAY_SCOPE,), automatic_rotation=False
        )
        app.state.test_player_headers = {"Authorization": f"Bearer {player_token}"}
    return app


def _claim_headers(client_id: str, secret: str | None = None) -> dict[str, str]:
    headers = {CLIENT_ID_HEADER: client_id}
    if secret is not None:
        headers["X-Bunnyland-Claim-Secret"] = secret
    return headers


def _create_claim(
    client,
    request: ClaimCreateRequest,
    *,
    client_id: str = "client-a",
):
    response = client.post(
        "/v1/play/claims",
        headers=_claim_headers(client_id),
        json=request.model_dump(mode="json", exclude_none=True),
    )
    assert response.status_code == 201, response.text
    return response.json(), response.headers["X-Bunnyland-Claim-Secret"]


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
        edge["target_id"] == str(scenario.character) for edge in room["relationships"]["Contains"]
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


def test_world_snapshot_serializes_queued_commands(scenario):
    command = CommandRequest(
        character_id=str(scenario.character),
        controller_id=str(scenario.controller),
        controller_generation=scenario.generation,
        command_type="say",
        payload={"text": "hold on"},
        cost={"action": 1, "focus": 1},
        lane=Lane.WORLD,
        command_id="cmd-waiting",
    ).to_submitted(submitted_at_epoch=42)
    scenario.actor.queues.enqueue(command)

    snapshot = serialize_world(scenario.actor)

    assert snapshot["queued_commands"] == [
        {
            "command_id": "cmd-waiting",
            "character_id": str(scenario.character),
            "command_type": "say",
            "payload": {"text": "hold on"},
            "cost": {"action": 1, "focus": 1},
            "lane": "world",
            "submitted_at_epoch": 42,
            "expires_at_epoch": None,
        }
    ]


def test_world_snapshot_serializes_pending_submitted_commands_before_tick(scenario):
    command = CommandRequest(
        character_id=str(scenario.character),
        controller_id=str(scenario.controller),
        controller_generation=scenario.generation,
        command_type="say",
        payload={"text": "next tick"},
        cost={"action": 1, "focus": 1},
        lane=Lane.WORLD,
        command_id="cmd-next-tick",
    ).to_submitted(submitted_at_epoch=42)
    scenario.actor.submit_nowait(command)

    snapshot = serialize_world(scenario.actor)

    assert snapshot["queued_commands"] == [
        {
            "command_id": "cmd-next-tick",
            "character_id": str(scenario.character),
            "command_type": "say",
            "payload": {"text": "next tick"},
            "cost": {"action": 1, "focus": 1},
            "lane": "world",
            "submitted_at_epoch": 42,
            "expires_at_epoch": None,
        }
    ]


def test_client_view_scopes_visible_state_points_controller_and_actions(scenario):
    world = scenario.actor.world
    visible_item = spawn_entity(
        world,
        [
            IdentityComponent(name="a loose pebble", kind="item"),
            PortableComponent(),
        ],
    )
    hidden_item = spawn_entity(
        world,
        [
            IdentityComponent(name="hidden ledger", kind="item"),
            PortableComponent(),
            StealthComponent(hiding=True, visibility_level=0.0),
        ],
    )
    remote_item = spawn_entity(
        world,
        [
            IdentityComponent(name="remote candle", kind="item"),
            PortableComponent(),
        ],
    )
    carried_item = spawn_entity(
        world,
        [
            IdentityComponent(name="brass key", kind="item"),
            PortableComponent(),
        ],
    )
    world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), visible_item.id
    )
    world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), hidden_item.id
    )
    world.get_entity(scenario.room_b).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), remote_item.id
    )
    world.get_entity(scenario.character).add_relationship(
        Contains(mode=ContainmentMode.INVENTORY), carried_item.id
    )

    view = serialize_character_projection(scenario.actor, str(scenario.character)).model_dump(
        mode="json"
    )

    assert view["character_id"] == str(scenario.character)
    assert view["character_name"] == "Juniper"
    assert view["room"]["id"] == str(scenario.room_a)
    assert view["points"] == {
        "action": 5.0,
        "action_max": 5.0,
        "focus": 3.0,
        "focus_max": 3.0,
    }
    assert view["controller"] == {
        "controller_id": str(scenario.controller),
        "generation": scenario.generation,
        "kind": "llm",
        "name": "default",
        "detail": "ollama/claude",
    }
    rendered = json.dumps(view)
    assert "a loose pebble" in rendered
    assert "brass key" in rendered
    assert "hidden ledger" not in rendered
    assert "remote candle" not in rendered
    assert "components" not in rendered
    assert "relationships" not in rendered
    assert {target["id"] for target in view["target_groups"]["roomItems"]} == {str(visible_item.id)}
    assert {target["id"] for target in view["target_groups"]["inventory"]} == {str(carried_item.id)}
    move = next(action for action in view["actions"] if action["command_type"] == "move")
    assert move["cost"] == {"action": 1, "focus": 0}
    assert any(
        argument["key"] == "exit_id" and argument["target_group"] == "exits"
        for argument in move["arguments"]
    )


def test_client_view_describes_controller_identity(scenario):
    actor = scenario.actor
    world = actor.world

    def assign_and_view(components):
        controller = spawn_entity(world, components)
        generation = actor.assign_controller(scenario.character, controller.id)
        view = serialize_character_projection(actor, str(scenario.character)).model_dump(
            mode="json"
        )
        return generation, view["controller"]

    cases = [
        (
            [DiscordControllerComponent(discord_user_id=42, default_channel_id=99)],
            "discord",
            "Discord user 42",
            "channel 99",
        ),
        (
            [WebControllerComponent(client_id="tab-1", label="Toon Client")],
            "web",
            "Toon Client",
            "tab-1",
        ),
        ([WebControllerComponent(client_id="web", label="web")], "web", "web", ""),
        (
            [MCPControllerComponent(client_id="agent-1", label="Operator")],
            "mcp",
            "Operator",
            "agent-1",
        ),
        ([MCPControllerComponent(client_id="agent-2", label="")], "mcp", "agent-2", ""),
        (
            [LLMControllerComponent(profile_name="guide", model="mixtral")],
            "llm",
            "guide",
            "ollama/mixtral",
        ),
        (
            [LLMControllerComponent(profile_name="guide", model="", provider="openai")],
            "llm",
            "guide",
            "openai",
        ),
        (
            [BehaviorControllerComponent(behavior_name="patrol", act_every_ticks=2)],
            "behavior",
            "patrol",
            "every 2 tick(s)",
        ),
        (
            [ScriptedControllerComponent(script_name="morning", loop=True)],
            "scripted",
            "morning",
            "looping",
        ),
        ([ScriptedControllerComponent(script_name="", loop=False)], "scripted", "scripted", ""),
        ([SuspendedControllerComponent(reason="offline")], "suspended", "Suspended", "offline"),
        (
            [IdentityComponent(name="custom controller", kind="controller")],
            "",
            "custom controller",
            "",
        ),
    ]
    for components, kind, name, detail in cases:
        generation, controller = assign_and_view(components)
        assert controller == {
            "controller_id": controller["controller_id"],
            "generation": generation,
            "kind": kind,
            "name": name,
            "detail": detail,
        }


def test_character_projection_includes_curated_character_sheet_data(scenario):
    actor = scenario.actor
    world = actor.world
    character = world.get_entity(scenario.character)
    replace_component(
        character,
        CharacterComponent(species="hare", biography="A careful tunnel scout."),
    )
    replace_component(
        character,
        IdentityComponent(name="Juniper", kind="character", tags=("scout", "local")),
    )
    character.add_component(
        DescriptionComponent(
            short="Dusty from a long patrol.",
            appearance="Long ears, patched satchel, steady eyes.",
        )
    )
    character.add_component(HealthComponent(current=7.0, maximum=10.0))
    character.add_component(PainComponent(current=4.0))
    character.add_component(BleedingComponent(rate=1.5))
    character.add_component(BodyPlanComponent(parts=("head", "torso", "paws")))
    character.add_component(WeightComponent(weight=42.0))
    character.add_component(
        InjuryComponent(body_part="right ear", severity=1.0, pain=1.5, bleeding_rate=0.0)
    )
    character.add_component(HungerComponent(meter=Meter(value=75.0)))
    character.add_component(ThirstComponent(meter=Meter(value=20.0)))
    character.add_component(
        AffectComponent(
            current=AffectVector(stress=12.0, curiosity=5.0),
            labels=("tense",),
        )
    )
    character.add_component(LifeStageComponent(stage="adult"))
    character.add_component(AgeComponent(born_at_epoch=-(22 * 365 * 24 * 60 * 60)))
    character.add_component(CareerComponent(title="Scout", level=3))
    character.add_component(
        AspirationComponent(name="Map the burrow", completed=("Find north tunnel",))
    )
    character.add_component(HouseholdComponent(household_id="warren-1"))
    character.add_component(ReputationComponent(score=4.0, known_for=("reliable",)))
    character.add_component(
        SkillSetComponent(levels={"survival": 3, "lockpicking": 1}, xp={"survival": 8.5})
    )
    character.add_component(
        CharacterProfileComponent(
            traits=("watchful",),
            interests=("moss maps",),
            preferred_routine="morning patrol",
        )
    )
    character.add_component(PersonaProfileComponent(role="pathfinder", voice="quiet"))
    character.add_component(TraitSetComponent(traits=("curious", "patient")))
    character.add_component(PreferenceComponent(likes=("tea",), dislikes=("floods",)))
    character.add_component(GoalComponent(active_goals=("keep everyone safe",)))
    character.add_component(WhimComponent(want="check the north door"))
    character.add_component(PregnancyComponent(started_at_epoch=0, due_at_epoch=500))
    character.add_component(WellRestedComponent(expires_at_epoch=100))
    character.add_component(SuspendedComponent())
    character.add_component(SleepingComponent(started_at_epoch=0))
    character.add_component(DownedComponent(downed_at_epoch=0, cause="test", stable=True))
    character.add_component(DeadComponent(died_at_epoch=0, cause="test"))

    injury = spawn_entity(
        world,
        [InjuryComponent(body_part="left paw", severity=2.0, pain=3.0, bleeding_rate=1.0)],
    )
    character.add_relationship(HasInjury(), injury.id)
    thought = spawn_entity(
        world,
        [
            ThoughtComponent(
                label="worried",
                text="The tunnel roof is groaning.",
                affect_delta=AffectDelta(stress=3.0),
                created_at_epoch=0,
            )
        ],
    )
    character.add_relationship(HasThought(), thought.id)
    marlow = spawn_entity(
        world,
        [IdentityComponent(name="Marlow", kind="character"), CharacterComponent()],
    )
    character.add_relationship(SocialBond(trust=4.0, familiarity=2.0), marlow.id)

    view = serialize_character_projection(actor, str(scenario.character)).model_dump(mode="json")
    sheet = view["sheet"]

    assert sheet["species"] == "hare"
    assert sheet["biography"] == "A careful tunnel scout."
    assert sheet["description"] == "Dusty from a long patrol."
    assert sheet["appearance"] == "Long ears, patched satchel, steady eyes."
    assert sheet["tags"] == ["scout", "local"]
    assert {
        "dead",
        "downed (stable)",
        "sleeping",
        "suspended",
        "pregnant",
        "well rested",
        "tense",
    } <= set(sheet["status"])
    assert {row["label"]: row["text"] for row in sheet["vitals"]}["Health"] == "7 / 10"
    assert {row["label"]: row["band"] for row in sheet["needs"]}["Hunger"] == "urgent"
    assert {row["label"]: row["text"] for row in sheet["affect"]}["Stress"] == "12"
    assert {row["label"]: row["value"] for row in sheet["profile"]}["Career"] == "Scout"
    assert {row["label"]: row["value"] for row in sheet["skills"]}["Survival"] == "level 3"
    assert "goal: keep everyone safe" in sheet["traits"]
    assert any(
        row["label"] == "Social Bond" and row["value"] == "Marlow" for row in sheet["relations"]
    )
    assert any(row["label"] == "left paw" for row in sheet["injuries"])
    assert any(row["label"] == "Thought" and row["value"] == "worried" for row in sheet["notes"])

    rendered = json.dumps(view)
    assert "components" not in rendered
    assert "relationships" not in rendered


def test_character_sheet_projection_handles_sparse_optional_fields(scenario):
    actor = scenario.actor
    world = actor.world
    character = world.get_entity(scenario.character)
    replace_component(character, IdentityComponent(name="Juniper", kind=""))
    character.add_component(DescriptionComponent(short="", appearance=""))
    character.add_component(CharacterProfileComponent(traits=("reserved",)))
    character.add_component(PersonaProfileComponent())
    character.add_component(WhimComponent(want="already done", completed_at_epoch=1))

    non_injury = spawn_entity(world, [IdentityComponent(name="not an injury", kind="note")])
    character.add_relationship(HasInjury(), non_injury.id)

    non_thought = spawn_entity(world, [IdentityComponent(name="not a thought", kind="note")])
    character.add_relationship(HasThought(), non_thought.id)

    sheet = serialize_character_projection(actor, str(scenario.character)).model_dump(mode="json")[
        "sheet"
    ]

    assert {row["label"]: row["value"] for row in sheet["profile"]}["Kind"] == "character"
    assert "reserved" in sheet["traits"]
    assert "whim: already done" not in sheet["traits"]
    assert sheet["injuries"] == []
    assert sheet["notes"] == []


def test_character_projection_action_availability_reflects_points():
    affordable = build_scenario(action_current=5.0)
    rich = serialize_character_projection(affordable.actor, str(affordable.character)).model_dump(
        mode="json"
    )
    move = next(action for action in rich["actions"] if action["command_type"] == "move")
    assert move["available"] is True
    assert move["enough_action_points"] is True
    assert move["unavailable_reason"] == ""

    broke = build_scenario(action_current=0.0)
    poor = serialize_character_projection(broke.actor, str(broke.character)).model_dump(mode="json")
    move_poor = next(action for action in poor["actions"] if action["command_type"] == "move")
    assert move_poor["available"] is False
    assert move_poor["enough_action_points"] is False
    assert move_poor["unavailable_reason"] == "not enough action points"


def test_character_projection_action_availability_reflects_requirements(scenario):
    class _PickLockHandler:
        command_type = "pick-lock"

        def execute(self, ctx, command):  # pragma: no cover - not executed here
            return planned(MutationPlan())

    scenario.actor.register_handler(_PickLockHandler())

    without_skill = serialize_character_projection(
        scenario.actor, str(scenario.character)
    ).model_dump(mode="json")
    pick = next(
        action for action in without_skill["actions"] if action["command_type"] == "pick-lock"
    )
    assert pick["meets_requirements"] is False
    assert pick["available"] is False
    assert pick["unavailable_reason"] == "missing a required skill or item"

    scenario.actor.world.get_entity(scenario.character).add_component(
        SkillSetComponent(levels={"lockpicking": 1})
    )
    with_skill = serialize_character_projection(scenario.actor, str(scenario.character)).model_dump(
        mode="json"
    )
    pick_ready = next(
        action for action in with_skill["actions"] if action["command_type"] == "pick-lock"
    )
    assert pick_ready["meets_requirements"] is True
    assert pick_ready["available"] is True


def test_room_projection_scopes_visible_state_and_sprite_facts(scenario):
    world = scenario.actor.world
    room = world.get_entity(scenario.room_a)
    room.add_component(ToonRoomComponent(default_start=True))
    room.add_component(SpriteImageComponent(url="/rooms/moss.png"))
    room.add_component(SpriteBoundsComponent(width=120.0, height=80.0))
    visible_item = spawn_entity(
        world,
        [
            IdentityComponent(name="Painted Stool", kind="stool"),
            PortableComponent(),
            SpritePositionComponent(x=12.0, y=34.0),
            SpriteLayerComponent(layer=10),
            SpriteScaleComponent(scale=1.25),
            SpriteBoundsComponent(width=8.0, height=6.0, solid=True),
        ],
    )
    hidden_item = spawn_entity(
        world,
        [
            IdentityComponent(name="hidden ledger", kind="item"),
            PortableComponent(),
            StealthComponent(hiding=True, visibility_level=0.0),
            SpritePositionComponent(x=50.0, y=50.0),
        ],
    )
    remote_item = spawn_entity(
        world,
        [
            IdentityComponent(name="remote candle", kind="item"),
            PortableComponent(),
            SpritePositionComponent(x=10.0, y=10.0),
        ],
    )
    world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), visible_item.id
    )
    world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), hidden_item.id
    )
    world.get_entity(scenario.room_b).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), remote_item.id
    )

    view = serialize_room_projection(scenario.actor, str(scenario.room_a)).model_dump(mode="json")

    assert view["room"]["id"] == str(scenario.room_a)
    assert view["room"]["title"] == "Mosslit Burrow"
    assert view["room"]["default_start"] is True
    assert view["room"]["sprite"]["image_url"] == "/rooms/moss.png"
    assert view["room"]["sprite"]["bounds"] == {"width": 120.0, "height": 80.0, "solid": False}
    rendered = json.dumps(view)
    assert "Painted Stool" in rendered
    assert "hidden ledger" not in rendered
    assert "remote candle" not in rendered
    assert "components" not in rendered
    assert "relationships" not in rendered
    stool = next(
        entity for entity in view["room"]["entities"] if entity["id"] == str(visible_item.id)
    )
    assert stool["sprite"]["position"] == {"x": 12.0, "y": 34.0}
    assert stool["sprite"]["layer"] == 10
    assert stool["sprite"]["scale"] == 1.25
    assert stool["sprite"]["bounds"] == {"width": 8.0, "height": 6.0, "solid": True}
    assert any(exit["id"] == str(scenario.room_b) for exit in view["room"]["exits"])


def test_room_projection_rejects_invalid_ids_and_wrong_kind(scenario):
    with pytest.raises(ValueError, match="room does not exist"):
        serialize_room_projection(scenario.actor, "not-an-id")

    with pytest.raises(ValueError, match="entity is not a room"):
        serialize_room_projection(scenario.actor, str(scenario.character))


def test_character_queued_commands_scopes_commands_to_character(scenario):
    other = spawn_entity(
        scenario.actor.world,
        [CharacterComponent(), IdentityComponent(name="Hazel", kind="character")],
    )
    included = CommandRequest(
        character_id=str(scenario.character),
        controller_id=str(scenario.controller),
        controller_generation=scenario.generation,
        command_type="say",
        payload={"text": "next"},
        cost={"action": 1},
        lane=Lane.WORLD,
        command_id="cmd-included",
    ).to_submitted(submitted_at_epoch=42)
    pending = CommandRequest(
        character_id=str(scenario.character),
        controller_id=str(scenario.controller),
        controller_generation=scenario.generation,
        command_type="wait",
        payload={},
        lane=Lane.FOCUS,
        command_id="cmd-pending",
    ).to_submitted(submitted_at_epoch=43)
    excluded = CommandRequest(
        character_id=str(other.id),
        controller_id=str(scenario.controller),
        controller_generation=scenario.generation,
        command_type="say",
        payload={"text": "elsewhere"},
        command_id="cmd-excluded",
    ).to_submitted(submitted_at_epoch=44)
    scenario.actor.queues.enqueue(included)
    scenario.actor.queues.enqueue(excluded)
    scenario.actor.submit_nowait(pending)

    view = serialize_character_queued_commands(scenario.actor, str(scenario.character)).model_dump(
        mode="json"
    )

    assert view["character_id"] == str(scenario.character)
    assert [command["command_id"] for command in view["commands"]] == [
        "cmd-pending",
        "cmd-included",
    ]
    assert view["commands"][0]["lane"] == "focus"
    assert view["commands"][1]["cost"] == {"action": 1, "focus": 0}


def test_client_view_action_menu_uses_advisory_target_groups(scenario):
    scenario.actor.register_handler(TakeHandler())
    scenario.actor.register_handler(DropHandler())
    scenario.actor.register_handler(PutHandler())
    scenario.actor.register_handler(TellHandler())

    class _SipHandler:
        command_type = "sip"

    class _MarkHandler:
        command_type = "mark"

    scenario.actor.register_handler(_SipHandler())
    scenario.actor.register_action_definition(
        ActionDefinition(
            command_type="sip",
            arguments={"source_id": ActionArgument(kind="entity")},
        )
    )
    scenario.actor.register_handler(_MarkHandler())
    scenario.actor.register_action_definition(
        ActionDefinition(
            command_type="mark",
            icon="📍",
            arguments={"artifact_id": ActionArgument(kind="entity")},
        )
    )

    view = serialize_character_projection(scenario.actor, str(scenario.character)).model_dump(
        mode="json"
    )
    actions = {action["command_type"]: action for action in view["actions"]}

    take_args = {
        argument["key"]: argument["target_group"] for argument in actions["take"]["arguments"]
    }
    drop_args = {
        argument["key"]: argument["target_group"] for argument in actions["drop"]["arguments"]
    }
    put_args = {
        argument["key"]: argument["target_group"] for argument in actions["put"]["arguments"]
    }
    tell_args = {
        argument["key"]: argument["target_group"] for argument in actions["tell"]["arguments"]
    }
    sip_args = {
        argument["key"]: argument["target_group"] for argument in actions["sip"]["arguments"]
    }
    mark_args = {
        argument["key"]: argument["target_group"] for argument in actions["mark"]["arguments"]
    }
    assert take_args["item_id"] == "reachableItems"
    assert drop_args["item_id"] == "inventory"
    assert put_args["item_id"] == "inventory"
    assert put_args["target_container_id"] == "reachableItems"
    assert actions["take"]["icon"] == "🤲"
    assert actions["sip"]["icon"] == "•"
    assert actions["mark"]["icon"] == "📍"
    assert tell_args["target_id"] == "characters"
    assert tell_args["text"] is None
    assert sip_args["source_id"] == "reachableItems"
    assert mark_args["artifact_id"] == "reachable"


def test_client_view_handles_unperceiving_character_and_errors():
    actor = WorldActor()
    character = spawn_entity(
        actor.world,
        [
            IdentityComponent(name="Quiet", kind="character"),
            CharacterComponent(),
            PerceptionComponent(active=False),
        ],
    )
    room = spawn_entity(actor.world, [RoomComponent(title="Bare Room")])
    actor.world.get_entity(room.id).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), character.id
    )
    carried_room = spawn_entity(actor.world, [RoomComponent(title="Pocket Room")])
    carried_character = spawn_entity(actor.world, [CharacterComponent()])
    carried_item = spawn_entity(actor.world, [PortableComponent()])
    worn_item = spawn_entity(actor.world, [IdentityComponent(name="cloak", kind="item")])
    carried_other = spawn_entity(actor.world)
    character.add_relationship(Contains(mode=ContainmentMode.INVENTORY), carried_room.id)
    character.add_relationship(Contains(mode=ContainmentMode.INVENTORY), carried_character.id)
    character.add_relationship(Contains(mode=ContainmentMode.INVENTORY), carried_item.id)
    character.add_relationship(Contains(mode=ContainmentMode.INVENTORY), carried_other.id)
    character.add_relationship(Holding(), carried_item.id)
    character.add_relationship(Wearing(), worn_item.id)

    view = serialize_character_projection(actor, str(character.id)).model_dump(mode="json")

    assert view["can_perceive"] is False
    assert view["room"] == {
        "id": str(room.id),
        "title": "Bare Room",
        "entities": [],
        "exits": [],
    }
    assert view["points"] == {"action": 0.0, "action_max": 0.0, "focus": 0.0, "focus_max": 0.0}
    assert view["controller"] is None
    assert {target["kind"] for target in view["inventory"]} == {
        "item",
        "character",
        "room",
        "other",
    }
    assert sum(1 for target in view["inventory"] if target["id"] == str(carried_item.id)) == 1
    assert any(target["id"] == str(worn_item.id) for target in view["inventory"])

    unplaced = spawn_entity(
        actor.world,
        [
            IdentityComponent(name="Unplaced", kind="character"),
            CharacterComponent(),
            PerceptionComponent(active=False),
        ],
    )
    unplaced_view = serialize_character_projection(actor, str(unplaced.id)).model_dump(mode="json")
    assert unplaced_view["room"] == {"id": None, "title": "", "entities": [], "exits": []}

    with pytest.raises(ValueError, match="character does not exist"):
        serialize_character_projection(actor, "not-an-id")
    with pytest.raises(ValueError, match="entity is not a character"):
        serialize_character_projection(actor, str(room.id))


def test_dm_projection_rejects_blank_id(scenario):
    with pytest.raises(ValueError, match="dm id must not be blank"):
        serialize_dm_projection(scenario.actor, " ")


def test_jsonable_serializes_client_view_models():
    assert jsonable(ClientTargetView(id="item_1", label="lamp", kind="item")) == {
        "id": "item_1",
        "label": "lamp",
        "kind": "item",
    }


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
        message["data"]["event_type"] == "ActorMovedEvent" for message in stream.recent_messages()
    )


def test_event_stream_broadcast_drops_oldest_when_queue_is_full(scenario):
    stream = EventStream(scenario.actor)
    assert stream._room_of("not-an-entity") is None
    subscription = stream.subscribe(max_queue_size=1)
    try:
        stream.broadcast({"type": "first"})
        stream.broadcast({"type": "second"})

        assert subscription.queue.get_nowait() == {"type": "second"}
        assert subscription.queue.empty()
    finally:
        subscription.close()


def test_event_stream_broadcast_tolerates_concurrently_drained_full_queue(scenario):
    # Defensive path: ``full()`` reports True but a concurrent consumer has already drained
    # the queue, so ``get_nowait()`` raises QueueEmpty. The broadcast must swallow it and
    # still enqueue the new message instead of crashing the fan-out loop.
    class RacyQueue(asyncio.Queue):
        def __init__(self) -> None:
            super().__init__()
            self.delivered: list[dict] = []

        def full(self) -> bool:  # type: ignore[override]
            return True

        def get_nowait(self):  # type: ignore[override]
            raise asyncio.QueueEmpty

        def put_nowait(self, item) -> None:  # type: ignore[override]
            self.delivered.append(item)

    racy = RacyQueue()
    stream = EventStream(scenario.actor)
    subscription = stream.subscribe()
    object.__setattr__(subscription, "queue", racy)
    stream._subscribers = {subscription}
    try:
        stream.broadcast({"type": "racy"})
        assert racy.delivered == [{"type": "racy"}]
    finally:
        stream._subscribers = set()


def test_character_projection_skips_dangling_inventory_and_duplicate_holds(scenario):
    world = scenario.actor.world
    character = world.get_entity(scenario.character)

    held = spawn_entity(world, [IdentityComponent(name="lamp", kind="item"), PortableComponent()])
    character.add_relationship(Contains(mode=ContainmentMode.INVENTORY), held.id)
    # Holding the same item again must be de-duplicated against the Contains listing.
    character.add_relationship(Holding(), held.id)

    # A dangling inventory edge to a removed entity must be skipped, not crash.
    ghost = spawn_entity(world, [PortableComponent()])
    character.add_relationship(Contains(mode=ContainmentMode.INVENTORY), ghost.id)
    worn_ghost = spawn_entity(world, [IdentityComponent(name="rag", kind="item")])
    character.add_relationship(Wearing(), worn_ghost.id)
    world.remove(ghost.id)
    world.remove(worn_ghost.id)

    view = serialize_character_projection(scenario.actor, str(scenario.character)).model_dump(
        mode="json"
    )

    inventory_ids = [target["id"] for target in view["inventory"]]
    assert inventory_ids.count(str(held.id)) == 1
    assert str(ghost.id) not in inventory_ids
    assert str(worn_ghost.id) not in inventory_ids


def test_room_projection_and_overview_skip_hidden_and_dangling_contents(scenario):
    world = scenario.actor.world
    room = world.get_entity(scenario.room_a)

    hidden = spawn_entity(
        world,
        [
            IdentityComponent(name="ghost", kind="item"),
            StealthComponent(hiding=True, visibility_level=0.0),
        ],
    )
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), hidden.id)

    item = spawn_entity(world, [IdentityComponent(name="pebble", kind="item"), PortableComponent()])
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), item.id)

    # A visible, non-portable, non-character fixture: counted as neither occupant nor item.
    fixture = spawn_entity(world, [IdentityComponent(name="statue", kind="decor")])
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), fixture.id)

    invisible = spawn_entity(world, [IdentityComponent(name="mote", kind="item")])
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT, visible=False), invisible.id)

    dangling = spawn_entity(world, [IdentityComponent(name="dust", kind="item")])
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), dangling.id)
    world.remove(dangling.id)

    room_view = serialize_room_projection(scenario.actor, str(scenario.room_a)).model_dump(
        mode="json"
    )
    listed = {entity["id"] for entity in room_view["room"]["entities"]}
    assert str(item.id) in listed
    assert str(hidden.id) not in listed
    assert str(invisible.id) not in listed
    assert str(dangling.id) not in listed

    overview = serialize_world_overview(scenario.actor).model_dump(mode="json")
    room_overview = next(r for r in overview["rooms"] if r["id"] == str(scenario.room_a))
    # Character (occupant) + pebble (portable item); hidden/invisible/dangling all excluded.
    assert room_overview["item_count"] == 1
    assert room_overview["occupant_count"] == 1


def test_target_groups_separate_perceived_characters_from_room_items(scenario):
    # A perceived character must land in "characters" (not roomItems); a perceived portable
    # item must land in roomItems. This exercises the character/non-character split in
    # _target_groups (the kind=="character" branch that skips the room-items append).
    world = scenario.actor.world
    other = spawn_entity(
        world, [CharacterComponent(), IdentityComponent(name="Bramble", kind="character")]
    )
    world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), other.id
    )
    stone = spawn_entity(world, [IdentityComponent(name="rock", kind="item"), PortableComponent()])
    world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), stone.id
    )

    groups = serialize_character_projection(scenario.actor, str(scenario.character)).model_dump(
        mode="json"
    )["target_groups"]

    assert "Bramble" in [target["label"] for target in groups["characters"]]
    assert "Bramble" not in [target["label"] for target in groups["roomItems"]]
    assert "rock" in [target["label"] for target in groups["roomItems"]]


def test_target_groups_separate_living_held_items_from_takeable_body_contents(scenario):
    world = scenario.actor.world
    holder = spawn_entity(
        world, [CharacterComponent(), IdentityComponent(name="Hazel", kind="character")]
    )
    body = spawn_entity(
        world,
        [
            CharacterComponent(),
            DeadComponent(died_at_epoch=0, cause="test"),
            IdentityComponent(name="Marlow", kind="character"),
        ],
    )
    room = world.get_entity(scenario.room_a)
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), holder.id)
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), body.id)
    held = spawn_entity(
        world, [IdentityComponent(name="steamed bun", kind="food"), PortableComponent()]
    )
    pocketed = spawn_entity(
        world, [IdentityComponent(name="pocket key", kind="item"), PortableComponent()]
    )
    body_item = spawn_entity(
        world, [IdentityComponent(name="brass key", kind="item"), PortableComponent()]
    )
    holder.add_relationship(Contains(mode=ContainmentMode.INVENTORY), held.id)
    holder.add_relationship(Contains(mode=ContainmentMode.INVENTORY), pocketed.id)
    holder.add_relationship(Holding(slot="hand"), held.id)
    body.add_relationship(Contains(mode=ContainmentMode.INVENTORY), body_item.id)

    view = serialize_character_projection(scenario.actor, str(scenario.character)).model_dump(
        mode="json"
    )
    groups = view["target_groups"]

    assert groups["heldItems"] == [
        {"id": str(held.id), "label": "steamed bun (held by Hazel)", "kind": "object"}
    ]
    assert str(held.id) not in {target["id"] for target in groups["reachableItems"]}
    assert str(pocketed.id) not in json.dumps(view)
    assert str(body_item.id) in {target["id"] for target in groups["reachableItems"]}


def test_sprite_bounds_view_falls_back_to_default_when_no_bounds(scenario):
    # An entity with neither explicit SpriteBoundsComponent nor a kind that maps to default bounds
    # forces the ``bounds = SpriteBoundsComponent()`` fallback in ``_sprite_bounds_view``.
    world = scenario.actor.world
    # kind="trinket" maps to no default footprint and the entity carries no PortableComponent,
    # so default_bounds_for returns None and _sprite_bounds_view uses the fallback component.
    plain = spawn_entity(world, [IdentityComponent(name="speck", kind="trinket")])
    world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), plain.id
    )

    view = serialize_room_projection(scenario.actor, str(scenario.room_a)).model_dump(mode="json")
    speck = next(e for e in view["room"]["entities"] if e["id"] == str(plain.id))
    assert speck["sprite"]["bounds"] == {
        "width": SpriteBoundsComponent().width,
        "height": SpriteBoundsComponent().height,
        "solid": SpriteBoundsComponent().solid,
    }


def test_type_schema_reports_adapter_errors(monkeypatch):
    class BadType:
        pass

    class RaisingAdapter:
        def __init__(self, type_):
            self.type_ = type_

        def json_schema(self):
            raise RuntimeError("cannot adapt")

    monkeypatch.setattr("bunnyland.server.schema.TypeAdapter", RaisingAdapter)

    schema = _type_schema("BadType", BadType, 0)

    assert schema.used is False
    assert schema.count == 0
    assert schema.schema_error == "cannot adapt"
    assert schema.json_schema["additionalProperties"] is True


async def test_generation_failed_publisher_emits_failure_event(scenario):
    events: list[WorldGenerationFailedEvent] = []
    scenario.actor.bus.subscribe(WorldGenerationFailedEvent, events.append)
    job = server_admin.WorldGenerationJob(
        job_id="job-failed",
        seed="bad seed",
        generator="stub",
        status="failed",
        error="boom",
    )

    await server_admin._publish_generation_failed(scenario.actor, job)

    assert events[0].job_id == "job-failed"
    assert events[0].error == "boom"


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
    assert serialized["event_key"] == "bunnyland.core:ActorMovedEvent"
    assert serialized["event"]["world_epoch"] == 7
    assert serialized["event"]["created_at"] is not None


def test_server_app_module_falls_back_when_fastapi_missing(scenario):
    import importlib

    import bunnyland.server.app as app_mod

    try:
        with patch.dict(sys.modules, {"fastapi": None, "fastapi.middleware.cors": None}):
            reloaded = importlib.reload(app_mod)
            assert reloaded.FastAPI is None
            with pytest.raises(RuntimeError, match="requires FastAPI"):
                reloaded.create_app(scenario.actor)
    finally:
        # Restore a healthy module so unrelated tests keep the real FastAPI symbols.
        importlib.reload(app_mod)


async def test_run_loop_with_api_missing_uvicorn_raises(scenario, monkeypatch):
    monkeypatch.setitem(sys.modules, "uvicorn", None)
    loop = GameLoop(
        scenario.actor,
        ControllerDispatch(
            scenario.actor,
            PromptBuilder(scenario.actor.world),
            ScriptedAgent([]),
        ),
    )
    meta = WorldMeta(seed="moss", generator="oneshot")
    with pytest.raises(RuntimeError, match="requires uvicorn"):
        await run_loop_with_api(loop, scenario.actor, meta, host="127.0.0.1", port=0)


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
    assert "/v1/public/health" in paths
    assert "/v1/public/features" in paths
    assert "/v1/admin/world/snapshot" in paths
    assert "/v1/play/characters" in paths
    assert "/v1/play/claims/{claim_id}/projection" in paths
    assert "/v1/play/claims/{claim_id}/commands" in paths
    assert "/v1/play/claims/{claim_id}/commands/{command_id}" in paths
    assert "/v1/admin/characters/{character_id}" in paths
    assert "/play/world/client-view/{character_id}" not in paths
    assert "/v1/play/catalog" in paths
    assert "/v1/play/claims" in paths
    assert "/v1/admin/world" in paths
    assert "/v1/admin/world/generators" in paths
    assert "/v1/admin/world/generation-jobs" in paths
    assert "/v1/admin/media/{target_kind}/{target_id}/{purpose}" in paths
    assert "/v1/admin/world/checkpoints" in paths
    assert "/v1/admin/memory/collections" in paths
    assert "/v1/admin/memory/collections/{collection}/documents" in paths
    assert "/v1/admin/memory/collections/{collection}/documents/{document_id}" in paths
    assert "/v1/admin/world/runtime" in paths
    assert "/v1/admin/world/stream" in paths


def test_route_matrix_declares_every_http_and_websocket_surface_once(scenario):
    app = create_app(scenario.actor, plugins=select(bunnyland_plugins(), [MCP]))

    matrix = route_surface_matrix(app)

    assert len(matrix) == len(app.routes)
    assert all(classify_authorization_surface(path) is surface for _, path, surface in matrix)
    assert (
        "websocket",
        "/v1/play/claims/{claim_id}/stream",
        AuthorizationSurface.PLAY,
    ) in matrix
    assert ("websocket", "/v1/admin/world/stream", AuthorizationSurface.ADMIN) in matrix
    assert ("http", "/v1/mcp", AuthorizationSurface.MCP) in matrix


def test_route_audit_and_addon_zoning_reject_unzoned_or_cross_zone_routes(scenario):
    fastapi = pytest.importorskip("fastapi")
    unzoned = fastapi.FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @unzoned.get("/legacy")
    async def legacy_route():
        return {"ok": True}

    with pytest.raises(ValueError, match="outside an authorization zone"):
        route_surface_matrix(unzoned)

    no_path = SimpleNamespace(router=SimpleNamespace(routes=[SimpleNamespace()]))
    assert route_surface_matrix(no_path) == []

    invalid_websocket = fastapi.FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @invalid_websocket.websocket("/v1/public/socket")
    async def public_socket(_websocket):
        return None

    with pytest.raises(ValueError, match="websocket route uses invalid"):
        route_surface_matrix(invalid_websocket)

    def install_cross_zone(router, _actor, **_context):
        @router.get("/admin/escape")
        async def escaped_route():
            return {"ok": True}

    plugin = Plugin(
        id="test.cross-zone",
        name="Cross-zone Test",
        runtime=RuntimeContribution(
            http=(HttpContribution(zone=HttpZone.PLAY, registrars=(install_cross_zone,)),)
        ),
    )
    app = create_app(scenario.actor, plugins=(plugin,))
    assert any(
        route.path == "/v1/play/extensions/test.cross-zone/admin/escape" for route in app.routes
    )

    def install_absolute_zone(router, _actor, **_context):
        @router.get("/v1/admin/escape")
        async def absolute_escape():
            return {"escaped": True}

    absolute = Plugin(
        id="test.absolute-zone",
        name="Absolute Zone Test",
        runtime=RuntimeContribution(
            http=(HttpContribution(zone=HttpZone.PLAY, registrars=(install_absolute_zone,)),)
        ),
    )
    with pytest.raises(ValueError, match="attempted absolute or cross-zone route"):
        create_app(scenario.actor, plugins=(absolute,))


def test_unknown_zoned_paths_remain_404(scenario):
    testclient = pytest.importorskip("fastapi.testclient")
    app = create_app(scenario.actor)
    client = testclient.TestClient(app)

    assert client.get("/v1/play/does-not-exist").status_code == 404
    assert client.get("/v1/admin/does-not-exist").status_code == 404


def test_fixed_window_rate_limiter_bounds_and_recovers() -> None:
    current = [0.0]
    clock_limiter = FixedWindowRateLimiter(1, 10, clock=lambda: current[0])
    assert clock_limiter.check("clocked") == (True, 0)
    assert clock_limiter.check("clocked") == (False, 10)
    clock_limiter.reset("clocked")
    assert clock_limiter.check("clocked") == (True, 0)

    limiter = FixedWindowRateLimiter(2, 10)

    assert limiter.check("client", now=0) == (True, 0)
    assert limiter.check("client", now=1) == (True, 0)
    assert limiter.check("client", now=2) == (False, 8)
    assert limiter.check("other", now=2) == (True, 0)
    assert limiter.check("client", now=10) == (True, 0)
    assert limiter.check("fresh", now=20) == (True, 0)
    assert set(limiter._requests) == {"fresh"}
    assert FixedWindowRateLimiter(0, 10).check("client", now=0) == (True, 0)


def test_fastapi_rate_limit_returns_retry_after_and_exempts_health(scenario):
    testclient = pytest.importorskip("fastapi.testclient")
    app = create_app(
        scenario.actor,
        rate_limit_requests=1,
        rate_limit_window_seconds=60,
    )
    client = testclient.TestClient(app, headers=_ADMIN_HEADERS)

    headers = {
        "X-Forwarded-For": "198.51.100.1, 10.0.0.1",
        "X-Bunnyland-Client-Id": "first",
    }
    assert client.get("/v1/play/characters", headers=headers).status_code == 200
    limited = client.get(
        "/v1/play/characters",
        headers={**headers, "X-Bunnyland-Client-Id": "rotated"},
    )
    assert limited.status_code == 429
    assert limited.headers["Retry-After"] == "60"
    assert limited.json()["detail"] == "request rate limit exceeded"
    assert limited.json()["code"] == "rate_limited"
    still_limited = client.get(
        "/v1/play/characters",
        headers={
            "X-Forwarded-For": "198.51.100.1, 10.0.0.2",
            CLIENT_ID_HEADER: "third",
        },
    )
    assert still_limited.status_code == 429
    assert client.get("/v1/public/health", headers=headers).status_code == 204
    assert client.get("/v1/public/health", headers=headers).status_code == 204


def test_fastapi_app_factory_installs_zoned_plugin_routers(scenario):
    testclient = pytest.importorskip("fastapi.testclient")
    seen = {}

    def install_router(router, actor, **context):
        seen["actor"] = actor
        seen["meta"] = context["meta"]

        @router.get("/plugin/ping")
        async def plugin_ping():
            return {"ok": True, "seed": context["meta"].seed}

    plugin = Plugin(
        id="test.router",
        name="Router Test",
        runtime=RuntimeContribution(
            http=(HttpContribution(zone=HttpZone.PLAY, registrars=(install_router,)),)
        ),
    )
    meta = WorldMeta(seed="moss")
    app = create_app(scenario.actor, meta=meta, plugins=(plugin,))
    client = testclient.TestClient(
        app,
        headers={CLIENT_ID_HEADER: "test-player"},
    )

    response = client.get("/v1/play/extensions/test.router/plugin/ping")

    assert response.status_code == 200
    assert response.json() == {"ok": True, "seed": "moss"}
    assert seen == {"actor": scenario.actor, "meta": meta}


def test_fastapi_read_endpoints_return_world_state_schema_and_library(scenario, monkeypatch):
    testclient = pytest.importorskip("fastapi.testclient")
    meta = WorldMeta(seed="moss", generator="oneshot", plugins=("bunnyland.core_verbs",))
    monkeypatch.setenv("BUNNYLAND_GIT_HASH", "deadbeefcafebabe")
    secrets = ClaimSecretRegistry()
    claim = add_claim(
        scenario.actor.world.get_entity(scenario.controller),
        client_kind="web",
        client_id="room-client",
        character_id=str(scenario.character),
    )
    claim_secret = secrets.issue(claim.claim_id)
    app = create_app(
        scenario.actor,
        meta=meta,
        with_admin=True,
        claim_secrets=secrets,
    )
    client = testclient.TestClient(app, headers=_ADMIN_HEADERS)

    features = client.get("/v1/public/features")
    snapshot = client.get("/v1/admin/world/snapshot", headers=_ADMIN_HEADERS)
    catalog = client.get(
        "/v1/play/catalog",
        headers={**app.state.test_player_headers, CLIENT_ID_HEADER: "room-client"},
    )
    recent = client.get(
        "/v1/admin/world/events",
        headers=_ADMIN_HEADERS,
    )
    player_headers = {
        **app.state.test_player_headers,
        CLIENT_ID_HEADER: "room-client",
        "X-Bunnyland-Claim-Secret": claim_secret,
    }
    projection = client.get(
        f"/v1/play/claims/{claim.claim_id}/projection",
        headers=player_headers,
    )

    assert features.status_code == 200
    assert features.json()["character_sheets"] is True
    assert snapshot.status_code == 200
    assert snapshot.json()["metadata"]["seed"] == "moss"
    assert catalog.status_code == 200
    assert catalog.json()["components"]["RoomComponent"]["count"] == 2
    assert catalog.json()["content"] == load_content_library().model_dump(mode="json")
    assert recent.status_code == 200
    assert recent.json()["events"] == []
    assert projection.status_code == 200
    assert projection.json()["character"]["character_id"] == str(scenario.character)
    assert projection.json()["scene"]["room"]["id"] == str(scenario.room_a)
    assert projection.json()["commands"] == []


def test_claim_scoped_perspective_query_route_and_stream_metrics(scenario, monkeypatch):
    from bunnyland.core.perspective import V1_PERSPECTIVE_QUERIES

    testclient = pytest.importorskip("fastapi.testclient")
    for definition in V1_PERSPECTIVE_QUERIES:
        scenario.actor.perspective_queries.register(definition, owner="bunnyland.core_verbs")
    for definition in SOCIAL_PERSPECTIVE_QUERIES:
        scenario.actor.perspective_queries.register(definition, owner="bunnyland.social")
    hazel = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="Hazel", kind="character"), CharacterComponent()],
    )
    scenario.actor.world.get_entity(scenario.character).add_relationship(
        SocialBond(trust=0.5), hazel.id
    )
    create_obligation(
        scenario.actor.world,
        kind="request",
        text="Share the map",
        debtor_id=hazel.id,
        creditor_id=scenario.character,
        due_epoch=99,
    )
    secrets = ClaimSecretRegistry()
    controller = scenario.actor.world.get_entity(scenario.controller)
    claim = add_claim(
        controller,
        client_kind="web",
        client_id="query-client",
        character_id=str(scenario.character),
    )
    secret = secrets.issue(claim.claim_id)
    app = create_app(
        scenario.actor,
        claim_secrets=secrets,
        with_admin=True,
    )
    client = testclient.TestClient(app, headers=_ADMIN_HEADERS)
    headers = {
        **app.state.test_player_headers,
        CLIENT_ID_HEADER: "query-client",
        "X-Bunnyland-Claim-Secret": secret,
    }
    path = f"/v1/play/claims/{claim.claim_id}/queries"

    valid = client.post(
        path,
        headers=headers,
        json={"query": "valid_targets", "arguments": {"action": "move"}},
    )
    unknown = client.post(
        path,
        headers=headers,
        json={"query": "raw_relics"},
    )
    connections = client.post(path, headers=headers, json={"query": "social_connections"})
    obligations = client.post(path, headers=headers, json={"query": "open_obligations"})
    wrong_client = client.post(
        path,
        headers={**headers, CLIENT_ID_HEADER: "other-client"},
        json={"query": "social_connections"},
    )

    assert valid.status_code == 200
    assert valid.json()["result"]["exit_id"][0]["id"] == str(scenario.room_b)
    assert unknown.status_code == 400
    assert connections.status_code == 200
    assert connections.json()["result"][0]["character"] == {
        "id": str(hazel.id),
        "name": "Hazel",
        "kind": "character",
    }
    assert obligations.status_code == 200
    assert obligations.json()["result"][0]["role"] == "creditor"
    assert obligations.json()["result"][0]["due_epoch"] == 99
    assert wrong_client.status_code == 403

    def forbidden(*args, **kwargs):
        raise PermissionError("query is not visible")

    monkeypatch.setattr(scenario.actor.perspective_queries, "execute", forbidden)
    denied = client.post(
        path,
        headers=headers,
        json={"query": "valid_targets", "arguments": {"action": "move"}},
    )
    assert denied.status_code == 403

    def timeout(*args, **kwargs):
        raise TimeoutError("query budget exhausted")

    monkeypatch.setattr(scenario.actor.perspective_queries, "execute", timeout)
    exhausted = client.post(
        path,
        headers=headers,
        json={"query": "valid_targets", "arguments": {"action": "move"}},
    )
    assert exhausted.status_code == 503


def test_health_reports_unknown_git_hash_when_env_is_missing(scenario, monkeypatch):
    testclient = pytest.importorskip("fastapi.testclient")
    monkeypatch.delenv("BUNNYLAND_GIT_HASH", raising=False)
    app = create_app(scenario.actor)
    client = testclient.TestClient(app)

    health = client.get("/v1/public/health")

    assert health.status_code == 204
    assert health.content == b""


def test_health_reports_configured_feature_flags(scenario, monkeypatch):
    from fastapi.testclient import TestClient

    class ImageService:
        def start_backfill(self):
            pass

        async def aclose(self):
            pass

    monkeypatch.setattr(
        server_app,
        "create_bunnyland_mcp_app",
        lambda **_kwargs: server_app.FastAPI(),
    )
    app = create_app(
        scenario.actor,
        plugins=select(bunnyland_plugins(), [MCP]),
        imagegen=ImageService(),
        character_chat=object(),
    )
    client = TestClient(app)

    public_features = client.get("/v1/public/features")

    assert public_features.status_code == 200
    assert public_features.json() == {
        "mcp": True,
        "character_chat": True,
        "character_sheets": True,
        "image_generation": True,
    }


def test_fastapi_character_list_returns_claim_lobby_without_state(scenario):
    testclient = pytest.importorskip("fastapi.testclient")
    suspended = spawn_entity(
        scenario.actor.world,
        [
            CharacterComponent(),
            IdentityComponent(name="Aspen", kind="character"),
            SuspendedComponent(),
        ],
    )
    app = create_app(scenario.actor)
    client = testclient.TestClient(app)

    response = client.get("/v1/play/characters", headers={CLIENT_ID_HEADER: "lobby-client"})

    assert response.status_code == 200
    body = response.json()
    assert body["world_epoch"] == scenario.actor.epoch
    characters = {entry["id"]: entry for entry in body["characters"]}
    # Sorted by name: Aspen before Juniper.
    assert [entry["name"] for entry in body["characters"]] == ["Aspen", "Juniper"]
    assert characters[str(suspended.id)]["suspended"] is True
    assert characters[str(scenario.character)]["suspended"] is False
    # The lobby is ids and names only -- no per-character state leaks through.
    assert "points" not in response.text
    assert "inventory" not in response.text
    assert "components" not in response.text


def test_fastapi_character_projection_maps_invalid_ids_to_http_errors(scenario):
    testclient = pytest.importorskip("fastapi.testclient")
    app = create_app(scenario.actor)
    client = testclient.TestClient(app)

    invalid = client.post(
        "/v1/play/claims",
        headers={CLIENT_ID_HEADER: "projection-client"},
        json={"character_id": "not-an-id"},
    )
    wrong_kind = client.post(
        "/v1/play/claims",
        headers={CLIENT_ID_HEADER: "projection-client"},
        json={"character_id": str(scenario.room_a)},
    )

    assert invalid.status_code == 404
    assert invalid.json()["detail"] == "character does not exist"
    assert wrong_kind.status_code == 400
    assert wrong_kind.json()["detail"] == "entity is not a character"


def test_fastapi_room_projection_and_queue_map_invalid_ids_to_http_errors(scenario):
    testclient = pytest.importorskip("fastapi.testclient")
    secrets = ClaimSecretRegistry()
    claim = add_claim(
        scenario.actor.world.get_entity(scenario.controller),
        client_kind="web",
        client_id="room-client",
        character_id=str(scenario.character),
    )
    secret = secrets.issue(claim.claim_id)
    app = create_app(scenario.actor, claim_secrets=secrets)
    client = testclient.TestClient(app)
    headers = {
        CLIENT_ID_HEADER: "room-client",
        "X-Bunnyland-Claim-Secret": secret,
    }

    missing_claim = client.get("/v1/play/claims/not-a-claim/projection", headers=headers)
    visible = client.get(f"/v1/play/claims/{claim.claim_id}/projection", headers=headers)

    assert missing_claim.status_code == 404
    assert missing_claim.json()["detail"] == "claim does not exist"
    assert visible.status_code == 200
    assert visible.json()["scene"]["room"]["id"] == str(scenario.room_a)
    assert visible.json()["commands"] == []


def test_fastapi_room_projection_requires_claim_and_current_perception(scenario, monkeypatch):
    testclient = pytest.importorskip("fastapi.testclient")
    secrets = ClaimSecretRegistry()
    claim = add_claim(
        scenario.actor.world.get_entity(scenario.controller),
        client_kind="web",
        client_id="room-client",
        character_id=str(scenario.character),
    )
    secret = secrets.issue(claim.claim_id)
    client = testclient.TestClient(create_app(scenario.actor, claim_secrets=secrets))
    path = f"/v1/play/claims/{claim.claim_id}/projection"
    missing_secret = client.get(path, headers={CLIENT_ID_HEADER: "room-client"})
    wrong_secret = client.get(
        path,
        headers={
            CLIENT_ID_HEADER: "room-client",
            "X-Bunnyland-Claim-Secret": "wrong",
        },
    )
    wrong_client = client.get(
        path,
        headers={
            CLIENT_ID_HEADER: "other-client",
            "X-Bunnyland-Claim-Secret": secret,
        },
    )
    visible_room = client.get(
        path,
        headers={
            CLIENT_ID_HEADER: "room-client",
            "X-Bunnyland-Claim-Secret": secret,
        },
    )

    assert missing_secret.status_code == 403
    assert wrong_secret.status_code == 403
    assert wrong_client.status_code == 403
    assert visible_room.status_code == 200


def test_fastapi_openapi_exposes_projection_contract_route(scenario):
    pytest.importorskip("fastapi")
    app = create_app(scenario.actor, with_admin=True)

    schema = app.openapi()
    operation = schema["paths"]["/v1/play/claims/{claim_id}/projection"]["get"]

    assert {parameter["name"] for parameter in operation["parameters"]} == {
        "claim_id",
        "X-Bunnyland-Claim-Secret",
        "X-Bunnyland-Client-Id",
    }
    assert operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ClaimProjectionResource"
    }
    recent_operation = schema["paths"]["/v1/admin/world/events"]["get"]
    assert recent_operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/EventCollection"
    }
    dm_operation = schema["paths"]["/v1/admin/characters/{character_id}"]["get"]
    assert {parameter["name"] for parameter in dm_operation["parameters"]} == {"character_id"}


def test_fastapi_dm_projection_requires_permission_and_returns_typed_view(scenario):
    testclient = pytest.importorskip("fastapi.testclient")
    world = scenario.actor.world
    hidden_item = spawn_entity(
        world,
        [
            IdentityComponent(name="hidden ledger", kind="item"),
            PortableComponent(),
            StealthComponent(hiding=True, visibility_level=0.0),
        ],
    )
    world.get_entity(scenario.room_b).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), hidden_item.id
    )
    app = create_app(scenario.actor, with_admin=True)
    client = testclient.TestClient(app)

    missing = client.get("/v1/admin/characters/dm-1")
    wrong = client.get(
        "/v1/admin/characters/dm-1",
        headers={
            "Authorization": "Bearer invalid",
            CLIENT_ID_HEADER: "admin-a",
        },
    )
    allowed = client.get("/v1/admin/characters/dm-1", headers=_ADMIN_HEADERS)

    assert missing.status_code == 401
    assert wrong.status_code == 401
    assert allowed.status_code == 200
    view = allowed.json()
    assert view["dm_id"] == "dm-1"
    assert {room["title"] for room in view["rooms"]} == {"Mosslit Burrow", "North Tunnel"}
    assert any(character["label"] == "Juniper" for character in view["characters"])
    rendered = json.dumps(view)
    assert "hidden ledger" in rendered
    assert "components" not in rendered
    assert "relationships" not in rendered


def test_fastapi_world_overview_requires_permission_and_returns_room_network(scenario):
    testclient = pytest.importorskip("fastapi.testclient")
    world = scenario.actor.world
    berry = spawn_entity(
        world, [IdentityComponent(name="three berries", kind="item"), PortableComponent()]
    )
    world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), berry.id
    )
    app = create_app(scenario.actor, with_admin=True)
    client = testclient.TestClient(app)

    missing = client.get("/v1/admin/world")
    wrong = client.get(
        "/v1/admin/world",
        headers={
            "Authorization": "Bearer invalid",
            CLIENT_ID_HEADER: "admin-a",
        },
    )
    allowed = client.get("/v1/admin/world", headers=_ADMIN_HEADERS)

    assert missing.status_code == 401
    assert wrong.status_code == 401
    assert allowed.status_code == 200
    view = allowed.json()
    assert view["room_count"] == 2
    assert view["character_count"] == 1
    rooms = {room["title"]: room for room in view["rooms"]}
    assert set(rooms) == {"Mosslit Burrow", "North Tunnel"}
    burrow = rooms["Mosslit Burrow"]
    assert burrow["occupant_count"] == 1  # Juniper
    assert burrow["item_count"] == 1  # three berries
    assert {exit["direction"] for exit in burrow["exits"]} == {"north"}
    # Slim map only -- no raw ECS components or relationships leak through.
    rendered = json.dumps(view)
    assert "components" not in rendered
    assert "relationships" not in rendered


def test_fastapi_world_snapshot_requires_admin_scope(scenario):
    testclient = pytest.importorskip("fastapi.testclient")
    app = create_app(scenario.actor, with_admin=True)
    client = testclient.TestClient(app)

    missing = client.get("/v1/admin/world/snapshot")
    wrong = client.get(
        "/v1/admin/world/snapshot",
        headers={
            "Authorization": "Bearer invalid",
            CLIENT_ID_HEADER: "admin-a",
        },
    )
    allowed = client.get("/v1/admin/world/snapshot", headers=_ADMIN_HEADERS)

    assert missing.status_code == 401
    assert wrong.status_code == 401
    assert allowed.status_code == 200
    assert any(entity["id"] == str(scenario.character) for entity in allowed.json()["entities"])


def test_fastapi_admin_memory_lists_characters_and_documents_without_backend_type(scenario):
    testclient = pytest.importorskip("fastapi.testclient")
    store = install_memory(scenario.actor, InMemoryStore())
    character = scenario.actor.world.get_entity(scenario.character)
    character.add_component(
        MemoryProfileComponent(
            vector_collection="juniper-private",
            shared_collections=("burrow-board", "kitchen-board"),
        )
    )
    entry = store.add(
        "juniper-private",
        text="Berries grow near the north tunnel.",
        tags=("forage",),
        created_at_epoch=12,
        source="manual",
    )
    app = create_app(scenario.actor, with_admin=True)
    client = testclient.TestClient(app)

    characters = client.get("/v1/admin/memory/collections", headers=_ADMIN_HEADERS)
    documents = client.get(
        "/v1/admin/memory/collections/juniper-private/documents",
        headers=_ADMIN_HEADERS,
    )

    assert characters.status_code == 200
    assert characters.json()["characters"] == [
        {
            "character_id": str(scenario.character),
            "name": "Juniper",
            "private_collection": "juniper-private",
            "shared_collections": ["burrow-board", "kitchen-board"],
        }
    ]
    assert documents.status_code == 200
    body = documents.json()
    assert body["collection"] == "juniper-private"
    assert body["documents"] == [
        {
            "id": entry.id,
            "document": "Berries grow near the north tunnel.",
            "metadata": {
                "tags": ["forage"],
                "created_at_epoch": 12,
                "source": "manual",
            },
        }
    ]
    rendered = json.dumps({"characters": characters.json(), "documents": body}).lower()
    assert "backend" not in rendered
    assert "store" not in rendered
    assert "chroma" not in rendered


def test_fastapi_admin_memory_updates_and_deletes_document(scenario):
    testclient = pytest.importorskip("fastapi.testclient")
    store = install_memory(scenario.actor, InMemoryStore())
    scenario.actor.world.get_entity(scenario.character).add_component(
        MemoryProfileComponent(vector_collection="juniper-private")
    )
    entry = store.add("juniper-private", text="old text", created_at_epoch=1)
    app = create_app(scenario.actor, with_admin=True)
    client = testclient.TestClient(app)

    updated = client.patch(
        f"/v1/admin/memory/collections/juniper-private/documents/{entry.id}",
        headers=_ADMIN_HEADERS,
        json={
            "document": "updated text",
            "metadata": {"tags": ["edited"], "created_at_epoch": 22, "source": "admin"},
        },
    )
    listed = client.get(
        "/v1/admin/memory/collections/juniper-private/documents",
        headers=_ADMIN_HEADERS,
    )
    deleted = client.delete(
        f"/v1/admin/memory/collections/juniper-private/documents/{entry.id}",
        headers=_ADMIN_HEADERS,
    )
    after_delete = client.get(
        "/v1/admin/memory/collections/juniper-private/documents",
        headers=_ADMIN_HEADERS,
    )

    assert updated.status_code == 200
    assert updated.json()["document"] == {
        "id": entry.id,
        "document": "updated text",
        "metadata": {"tags": ["edited"], "created_at_epoch": 22, "source": "admin"},
    }
    assert listed.json()["documents"][0]["document"] == "updated text"
    assert deleted.status_code == 204
    assert deleted.content == b""
    assert after_delete.json()["documents"] == []


def test_fastapi_admin_memory_creates_document(scenario):
    testclient = pytest.importorskip("fastapi.testclient")
    install_memory(scenario.actor, InMemoryStore())
    scenario.actor.world.get_entity(scenario.character).add_component(
        MemoryProfileComponent(vector_collection="juniper-private")
    )
    app = create_app(scenario.actor, with_admin=True)
    client = testclient.TestClient(app)

    created = client.post(
        "/v1/admin/memory/collections/juniper-private/documents",
        headers=_ADMIN_HEADERS,
        json={
            "document": "new memory text",
            "metadata": {"tags": "new, note", "created_at_epoch": 33, "source": "admin"},
        },
    )
    listed = client.get(
        "/v1/admin/memory/collections/juniper-private/documents",
        headers=_ADMIN_HEADERS,
    )

    assert created.status_code == 201
    body = created.json()
    assert body["collection"] == "juniper-private"
    assert body["document"]["id"]
    assert body["document"]["document"] == "new memory text"
    assert body["document"]["metadata"] == {
        "tags": ["new", "note"],
        "created_at_epoch": 33,
        "source": "admin",
    }
    assert listed.json()["documents"] == [body["document"]]
    rendered = json.dumps(body).lower()
    assert "backend" not in rendered
    assert "store" not in rendered
    assert "chroma" not in rendered


def test_fastapi_admin_memory_missing_document_returns_404(scenario):
    testclient = pytest.importorskip("fastapi.testclient")
    install_memory(scenario.actor, InMemoryStore())
    scenario.actor.world.get_entity(scenario.character).add_component(
        MemoryProfileComponent(vector_collection="juniper-private")
    )
    app = create_app(scenario.actor, with_admin=True)
    client = testclient.TestClient(app)

    updated = client.patch(
        "/v1/admin/memory/collections/juniper-private/documents/missing",
        headers=_ADMIN_HEADERS,
        json={"document": "updated text", "metadata": {}},
    )
    deleted = client.delete(
        "/v1/admin/memory/collections/juniper-private/documents/missing",
        headers=_ADMIN_HEADERS,
    )

    assert updated.status_code == 404
    assert updated.json()["detail"] == "memory document not found"
    assert deleted.status_code == 404
    assert deleted.json()["detail"] == "memory document not found"


def test_fastapi_admin_memory_returns_generic_conflict_when_unconfigured(scenario):
    testclient = pytest.importorskip("fastapi.testclient")
    app = create_app(scenario.actor, with_admin=True)
    client = testclient.TestClient(app)

    response = client.get(
        "/v1/admin/memory/collections/juniper-private/documents",
        headers=_ADMIN_HEADERS,
    )
    create_response = client.post(
        "/v1/admin/memory/collections/juniper-private/documents",
        headers=_ADMIN_HEADERS,
        json={"document": "new text", "metadata": {}},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "memory is not configured"
    assert create_response.status_code == 409
    assert create_response.json()["detail"] == "memory is not configured"
    assert "chroma" not in response.text.lower()
    assert "chroma" not in create_response.text.lower()


def test_fastapi_admin_memory_requires_admin_scope(scenario):
    testclient = pytest.importorskip("fastapi.testclient")
    store = install_memory(scenario.actor, InMemoryStore())
    store.add("juniper-private", text="secret note")
    app = create_app(scenario.actor, with_admin=True)
    client = testclient.TestClient(app)

    missing = client.get("/v1/admin/memory/collections")
    wrong = client.get(
        "/v1/admin/memory/collections/juniper-private/documents",
        headers={"Authorization": "Bearer invalid", CLIENT_ID_HEADER: "admin-a"},
    )
    wrong_create = client.post(
        "/v1/admin/memory/collections/juniper-private/documents",
        headers={"Authorization": "Bearer invalid", CLIENT_ID_HEADER: "admin-a"},
        json={"document": "new text", "metadata": {}},
    )

    assert missing.status_code == 401
    assert wrong.status_code == 401
    assert wrong_create.status_code == 401


def _admin_route_targets(app):
    # Every /admin/* path with a concrete value for each path param. The admin-secret
    # middleware runs before routing/body parsing, so a method+path with no body is enough
    # to prove the gate; HEAD/OPTIONS are skipped (FastAPI/CORS own those).
    substitutions = {
        "{collection}": "c",
        "{document_id}": "x",
        "{job_id}": "j",
        "{character_id}": "character:1",
        "{kind}": "script",
        "{name}": "x",
        "{target_kind}": "character",
        "{target_id}": "character:1",
        "{purpose}": "portrait",
    }
    targets = []
    for route in app.routes:
        path = getattr(route, "path", "")
        if not path.startswith("/v1/admin"):
            continue
        concrete = path
        for token, value in substitutions.items():
            concrete = concrete.replace(token, value)
        for method in sorted(getattr(route, "methods", set()) or set()):
            if method in {"HEAD", "OPTIONS"}:
                continue
            targets.append((method, concrete, path))
    return targets


def test_admin_routes_require_admin_bearer_scope(scenario):
    # Regression guard for the centralized admin gate: a new /admin/* route that forgets
    # authorization fails here instead of silently shipping an unauthenticated controller /
    # world-mutation primitive. With a token configured but none supplied, every admin route
    # must reject before its handler runs.
    testclient = pytest.importorskip("fastapi.testclient")
    app = create_app(scenario.actor, with_admin=True)
    client = testclient.TestClient(app, headers=app.state.test_player_headers)

    targets = _admin_route_targets(app)
    # Sanity: the introspection actually found the sensitive routes we care about.
    paths = {path for _method, _concrete, path in targets}
    assert "/v1/admin/characters/{character_id}/controller" in paths
    assert "/v1/admin/world" in paths
    assert "/v1/admin/world/generation-jobs" in paths

    for index, (method, concrete, path) in enumerate(targets):
        response = client.request(method, concrete)
        expected = 403 if index < 20 else 429
        assert response.status_code == expected, f"{method} {path} is not admin-gated"
        if expected == 403:
            assert response.json()["detail"] == "insufficient token scope"


def test_admin_routes_allow_cors_preflight_without_bearer_token(scenario):
    testclient = pytest.importorskip("fastapi.testclient")
    app = create_app(
        scenario.actor,
        with_admin=True,
        cors_origins=["http://127.0.0.1:8091"],
    )
    client = testclient.TestClient(app)

    response = client.options(
        "/v1/admin/memory/collections",
        headers={
            "Origin": "http://127.0.0.1:8091",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "Authorization",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:8091"
    assert "Authorization" in response.headers["access-control-allow-headers"]


def test_admin_gate_fails_closed_without_bearer_token(scenario):
    testclient = pytest.importorskip("fastapi.testclient")
    app = create_app(scenario.actor, token_store=TokenStore(":memory:"))
    client = testclient.TestClient(app)

    response = client.post(
        "/v1/admin/characters/character:1/controller",
        headers={
            "Authorization": "Bearer invalid",
            CLIENT_ID_HEADER: "admin-a",
        },
    )

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_fastapi_dm_projection_accepts_admin_bearer(scenario):
    testclient = pytest.importorskip("fastapi.testclient")
    app = create_app(scenario.actor, with_admin=True)
    client = testclient.TestClient(app)

    blocked = client.get(
        "/v1/admin/characters/dm-1",
        headers={"Authorization": "Bearer invalid", CLIENT_ID_HEADER: "admin-a"},
    )
    allowed = client.get("/v1/admin/characters/dm-1", headers=_ADMIN_HEADERS)

    assert blocked.status_code == 401
    assert allowed.status_code == 200
    assert allowed.json()["dm_id"] == "dm-1"


def test_fastapi_dm_projection_rejects_unknown_bearer(scenario):
    testclient = pytest.importorskip("fastapi.testclient")
    app = create_app(scenario.actor, token_store=TokenStore(":memory:"))
    client = testclient.TestClient(app)

    response = client.get(
        "/v1/admin/characters/dm-1",
        headers={"Authorization": "Bearer invalid", CLIENT_ID_HEADER: "admin-a"},
    )

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_fastapi_admin_client_id_allowlist_gates_admin_routes(scenario):
    testclient = pytest.importorskip("fastapi.testclient")
    app = create_app(
        scenario.actor,
        with_admin=True,
        admin_client_ids=["admin-a"],
    )
    client = testclient.TestClient(app)

    auth_only = {"Authorization": _ADMIN_HEADERS["Authorization"]}
    missing = client.get("/v1/admin/world", headers=auth_only)
    rejected = client.get(
        "/v1/admin/world",
        headers={**_ADMIN_HEADERS, CLIENT_ID_HEADER: "admin-b"},
    )
    allowed = client.get("/v1/admin/world", headers=_ADMIN_CLIENT_HEADERS)

    assert missing.status_code == 403
    assert missing.json()["detail"] == f"{CLIENT_ID_HEADER} header is required"
    assert rejected.status_code == 403
    assert rejected.json()["detail"] == "admin client_id is not allowed"
    assert allowed.status_code == 200


def test_room_description_prefers_long_then_short_description(scenario):
    world = scenario.actor.world
    bare = spawn_entity(world, [RoomComponent(title="Bare Room")])
    short = spawn_entity(
        world,
        [RoomComponent(title="Short Room"), DescriptionComponent(short="brief")],
    )
    long = spawn_entity(
        world,
        [
            RoomComponent(title="Long Room"),
            DescriptionComponent(short="brief", long="detailed"),
        ],
    )

    # Has a DescriptionComponent but both long and short are empty (branch 115->117).
    empty = spawn_entity(
        world,
        [RoomComponent(title="Empty Room"), DescriptionComponent(short="", long="")],
    )

    assert _room_description(bare) == "Bare Room"
    assert _room_description(short) == "Short Room - brief"
    assert _room_description(long) == "Long Room - detailed"
    assert _room_description(empty) == "Empty Room"


def test_fastapi_command_endpoint_queues_command_and_recent_events(scenario):
    testclient = pytest.importorskip("fastapi.testclient")
    app = create_app(scenario.actor)
    client = testclient.TestClient(app)
    claimed_response = client.post(
        "/v1/play/claims",
        headers={CLIENT_ID_HEADER: "client-a"},
        json={"character_id": str(scenario.character)},
    )
    claimed = claimed_response.json()
    claim_headers = {
        CLIENT_ID_HEADER: "client-a",
        "X-Bunnyland-Claim-Secret": claimed_response.headers["X-Bunnyland-Claim-Secret"],
    }

    response = client.post(
        f"/v1/play/claims/{claimed['id']}/commands",
        headers=claim_headers,
        json={
            "command_type": "move",
            "payload": {"direction": "north"},
            "cost": {"action": 1},
            "id": "cmd-http-move",
        },
    )

    assert response.status_code == 202
    assert response.json()["status"] == "queued"
    assert response.json()["id"] == "cmd-http-move"

    asyncio.run(scenario.actor.tick(0.0))

    recent = client.get(
        f"/v1/play/claims/{claimed['id']}/events",
        headers=claim_headers,
    )
    assert scenario.character_room() == scenario.room_b
    assert recent.status_code == 200
    assert any(
        message["data"]["event_type"] == "ActorMovedEvent" for message in recent.json()["events"]
    )


@pytest.mark.parametrize("verb", ["take-control", "release-to-llm", "suspend", "resume"])
def test_fastapi_command_endpoint_rejects_control_verbs(scenario, verb):
    # A claim holder must not be able to repoint their character at an arbitrary controller
    # through the generic command surface; control transitions go through the dedicated web
    # controller endpoints. The character's controller must stay put.
    testclient = pytest.importorskip("fastapi.testclient")
    app = create_app(scenario.actor)
    client = testclient.TestClient(app)
    claimed_response = client.post(
        "/v1/play/claims",
        headers={CLIENT_ID_HEADER: "client-a"},
        json={"character_id": str(scenario.character)},
    )
    claimed = claimed_response.json()
    claim_headers = {
        CLIENT_ID_HEADER: "client-a",
        "X-Bunnyland-Claim-Secret": claimed_response.headers["X-Bunnyland-Claim-Secret"],
    }
    # A controller the caller does not own — the target a hijack attempt would aim at.
    other = spawn_entity(
        scenario.actor.world, [WebControllerComponent(client_id="victim", label="other")]
    )

    response = client.post(
        f"/v1/play/claims/{claimed['id']}/commands",
        headers=claim_headers,
        json={
            "command_type": verb,
            "payload": {"controller_id": str(other.id)},
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == (
        "control verbs are not accepted here; use the web controller endpoints"
    )
    # The hijack target never became the controller.
    character = scenario.actor.world.get_entity(scenario.character)
    current = current_controller(scenario.actor, character)
    assert current is not None
    assert current[0].id != other.id


def test_fastapi_cancel_queued_command_removes_it(scenario):
    testclient = pytest.importorskip("fastapi.testclient")
    app = create_app(scenario.actor)
    client = testclient.TestClient(app)
    claimed_response = client.post(
        "/v1/play/claims",
        headers={CLIENT_ID_HEADER: "client-a"},
        json={"character_id": str(scenario.character)},
    )
    claimed = claimed_response.json()
    claim_headers = {
        CLIENT_ID_HEADER: "client-a",
        "X-Bunnyland-Claim-Secret": claimed_response.headers["X-Bunnyland-Claim-Secret"],
    }
    command = build_submitted_command(
        character_id=str(scenario.character),
        controller_id=claimed["controller_id"],
        controller_generation=claimed["controller_generation"],
        command_type="move",
        payload={"direction": "north"},
        cost=CommandCost(action=1),
        lane=Lane.WORLD,
        submitted_at_epoch=scenario.actor.epoch,
        command_id="cmd-cancel-me",
    )
    scenario.actor.queues.enqueue(command)

    response = client.delete(
        f"/v1/play/claims/{claimed['id']}/commands/cmd-cancel-me",
        headers=claim_headers,
    )
    queued = client.get(
        f"/v1/play/claims/{claimed['id']}/projection",
        headers=claim_headers,
    )

    assert response.status_code == 200
    assert response.json()["id"] == "cmd-cancel-me"
    assert response.json()["status"] == "cancelled"
    assert queued.status_code == 200
    assert queued.json()["commands"] == []

    stale = client.delete(
        f"/v1/play/claims/{claimed['id']}/commands/missing",
        headers=claim_headers,
    )
    assert stale.status_code == 200
    assert stale.json()["status"] == "rejected"


async def test_character_chat_endpoint_maps_service_exceptions(scenario):
    class FakeChat:
        allowed_tools = []

        def __init__(self, exc: Exception) -> None:
            self.exc = exc

        async def chat(self, character_id, request):
            raise self.exc

    for exc, detail in (
        (PermissionError("not allowed"), "not allowed"),
        (TypeError("bad shape"), "bad shape"),
        (ValueError("entity is not a character"), "entity is not a character"),
        (ValueError("missing character"), "missing character"),
    ):
        current = build_scenario()
        app = create_app(current.actor, character_chat=FakeChat(exc))
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            response = await client.post(
                f"/v1/chat/characters/{current.character}/jobs",
                headers={CLIENT_ID_HEADER: "client-a"},
                json={"kind": "chat", "message": "hello"},
            )
            await asyncio.sleep(0)
            result = await client.get(
                response.headers["Location"],
                headers={CLIENT_ID_HEADER: "client-a"},
            )
        assert response.status_code == 202
        assert result.json()["status"] == "failed"
        assert result.json()["failure"]["detail"] == detail


def test_fastapi_world_generation_status_endpoint_reports_idle(scenario):
    testclient = pytest.importorskip("fastapi.testclient")
    app = create_app(scenario.actor, with_admin=True)
    client = testclient.TestClient(app, headers=_ADMIN_HEADERS)

    response = client.get("/v1/admin/world/generators")

    assert response.status_code == 200
    assert response.json()["generators"] == []


def test_fastapi_runtime_endpoint_reports_attached_loop(scenario):
    testclient = pytest.importorskip("fastapi.testclient")

    class FakeLoop:
        paused = True
        running = False
        tick_seconds = 2.0
        time_scale = 1800.0
        next_tick_at_unix = None

    app = create_app(scenario.actor, loop=FakeLoop(), with_admin=True)
    client = testclient.TestClient(app, headers=_ADMIN_HEADERS)

    response = client.get("/v1/admin/world/runtime")

    assert response.status_code == 200
    assert response.json() == {
        "world_id": response.json()["world_id"],
        "world_epoch": scenario.actor.epoch,
        "paused": True,
        "running": False,
        "generated_at_unix": response.json()["generated_at_unix"],
        "next_tick_at_unix": None,
        "tick_seconds": 2.0,
        "time_scale": 1800.0,
        "game_seconds_per_tick": 3600.0,
    }
    assert isinstance(response.json()["generated_at_unix"], float)


def test_fastapi_pause_and_resume_endpoints_update_runtime(scenario):
    testclient = pytest.importorskip("fastapi.testclient")

    class FakeLoop:
        paused = False
        running = True

        def __init__(self) -> None:
            self.published: list[str] = []

        def pause(self):
            self.paused = True

            async def publish():
                self.published.append("pause")

            return publish()

        def resume(self):
            self.paused = False

            async def publish():
                self.published.append("resume")

            return publish()

    loop = FakeLoop()
    app = create_app(scenario.actor, loop=loop, with_admin=True)
    client = testclient.TestClient(app, headers=_ADMIN_HEADERS)

    paused = client.patch("/v1/admin/world/runtime", json={"paused": True})
    resumed = client.patch("/v1/admin/world/runtime", json={"paused": False})

    assert paused.status_code == 200
    assert paused.json()["paused"] is True
    assert resumed.status_code == 200
    assert resumed.json()["paused"] is False
    assert loop.published == ["pause", "resume"]


def test_fastapi_web_controller_claim_reports_bad_requests(scenario):
    testclient = pytest.importorskip("fastapi.testclient")
    app = create_app(scenario.actor)
    client = testclient.TestClient(app)
    non_character = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="Small Stone", kind="object")],
    )

    missing = client.post(
        "/v1/play/claims",
        headers={CLIENT_ID_HEADER: "client-a"},
        json={"character_id": "entity_999"},
    )
    not_character = client.post(
        "/v1/play/claims",
        headers={CLIENT_ID_HEADER: "client-a"},
        json={"character_id": str(non_character.id)},
    )
    blank_client = client.post(
        "/v1/play/claims",
        json={"character_id": str(scenario.character)},
    )

    assert missing.status_code == 404
    assert missing.json()["detail"] == "character does not exist"
    assert not_character.status_code == 400
    assert not_character.json()["detail"] == "entity is not a character"
    assert blank_client.status_code == 403
    assert blank_client.json()["detail"] == f"{CLIENT_ID_HEADER} header is required"


def test_fastapi_web_controller_claim_bounds_client_id_length(scenario):
    # An unbounded client_id would be stored and echoed verbatim; the model caps it so a
    # claim request cannot carry an oversized identifier.
    testclient = pytest.importorskip("fastapi.testclient")
    app = create_app(scenario.actor)
    client = testclient.TestClient(app)

    oversized = client.post(
        "/v1/play/claims",
        headers={CLIENT_ID_HEADER: "x" * 200},
        json={"character_id": str(scenario.character)},
    )

    assert oversized.status_code == 422


def test_fastapi_player_client_id_allowlist_gates_claims(scenario):
    testclient = pytest.importorskip("fastapi.testclient")
    app = create_app(scenario.actor, player_client_ids="client-a,,\n client-c")
    client = testclient.TestClient(app)

    rejected = client.post(
        "/v1/play/claims",
        headers={CLIENT_ID_HEADER: "client-b"},
        json={"character_id": str(scenario.character)},
    )
    allowed = client.post(
        "/v1/play/claims",
        headers={CLIENT_ID_HEADER: "client-a"},
        json={"character_id": str(scenario.character)},
    )

    assert rejected.status_code == 403
    assert rejected.json()["detail"] == "player client_id is not allowed"
    assert allowed.status_code == 201
    assert allowed.headers["X-Bunnyland-Claim-Secret"]


def test_fastapi_player_client_id_header_populates_web_claim_request(scenario):
    testclient = pytest.importorskip("fastapi.testclient")
    app = create_app(scenario.actor, player_client_ids="client-a")
    client = testclient.TestClient(app)

    rejected = client.post(
        "/v1/play/claims",
        headers={CLIENT_ID_HEADER: "client-b"},
        json={"character_id": str(scenario.character)},
    )
    response = client.post(
        "/v1/play/claims",
        headers={CLIENT_ID_HEADER: "client-a"},
        json={"character_id": str(scenario.character)},
    )

    assert rejected.status_code == 403
    assert rejected.json()["detail"] == "player client_id is not allowed"
    assert response.status_code == 201
    controller, _edge = current_controller(
        scenario.actor, scenario.actor.world.get_entity(scenario.character)
    )
    assert controller.get_component(ClaimedComponent).client_id == "client-a"


def test_fastapi_player_client_id_header_is_validated(scenario):
    testclient = pytest.importorskip("fastapi.testclient")
    app = create_app(scenario.actor)
    client = testclient.TestClient(app)

    response = client.post(
        "/v1/play/claims",
        headers={CLIENT_ID_HEADER: "x" * 200},
        json={"character_id": str(scenario.character)},
    )

    assert response.status_code == 422


def test_fastapi_world_generate_translates_start_errors(monkeypatch, scenario):
    testclient = pytest.importorskip("fastapi.testclient")
    plugins = select(bunnyland_plugins(), ["bunnyland.worldgen"])

    async def runtime_error(*args, **kwargs):
        raise RuntimeError("generator is already busy")

    monkeypatch.setattr(server_app, "start_world_generation", runtime_error)
    app = create_app(scenario.actor, plugins=plugins, with_admin=True)
    client = testclient.TestClient(app, headers=_ADMIN_HEADERS)

    conflict = client.post(
        "/v1/admin/world/generation-jobs",
        json={"kind": "world", "confirm_reset": True, "generator": "oneshot"},
    )

    assert conflict.status_code == 409
    assert conflict.json()["detail"] == "generator is already busy"

    async def unexpected_error(*args, **kwargs):
        raise ValueError("generator failed")

    monkeypatch.setattr(server_app, "start_world_generation", unexpected_error)

    failed = client.post(
        "/v1/admin/world/generation-jobs",
        json={"kind": "world", "confirm_reset": True, "generator": "oneshot"},
    )

    assert failed.status_code == 500
    assert failed.json()["detail"] == "generator failed"


@pytest.mark.parametrize(
    ("target", "path", "payload"),
    [
        (
            "generate_room_patch",
            "/v1/admin/world/generation-jobs",
            {"kind": "room", "door_entity_id": "entity_999"},
        ),
        (
            "generate_character_patch",
            "/v1/admin/world/generation-jobs",
            {"kind": "character", "room_entity_id": "entity_999"},
        ),
        (
            "generate_item_patch",
            "/v1/admin/world/generation-jobs",
            {"kind": "item", "container_entity_id": "entity_999"},
        ),
        (
            "generate_event_patch",
            "/v1/admin/world/generation-jobs",
            {"kind": "event", "room_entity_id": "entity_999"},
        ),
    ],
)
def test_fastapi_entity_generation_translates_unexpected_errors(
    monkeypatch,
    scenario,
    target,
    path,
    payload,
):
    testclient = pytest.importorskip("fastapi.testclient")

    def raise_unexpected(*args, **kwargs):
        raise RuntimeError("dm unavailable")

    monkeypatch.setattr(server_app, target, raise_unexpected)
    app = create_app(scenario.actor, with_admin=True)
    client = testclient.TestClient(app, headers=_ADMIN_HEADERS)

    response = client.post(path, json=payload)

    assert response.status_code == 500
    assert response.json()["detail"] == "dm unavailable"


def test_fastapi_save_endpoint_translates_save_errors(monkeypatch, scenario, tmp_path):
    testclient = pytest.importorskip("fastapi.testclient")

    def raise_save_error(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(server_app, "save_configured_world", raise_save_error)
    app = create_app(scenario.actor, save_path=tmp_path / "world.json", with_admin=True)
    client = testclient.TestClient(app, headers=_ADMIN_HEADERS)

    response = client.post("/v1/admin/world/checkpoints")

    assert response.status_code == 500
    assert response.json()["detail"] == "disk full"


async def test_run_loop_with_api_stops_server_when_game_loop_finishes(
    monkeypatch,
    scenario,
    tmp_path,
):
    monkeypatch.setattr("bunnyland.server.runtime.UserCredentialStore.validate", lambda _self: None)
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
        token_db_path=tmp_path / "tokens.sqlite3",
        max_ticks=7,
    )

    assert ticks == 7
    assert loop.max_ticks == 7
    assert servers[0].config["host"] == "127.0.0.1"
    assert servers[0].config["port"] == 8765
    assert servers[0].exited_after_signal is True


async def test_run_loop_with_api_stops_game_when_server_finishes(monkeypatch, scenario, tmp_path):
    monkeypatch.setattr("bunnyland.server.runtime.UserCredentialStore.validate", lambda _self: None)

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
        token_db_path=tmp_path / "tokens.sqlite3",
    )

    assert ticks == 3
    assert loop.stopped is True


def test_web_controller_claim_replaces_llm_controller_and_reuses_client(
    scenario,
    caplog,
):
    caplog.set_level("INFO", logger="bunnyland.server")
    app = create_app(scenario.actor)
    client = pytest.importorskip("fastapi.testclient").TestClient(app)
    first, secret = _create_claim(
        client,
        ClaimCreateRequest(
            character_id=str(scenario.character),
            label="toon",
            fallback_controller="llm",
            timeout_seconds=600,
        ),
    )
    reclaimed = client.put(
        f"/v1/play/claims/{first['id']}",
        headers=_claim_headers("client-a", secret),
    )
    assert reclaimed.status_code == 200
    second = reclaimed.json()

    assert first["controller_id"] == second["controller_id"]
    assert first["controller_generation"] == second["controller_generation"]
    assert first["controller_generation"] == scenario.generation + 1

    controller = scenario.actor.world.get_entity(parse_entity_id(first["controller_id"]))
    assert controller.get_component(WebControllerComponent).client_id == "client-a"
    claim = controller.get_component(ClaimTimeoutComponent)
    assert claim.fallback_controller == "llm"
    assert claim.timeout_seconds == 600
    character = scenario.actor.world.get_entity(scenario.character)
    edge, controller_id = character.get_relationships(ControlledBy)[0]
    assert str(controller_id) == first["controller_id"]
    assert edge.generation == first["controller_generation"]
    log_text = caplog.text
    assert f"character={scenario.character}" in log_text
    assert f"controller={first['controller_id']}" in log_text
    assert "client_id=client-a" in log_text


def test_web_controller_claim_unsuspends_character(scenario):
    app = create_app(scenario.actor)
    client = pytest.importorskip("fastapi.testclient").TestClient(app)
    character = scenario.actor.world.get_entity(scenario.character)
    character.add_component(SuspendedComponent(reason="offline"))

    _create_claim(client, ClaimCreateRequest(character_id=str(scenario.character), label="toon"))

    assert not character.has_component(SuspendedComponent)


def test_web_controller_claim_rejects_active_claim_conflicts(scenario):
    app = create_app(scenario.actor)
    client = pytest.importorskip("fastapi.testclient").TestClient(app)
    claimed, secret = _create_claim(
        client, ClaimCreateRequest(character_id=str(scenario.character), label="toon")
    )

    wrong_secret = client.put(
        f"/v1/play/claims/{claimed['id']}",
        headers=_claim_headers("client-a", "wrong"),
    )
    assert wrong_secret.status_code == 403
    assert wrong_secret.json()["detail"] == "invalid claim secret"

    duplicate_with_wrong_secret = client.post(
        "/v1/play/claims",
        headers=_claim_headers("client-a", "wrong"),
        json=ClaimCreateRequest(character_id=str(scenario.character)).model_dump(mode="json"),
    )
    assert duplicate_with_wrong_secret.status_code == 403
    assert duplicate_with_wrong_secret.json()["detail"] == "invalid claim secret"

    controller = scenario.actor.world.get_entity(parse_entity_id(claimed["controller_id"]))
    add_claim(
        controller,
        client_kind="mcp",
        client_id="client-a",
        character_id=str(scenario.character),
        label="toon",
        claim_id=claimed["id"],
    )

    moved = client.put(
        f"/v1/play/claims/{claimed['id']}",
        headers=_claim_headers("client-a", secret),
    )
    assert moved.status_code == 200
    assert moved.json()["id"] == claimed["id"]
    moved_controller = scenario.actor.world.get_entity(
        parse_entity_id(moved.json()["controller_id"])
    )
    assert moved_controller.get_component(ClaimedComponent).client_kind == "web"

    other_client = client.post(
        "/v1/play/claims",
        headers=_claim_headers("client-b"),
        json={"character_id": str(scenario.character)},
    )
    assert other_client.status_code == 409
    assert other_client.json()["detail"] == "character is already claimed"


def test_web_controller_claim_ignores_client_controller_claimed_for_other_character(
    scenario,
):
    app = create_app(scenario.actor)
    client = pytest.importorskip("fastapi.testclient").TestClient(app)
    other = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="Hazel", kind="character"), CharacterComponent()],
    )
    first, _secret = _create_claim(
        client, ClaimCreateRequest(character_id=str(scenario.character), label="toon")
    )
    second, _other_secret = _create_claim(
        client, ClaimCreateRequest(character_id=str(other.id), label="toon")
    )

    assert second["controller_id"] != first["controller_id"]


def test_web_controller_fallback_endpoint_updates_existing_claim(scenario):
    app = create_app(scenario.actor)
    client = pytest.importorskip("fastapi.testclient").TestClient(app)
    claimed, secret = _create_claim(
        client, ClaimCreateRequest(character_id=str(scenario.character), label="toon")
    )
    response = client.patch(
        f"/v1/play/claims/{claimed['id']}",
        headers=_claim_headers("client-a", secret),
        json=ClaimFallbackUpdate(
            kind="fallback",
            fallback_controller="llm",
            llm_model="claim-model",
            timeout_seconds=900,
        ).model_dump(mode="json", exclude_none=True),
    )
    assert response.status_code == 200
    updated = response.json()

    assert updated["controller_id"] == claimed["controller_id"]
    assert updated["controller_generation"] == claimed["controller_generation"]
    assert updated["fallback_controller"] == "llm"
    assert updated["timeout_seconds"] == 900
    controller = scenario.actor.world.get_entity(parse_entity_id(updated["controller_id"]))
    claim = controller.get_component(ClaimTimeoutComponent)
    assert claim.llm_model == "claim-model"


def test_web_command_submission_resumes_idle_claim(scenario):
    app = create_app(scenario.actor)
    client = pytest.importorskip("fastapi.testclient").TestClient(app)
    claimed, secret = _create_claim(
        client,
        ClaimCreateRequest(
            character_id=str(scenario.character),
            label="toon",
            fallback_controller="llm",
        ),
    )
    idled = client.patch(
        f"/v1/play/claims/{claimed['id']}",
        headers=_claim_headers("client-a", secret),
        json=ClaimControlUpdate(kind="control", desired="fallback").model_dump(mode="json"),
    )
    assert idled.status_code == 200
    assert idled.json()["controller_id"] != claimed["controller_id"]

    response = client.post(
        f"/v1/play/claims/{claimed['id']}/commands",
        headers=_claim_headers("client-a", secret),
        json=ClaimCommandRequest(command_type="say", payload={"text": "back"}).model_dump(
            mode="json"
        ),
    )

    assert response.status_code == 202
    assert response.json()["status"] == "rejected"
    assert response.json()["reason"] == "no handler for say"
    web_controller_id = parse_entity_id(claimed["controller_id"])
    assert web_controller_id is not None
    assert scenario.actor.current_generation(scenario.character, web_controller_id) is not None
    assert (
        scenario.actor.current_generation(
            scenario.character,
            web_controller_id,
        )
        != claimed["controller_generation"]
    )


def test_web_command_submission_with_no_controller_returns_stale_generation(scenario):
    app = create_app(scenario.actor)
    client = pytest.importorskip("fastapi.testclient").TestClient(app)
    character = scenario.actor.world.get_entity(scenario.character)
    character.remove_relationship(ControlledBy, scenario.controller)

    response = client.post(
        "/v1/play/claims/missing/commands",
        headers=_claim_headers("client-a", "wrong"),
        json=ClaimCommandRequest(command_type="say", payload={"text": "hello"}).model_dump(
            mode="json"
        ),
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "claim does not exist"


def test_web_command_submission_keeps_active_matching_web_claim(scenario):
    app = create_app(scenario.actor)
    client = pytest.importorskip("fastapi.testclient").TestClient(app)
    claimed, secret = _create_claim(
        client, ClaimCreateRequest(character_id=str(scenario.character))
    )

    response = client.post(
        f"/v1/play/claims/{claimed['id']}/commands",
        headers=_claim_headers("client-a", secret),
        json=ClaimCommandRequest(command_type="say", payload={"text": "hello"}).model_dump(
            mode="json"
        ),
    )

    assert response.status_code == 202
    assert response.json()["reason"] == "no handler for say"
    assert (
        scenario.actor.current_generation(
            scenario.character,
            parse_entity_id(claimed["controller_id"]),
        )
        == claimed["controller_generation"]
    )


def test_web_command_submission_rejects_unclaimed_and_resumes_portable_claims(
    scenario,
):
    app = create_app(scenario.actor)
    client = pytest.importorskip("fastapi.testclient").TestClient(app)
    character = scenario.actor.world.get_entity(scenario.character)

    no_claim = client.post(
        "/v1/play/claims/missing/commands",
        headers=_claim_headers("client-a", "wrong"),
        json=ClaimCommandRequest(command_type="say", payload={"text": "hello"}).model_dump(
            mode="json"
        ),
    )
    assert no_claim.status_code == 404

    claimed, secret = _create_claim(
        client, ClaimCreateRequest(character_id=str(scenario.character), label="toon")
    )
    controller = actor_controller = scenario.actor.world.get_entity(
        parse_entity_id(claimed["controller_id"])
    )
    controller.remove_component(WebControllerComponent)
    controller.add_component(MCPControllerComponent(client_id="client-a", label="toon"))
    add_claim(
        controller,
        client_kind="mcp",
        client_id="client-a",
        character_id=str(scenario.character),
        label="toon",
        claim_id=claimed["id"],
    )
    non_web = client.post(
        f"/v1/play/claims/{claimed['id']}/commands",
        headers=_claim_headers("client-a", secret),
        json=ClaimCommandRequest(command_type="say", payload={"text": "hello"}).model_dump(
            mode="json"
        ),
    )

    assert non_web.status_code == 202
    assert non_web.json()["reason"] == "no handler for say"
    active_controller_id = character.get_relationships(ControlledBy)[0][1]
    active_controller = scenario.actor.world.get_entity(active_controller_id)
    assert active_controller.id != actor_controller.id
    assert active_controller.has_component(WebControllerComponent)
    assert active_controller.get_component(ClaimedComponent).client_kind == "web"


def test_web_command_submission_rejects_mismatched_active_web_claim(scenario):
    app = create_app(scenario.actor)
    client = pytest.importorskip("fastapi.testclient").TestClient(app)
    claimed, secret = _create_claim(
        client, ClaimCreateRequest(character_id=str(scenario.character))
    )
    web = scenario.actor.world.get_entity(parse_entity_id(claimed["controller_id"]))
    replace_component(web, WebControllerComponent(client_id="wrong-client"))

    response = client.post(
        f"/v1/play/claims/{claimed['id']}/commands",
        headers=_claim_headers("client-a", secret),
        json=ClaimCommandRequest(command_type="say", payload={"text": "hello"}).model_dump(
            mode="json"
        ),
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "claim is not active for this web client"


def test_web_command_submission_resumes_idle_claim_with_new_web_controller(scenario):
    app = create_app(scenario.actor)
    client = pytest.importorskip("fastapi.testclient").TestClient(app)
    claimed, secret = _create_claim(
        client, ClaimCreateRequest(character_id=str(scenario.character), label="toon")
    )
    active = scenario.actor.world.get_entity(parse_entity_id(claimed["controller_id"]))
    idle = spawn_entity(
        scenario.actor.world,
        [LLMControllerComponent(profile_name="idle", model="claim-model")],
    )
    transfer_claim(active, idle)
    active.remove_component(WebControllerComponent)
    scenario.actor.assign_controller(scenario.character, idle.id)
    scenario.actor.world.get_entity(scenario.character).add_component(
        SuspendedComponent(reason="idle")
    )

    response = client.post(
        f"/v1/play/claims/{claimed['id']}/commands",
        headers=_claim_headers("client-a", secret),
        json=ClaimCommandRequest(command_type="say", payload={"text": "back"}).model_dump(
            mode="json"
        ),
    )

    assert response.status_code == 202
    assert response.json()["reason"] == "no handler for say"
    character = scenario.actor.world.get_entity(scenario.character)
    _edge, controller_id = character.get_relationships(ControlledBy)[0]
    assert controller_id != idle.id
    assert scenario.actor.world.get_entity(controller_id).has_component(WebControllerComponent)
    assert not character.has_component(SuspendedComponent)


def test_release_web_controller_to_llm_unsuspends_character(scenario):
    app = create_app(scenario.actor)
    client = pytest.importorskip("fastapi.testclient").TestClient(app)
    character = scenario.actor.world.get_entity(scenario.character)
    claimed, secret = _create_claim(
        client,
        ClaimCreateRequest(character_id=str(scenario.character), fallback_controller="llm"),
    )
    character.add_component(SuspendedComponent(reason="idle"))

    released = client.patch(
        f"/v1/play/claims/{claimed['id']}",
        headers=_claim_headers("client-a", secret),
        json=ClaimControlUpdate(kind="control", desired="fallback").model_dump(mode="json"),
    )

    assert released.status_code == 200
    assert released.json()["fallback_controller"] == "llm"
    assert not character.has_component(SuspendedComponent)


def test_fastapi_claimed_character_private_views_require_claim_secret(scenario):
    testclient = pytest.importorskip("fastapi.testclient")
    app = create_app(scenario.actor)
    client = testclient.TestClient(app)

    claim, secret = _create_claim(
        client, ClaimCreateRequest(character_id=str(scenario.character), label="toon")
    )

    missing_secret = client.get(
        f"/v1/play/claims/{claim['id']}/projection",
        headers=_claim_headers("client-a"),
    )
    wrong_claim = client.get(
        "/v1/play/claims/wrong/projection",
        headers=_claim_headers("client-a", secret),
    )
    allowed = client.get(
        f"/v1/play/claims/{claim['id']}/projection",
        headers=_claim_headers("client-a", secret),
    )

    assert missing_secret.status_code == 403
    assert missing_secret.json()["detail"] == "invalid claim secret"
    assert wrong_claim.status_code == 404
    assert wrong_claim.json()["detail"] == "claim does not exist"
    assert allowed.status_code == 200


def test_fastapi_release_claim_revokes_private_access(scenario):
    testclient = pytest.importorskip("fastapi.testclient")
    app = create_app(scenario.actor)
    client = testclient.TestClient(app)

    claim, secret = _create_claim(
        client, ClaimCreateRequest(character_id=str(scenario.character), label="toon")
    )
    released = client.delete(
        f"/v1/play/claims/{claim['id']}",
        headers=_claim_headers("client-a", secret),
    )
    revoked = client.get(
        f"/v1/play/claims/{claim['id']}/projection",
        headers=_claim_headers("client-a", secret),
    )

    assert released.status_code == 204
    assert revoked.status_code == 404


def test_fastapi_player_client_id_header_keeps_claim_secret_guard(scenario):
    testclient = pytest.importorskip("fastapi.testclient")
    app = create_app(scenario.actor)
    client = testclient.TestClient(app)

    claim, secret = _create_claim(
        client, ClaimCreateRequest(character_id=str(scenario.character), label="toon")
    )
    wrong_secret = client.delete(
        f"/v1/play/claims/{claim['id']}",
        headers=_claim_headers("client-a", "wrong"),
    )
    released = client.delete(
        f"/v1/play/claims/{claim['id']}",
        headers=_claim_headers("client-a", secret),
    )

    assert wrong_secret.status_code == 403
    assert wrong_secret.json()["detail"] == "invalid claim secret"
    assert released.status_code == 204


def test_fastapi_release_controller_to_suspended_fallback_retains_claim(scenario):
    testclient = pytest.importorskip("fastapi.testclient")
    app = create_app(scenario.actor)
    client = testclient.TestClient(app)

    claim, secret = _create_claim(
        client,
        ClaimCreateRequest(character_id=str(scenario.character), fallback_controller="suspend"),
    )
    idled = client.patch(
        f"/v1/play/claims/{claim['id']}",
        headers=_claim_headers("client-a", secret),
        json=ClaimControlUpdate(kind="control", desired="fallback").model_dump(mode="json"),
    )
    private_view = client.get(
        f"/v1/play/claims/{claim['id']}/projection",
        headers=_claim_headers("client-a", secret),
    )

    assert idled.status_code == 200
    assert idled.json()["fallback_controller"] == "suspend"
    assert idled.json()["id"] == claim["id"]
    assert private_view.status_code == 200


def test_web_controller_fallback_endpoint_reports_bad_requests(scenario):
    app = create_app(scenario.actor)
    client = pytest.importorskip("fastapi.testclient").TestClient(app)

    missing_character = client.post(
        "/v1/play/claims",
        headers=_claim_headers("client-a"),
        json={"character_id": "entity_999"},
    )
    assert missing_character.status_code == 404
    assert missing_character.json()["detail"] == "character does not exist"

    blank_client = client.post(
        "/v1/play/claims",
        headers={CLIENT_ID_HEADER: " "},
        json={"character_id": str(scenario.character)},
    )
    assert blank_client.status_code == 403

    claimed, secret = _create_claim(
        client, ClaimCreateRequest(character_id=str(scenario.character))
    )
    wrong_client = client.patch(
        f"/v1/play/claims/{claimed['id']}",
        headers=_claim_headers("client-b", secret),
        json=ClaimFallbackUpdate(kind="fallback", fallback_controller="llm").model_dump(
            mode="json", exclude_none=True
        ),
    )
    assert wrong_client.status_code == 403
    assert wrong_client.json()["detail"] == "claim belongs to another client"

    wrong_secret = client.patch(
        f"/v1/play/claims/{claimed['id']}",
        headers=_claim_headers("client-a", "wrong"),
        json=ClaimFallbackUpdate(kind="fallback", fallback_controller="llm").model_dump(
            mode="json", exclude_none=True
        ),
    )
    assert wrong_secret.status_code == 403
    assert wrong_secret.json()["detail"] == "invalid claim secret"

    unknown = spawn_entity(scenario.actor.world)
    unknown_controller = client.patch(
        f"/v1/play/claims/{claimed['id']}",
        headers=_claim_headers("client-a", secret),
        json=ClaimFallbackUpdate(kind="fallback", fallback_controller=str(unknown.id)).model_dump(
            mode="json", exclude_none=True
        ),
    )
    assert unknown_controller.status_code == 200
    unknown_release = client.patch(
        f"/v1/play/claims/{claimed['id']}",
        headers=_claim_headers("client-a", secret),
        json=ClaimControlUpdate(kind="control", desired="fallback").model_dump(mode="json"),
    )
    assert unknown_release.status_code == 400
    assert unknown_release.json()["detail"] == "entity is not a controller"

    invalid_fallback = client.patch(
        f"/v1/play/claims/{claimed['id']}",
        headers=_claim_headers("client-a", secret),
        json=ClaimFallbackUpdate(kind="fallback", fallback_controller="manual").model_dump(
            mode="json", exclude_none=True
        ),
    )
    assert invalid_fallback.status_code == 200
    invalid_release = client.patch(
        f"/v1/play/claims/{claimed['id']}",
        headers=_claim_headers("client-a", secret),
        json=ClaimControlUpdate(kind="control", desired="fallback").model_dump(mode="json"),
    )
    assert invalid_release.status_code == 400
    assert invalid_release.json()["detail"] == "fallback_controller is not a controller"

    existing = spawn_entity(
        scenario.actor.world,
        [LLMControllerComponent(profile_name="idle", model="claim-model")],
    )
    configured = client.patch(
        f"/v1/play/claims/{claimed['id']}",
        headers=_claim_headers("client-a", secret),
        json=ClaimFallbackUpdate(kind="fallback", fallback_controller=str(existing.id)).model_dump(
            mode="json", exclude_none=True
        ),
    )
    assert configured.status_code == 200
    released = client.patch(
        f"/v1/play/claims/{claimed['id']}",
        headers=_claim_headers("client-a", secret),
        json=ClaimControlUpdate(kind="control", desired="fallback").model_dump(mode="json"),
    )
    assert released.status_code == 200
    assert released.json()["controller_id"] == str(existing.id)


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
    reloaded, meta = load_world(path, registry=PluginRegistry(bunnyland_plugins()))
    assert reloaded.epoch == scenario.actor.epoch
    assert meta.seed == "moss"


def test_idle_generation_status_reports_current_epoch(scenario):
    status = server_admin.idle_generation_status(scenario.actor)

    assert status.status == "idle"
    assert status.world_epoch == scenario.actor.epoch


def test_admin_runtime_endpoints_require_attached_loop(scenario):
    app = create_app(scenario.actor, with_admin=True)
    client = pytest.importorskip("fastapi.testclient").TestClient(app, headers=_ADMIN_HEADERS)

    responses = [
        client.get("/v1/admin/world/runtime"),
        client.patch(
            "/v1/admin/world/runtime",
            json=RuntimePatchRequest(paused=True).model_dump(mode="json"),
        ),
        client.patch(
            "/v1/admin/world/runtime",
            json=RuntimePatchRequest(paused=False).model_dump(mode="json"),
        ),
    ]
    assert [response.status_code for response in responses] == [409, 409, 409]
    assert all(
        response.json()["detail"] == "server runtime is not attached" for response in responses
    )


def test_admin_save_endpoint_requires_configured_path(scenario):
    app = create_app(scenario.actor, with_admin=True)
    client = pytest.importorskip("fastapi.testclient").TestClient(app, headers=_ADMIN_HEADERS)

    response = client.post(
        "/v1/admin/world/checkpoints",
        json=CheckpointRequest().model_dump(mode="json"),
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "server was not started with --save"


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
        len(list(scenario.actor.world.query().with_all([CharacterComponent]).execute_entities()))
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


async def test_admin_world_generate_saves_replacement_world(scenario, tmp_path):
    plugins = select(bunnyland_plugins(), ["bunnyland.worldgen"])
    registry = collect_generators(plugins)
    meta = WorldMeta(seed="old seed", generator="oneshot")
    path = tmp_path / "generated.json"

    response = await generate_replacement_world(
        scenario.actor,
        plugins=plugins,
        generator=registry["empty"],
        seed="saved blank slate",
        options=GenOptions(),
        meta=meta,
        save_path=path,
        save=True,
    )

    reloaded, saved_meta = load_world(path, registry=PluginRegistry(bunnyland_plugins()))
    assert response.status == "succeeded"
    assert reloaded.epoch == scenario.actor.epoch
    assert saved_meta.seed == "saved blank slate"
    assert saved_meta.generator == "empty"
    assert saved_meta.plugins == ("bunnyland.worldgen",)
    assert saved_meta.saved_at_epoch == scenario.actor.epoch


async def test_admin_world_generate_requires_save_path_when_saving(scenario):
    plugins = select(bunnyland_plugins(), ["bunnyland.worldgen"])
    registry = collect_generators(plugins)

    with pytest.raises(RuntimeError, match="server was not started with --save"):
        await generate_replacement_world(
            scenario.actor,
            plugins=plugins,
            generator=registry["empty"],
            seed="unsaved blank slate",
            options=GenOptions(),
            meta=WorldMeta(),
            save=True,
        )


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


async def test_start_world_generation_requires_save_path_when_saving(scenario):
    plugins = select(bunnyland_plugins(), ["bunnyland.worldgen"])
    registry = collect_generators(plugins)

    with pytest.raises(RuntimeError, match="server was not started with --save"):
        await start_world_generation(
            scenario.actor,
            plugins=plugins,
            generator=registry["empty"],
            seed="blank",
            options=GenOptions(),
            meta=WorldMeta(),
            save=True,
        )


async def test_start_world_generation_saves_when_requested(scenario, tmp_path):
    plugins = select(bunnyland_plugins(), ["bunnyland.worldgen"])
    registry = collect_generators(plugins)
    path = tmp_path / "job-save.json"

    job = await start_world_generation(
        scenario.actor,
        plugins=plugins,
        generator=registry["recursive"],
        seed="moss job",
        options=GenOptions(max_rooms=2),
        meta=WorldMeta(),
        save_path=path,
        save=True,
    )
    assert job.task is not None
    await job.task

    assert job.status == "succeeded"
    assert job.saved is not None
    assert job.saved.path == str(path)
    reloaded, saved_meta = load_world(path, registry=PluginRegistry(bunnyland_plugins()))
    assert reloaded.epoch == scenario.actor.epoch
    assert saved_meta.seed == "moss job"


async def test_start_world_generation_publishes_failure_when_generation_raises(
    scenario, monkeypatch
):
    plugins = select(bunnyland_plugins(), ["bunnyland.worldgen"])
    registry = collect_generators(plugins)
    failures: list[WorldGenerationFailedEvent] = []
    scenario.actor.bus.subscribe(WorldGenerationFailedEvent, failures.append)

    async def explode(*args, **kwargs):
        raise RuntimeError("generation boom")

    monkeypatch.setattr(server_admin, "traced_generate", explode)

    job = await start_world_generation(
        scenario.actor,
        plugins=plugins,
        generator=registry["recursive"],
        seed="ill-fated",
        options=GenOptions(),
        meta=WorldMeta(),
    )
    assert job.task is not None
    await job.task

    assert job.status == "failed"
    assert job.error == "generation boom"
    assert failures and failures[-1].job_id == job.job_id
    assert failures[-1].error == "generation boom"


def test_admin_world_generators_lists_enabled_generators(scenario):
    plugins = select(bunnyland_plugins(), ["bunnyland.worldgen"])
    registry = collect_generators(plugins)
    app = create_app(scenario.actor, plugins=plugins, with_admin=True)
    client = pytest.importorskip("fastapi.testclient").TestClient(app, headers=_ADMIN_HEADERS)
    paths = {route.path for route in app.routes}
    response = client.get("/v1/admin/world/generators")
    assert response.status_code == 200
    generators = {item["name"]: item for item in response.json()["generators"]}

    assert "/v1/admin/world/generators" in paths
    assert "/v1/admin/world/generation-jobs/{job_id}" in paths
    assert {"empty", "oneshot", "recursive"} <= set(registry)
    assert generators["empty"]["uses_seed"] is False
    assert generators["empty"]["group"] == "administrative"
    assert generators["oneshot"]["uses_seed"] is True
    assert generators["oneshot"]["group"] == "algorithmic"
    assert generators["recursive"]["uses_seed"] is True
    assert generators["recursive"]["group"] == "algorithmic"


def test_admin_world_generate_defaults_to_recursive_when_available(scenario):
    plugins = select(bunnyland_plugins(), ["bunnyland.worldgen"])
    meta = WorldMeta(seed="old seed", generator="oneshot")
    app = create_app(scenario.actor, meta=meta, plugins=plugins, with_admin=True)
    client = pytest.importorskip("fastapi.testclient").TestClient(app, headers=_ADMIN_HEADERS)
    response = client.post(
        "/v1/admin/world/generation-jobs",
        json=GenerateWorldRequest(kind="world", confirm_reset=True, seed="rain port").model_dump(
            mode="json"
        ),
    )

    assert response.status_code == 202
    assert response.json()["result"]["generator"] == "recursive"


def test_admin_world_generate_endpoint_reports_precondition_errors(scenario):
    app_without_plugins = create_app(scenario.actor, with_admin=True)
    client = pytest.importorskip("fastapi.testclient").TestClient(
        app_without_plugins, headers=_ADMIN_HEADERS
    )

    unconfirmed = client.post(
        "/v1/admin/world/generation-jobs",
        json=GenerateWorldRequest(kind="world").model_dump(mode="json"),
    )
    assert unconfirmed.status_code == 400
    assert unconfirmed.json()["detail"] == "confirm_reset must be true"

    no_registry = client.post(
        "/v1/admin/world/generation-jobs",
        json=GenerateWorldRequest(kind="world", confirm_reset=True).model_dump(mode="json"),
    )
    assert no_registry.status_code == 409
    assert no_registry.json()["detail"] == (
        "server was not started with a world generator registry"
    )

    plugins = select(bunnyland_plugins(), ["bunnyland.worldgen"])
    app = create_app(scenario.actor, plugins=plugins, with_admin=True)
    client = pytest.importorskip("fastapi.testclient").TestClient(app, headers=_ADMIN_HEADERS)
    unknown = client.post(
        "/v1/admin/world/generation-jobs",
        json=GenerateWorldRequest(kind="world", confirm_reset=True, generator="missing").model_dump(
            mode="json"
        ),
    )
    assert unknown.status_code == 400
    assert "unknown generator 'missing'" in unknown.json()["detail"]


def test_admin_patch_endpoint_translates_patch_errors_to_http_400(scenario):
    app = create_app(scenario.actor, with_admin=True)
    client = pytest.importorskip("fastapi.testclient").TestClient(app, headers=_ADMIN_HEADERS)
    request = WorldPatchRequest.model_validate(
        {"operations": [{"op": "delete_entity", "entity_id": "entity_999"}]}
    )
    response = client.patch("/v1/admin/world", json=request.model_dump(mode="json"))

    assert response.status_code == 400
    assert response.json()["detail"] == "entity 'entity_999' does not exist"


def test_fastapi_list_controller_definitions_endpoint(scenario):
    testclient = pytest.importorskip("fastapi.testclient")
    app = create_app(scenario.actor, with_admin=True)
    client = testclient.TestClient(app, headers=_ADMIN_HEADERS)

    response = client.get("/v1/admin/controller-definitions")

    assert response.status_code == 200
    body = response.json()
    assert "scripts" in body
    assert "behaviors" in body
    assert "stored" in body


def test_admin_controller_assign_to_unsuspended_character(scenario):
    # The character starts unsuspended, so the assign path skips the SuspendedComponent
    # removal branch entirely (the False side of that guard).
    controller = spawn_entity(
        scenario.actor.world,
        [WebControllerComponent(client_id="op2", label="graph")],
    )
    assert not scenario.actor.world.get_entity(scenario.character).has_component(SuspendedComponent)

    app = create_app(scenario.actor, with_admin=True)
    client = pytest.importorskip("fastapi.testclient").TestClient(app, headers=_ADMIN_HEADERS)
    response = client.put(
        f"/v1/admin/characters/{scenario.character}/controller",
        json=ControllerAssignment(controller_id=str(controller.id)).model_dump(mode="json"),
    )

    assert response.status_code == 200
    character = scenario.actor.world.get_entity(scenario.character)
    assert not character.has_component(SuspendedComponent)
    _edge, target = character.get_relationships(ControlledBy)[0]
    assert target == controller.id


def test_create_app_requires_fastapi(scenario, monkeypatch):
    monkeypatch.setattr(server_app, "FastAPI", None)
    with pytest.raises(RuntimeError, match="requires FastAPI"):
        create_app(scenario.actor)


def test_fastapi_dm_projection_translates_value_errors_to_400(scenario):
    testclient = pytest.importorskip("fastapi.testclient")
    app = create_app(scenario.actor, with_admin=True)
    client = testclient.TestClient(app)

    # A whitespace-only dm id strips to empty and raises ValueError from the serializer.
    response = client.get("/v1/admin/characters/%20", headers=_ADMIN_HEADERS)

    assert response.status_code == 400
    assert response.json()["detail"] == "dm id must not be blank"


def test_runtime_timing_projects_next_tick_for_running_loop(scenario):
    testclient = pytest.importorskip("fastapi.testclient")

    class RunningLoop:
        paused = False
        running = True
        tick_seconds = 4.0
        time_scale = 60.0
        next_tick_at_unix = None

    app = create_app(scenario.actor, loop=RunningLoop(), with_admin=True)
    client = testclient.TestClient(app, headers=_ADMIN_HEADERS)

    body = client.get("/v1/admin/world/runtime").json()

    # A running, unpaused loop with no explicit next_tick computes one from now + tick_seconds.
    assert body["next_tick_at_unix"] is not None
    assert body["next_tick_at_unix"] > body["generated_at_unix"]


def test_fastapi_cancel_command_rejects_missing_and_non_character(scenario):
    testclient = pytest.importorskip("fastapi.testclient")
    app = create_app(scenario.actor)
    client = testclient.TestClient(app)
    missing = client.delete(
        "/v1/play/claims/missing/commands/cmd-x",
        headers=_claim_headers("client-a", "wrong"),
    )

    assert missing.status_code == 404
    assert missing.json()["detail"] == "claim does not exist"


def test_fastapi_cancel_command_reports_not_found_when_command_absent(scenario):
    testclient = pytest.importorskip("fastapi.testclient")
    app = create_app(scenario.actor)
    client = testclient.TestClient(app)
    claimed, secret = _create_claim(
        client, ClaimCreateRequest(character_id=str(scenario.character))
    )

    # Valid character + generation but no such queued command -> ok=False, "command not found".
    response = client.delete(
        f"/v1/play/claims/{claimed['id']}/commands/never-queued",
        headers=_claim_headers("client-a", secret),
    )

    assert response.status_code == 200
    assert response.json()["id"] == "never-queued"
    assert response.json()["status"] == "rejected"
    assert response.json()["reason"] == "command not found"


def test_admin_patch_endpoint_translates_unexpected_errors_to_400(scenario, monkeypatch):
    def boom(actor, request):
        raise RuntimeError("ecs exploded")

    monkeypatch.setattr(server_app, "apply_world_patch", boom)
    app = create_app(scenario.actor, with_admin=True)
    client = pytest.importorskip("fastapi.testclient").TestClient(app, headers=_ADMIN_HEADERS)
    request = WorldPatchRequest.model_validate({"operations": []})
    response = client.patch("/v1/admin/world", json=request.model_dump(mode="json"))

    assert response.status_code == 400
    assert response.json()["detail"] == "ecs exploded"


def test_register_script_endpoint_persists_valid_spec(scenario, tmp_path):
    app = create_app(
        scenario.actor, definitions_path=tmp_path / "definitions.json", with_admin=True
    )
    client = pytest.importorskip("fastapi.testclient").TestClient(app, headers=_ADMIN_HEADERS)
    spec = ScriptSpec(name="greeter", calls=(ToolCallSpec(name="wait", arguments={}),))
    response = client.put(
        "/v1/admin/controller-definitions/script/greeter",
        json=ControllerDefinitionRequest(
            definition=spec.model_dump(mode="json", exclude={"name"})
        ).model_dump(mode="json"),
    )

    assert response.status_code == 200
    assert "greeter" in response.json()["stored"]["scripts"]


def test_register_behavior_endpoint_persists_valid_spec(scenario, tmp_path):
    app = create_app(
        scenario.actor, definitions_path=tmp_path / "definitions.json", with_admin=True
    )
    client = pytest.importorskip("fastapi.testclient").TestClient(app, headers=_ADMIN_HEADERS)
    spec = BehaviorTreeSpec(
        name="waiter",
        root=BehaviorNodeSpec(kind="action", ref="take_first_item"),
    )
    response = client.put(
        "/v1/admin/controller-definitions/behavior/waiter",
        json=ControllerDefinitionRequest(
            definition=spec.model_dump(mode="json", exclude={"name"})
        ).model_dump(mode="json"),
    )

    assert response.status_code == 200
    assert "waiter" in response.json()["stored"]["behaviors"]


def test_register_behavior_endpoint_translates_value_errors(scenario):
    app = create_app(scenario.actor, with_admin=True)
    client = pytest.importorskip("fastapi.testclient").TestClient(app, headers=_ADMIN_HEADERS)

    # A behavior leaf referencing an unknown condition fails to compile -> ValueError -> 400.
    bad = BehaviorTreeSpec(
        name="broken",
        root=BehaviorNodeSpec(kind="condition", ref="definitely_not_a_real_condition"),
    )
    response = client.put(
        "/v1/admin/controller-definitions/behavior/broken",
        json=ControllerDefinitionRequest(
            definition=bad.model_dump(mode="json", exclude={"name"})
        ).model_dump(mode="json"),
    )

    assert response.status_code == 400


def test_register_script_endpoint_translates_value_errors(scenario):
    app = create_app(scenario.actor, with_admin=True)
    client = pytest.importorskip("fastapi.testclient").TestClient(app, headers=_ADMIN_HEADERS)

    # A script call referencing an unknown tool fails to compile -> ValueError -> 400.
    bad = ScriptSpec(
        name="broken",
        calls=(ToolCallSpec(name="definitely_not_a_real_tool", arguments={}),),
    )
    response = client.put(
        "/v1/admin/controller-definitions/script/broken",
        json=ControllerDefinitionRequest(
            definition=bad.model_dump(mode="json", exclude={"name"})
        ).model_dump(mode="json"),
    )

    assert response.status_code == 400
    assert "definitely_not_a_real_tool" in response.json()["detail"]


async def test_world_updates_websocket_handles_disconnect_on_send(scenario, monkeypatch):
    from fastapi import WebSocketDisconnect

    app = create_app(scenario.actor, meta=WorldMeta(seed="moss"), with_admin=True)
    route = next(route for route in app.routes if route.path == "/v1/admin/world/stream")

    closed = []
    monkeypatch.setattr(server_app, "WEBSOCKET_HEARTBEAT_SECONDS", 0.01)

    class FakeWebSocket:
        headers = _ADMIN_HEADERS
        cookies = {}
        sent = 0

        async def accept(self):
            return None

        async def receive_json(self):
            return {"type": "authenticate", "data": {}}

        async def send_json(self, _payload):
            self.sent += 1
            # The snapshot succeeds; the client vanishes on the next heartbeat.
            if self.sent == 2:
                raise WebSocketDisconnect(code=1006)

        async def close(self, code=1000):
            closed.append(code)

    # Should not raise: the handler catches WebSocketDisconnect and still closes the
    # subscription in its finally block.
    await route.endpoint(FakeWebSocket())


async def test_world_generation_status_endpoint_reports_running_job(scenario, monkeypatch):
    plugins = select(bunnyland_plugins(), ["bunnyland.worldgen"])
    app = create_app(scenario.actor, plugins=plugins, with_admin=True)
    release_generation = asyncio.Event()
    original_generate = server_admin.traced_generate

    async def delayed_generate(*args, **kwargs):
        await release_generation.wait()
        return await original_generate(*args, **kwargs)

    monkeypatch.setattr(server_admin, "traced_generate", delayed_generate)
    request = GenerateWorldRequest(
        kind="world", confirm_reset=True, generator="recursive", max_rooms=2
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
        headers=_ADMIN_HEADERS,
    ) as client:
        started = await client.post(
            "/v1/admin/world/generation-jobs", json=request.model_dump(mode="json")
        )
        assert started.status_code == 202
        job_id = started.json()["id"]

        # While the background job exists, status reflects it (not the idle response).
        running = await client.get(f"/v1/admin/world/generation-jobs/{job_id}")
        assert running.status_code == 200
        assert running.json()["id"] == job_id

        # A second generate while running is rejected with a conflict.
        conflict = await client.post(
            "/v1/admin/world/generation-jobs",
            json=GenerateWorldRequest(
                kind="world", confirm_reset=True, generator="recursive"
            ).model_dump(mode="json"),
        )
        assert conflict.status_code == 409
        assert conflict.json()["detail"] == "world generation is already running"
        release_generation.set()


def test_admin_world_generate_uses_generator_name_for_seedless_generators(scenario):
    plugins = select(bunnyland_plugins(), ["bunnyland.worldgen"])
    app = create_app(scenario.actor, plugins=plugins, with_admin=True)
    client = pytest.importorskip("fastapi.testclient").TestClient(app, headers=_ADMIN_HEADERS)

    # "empty" reports uses_seed=False, so the seed must be the generator name, not the request.
    response = client.post(
        "/v1/admin/world/generation-jobs",
        json=GenerateWorldRequest(
            kind="world", confirm_reset=True, generator="empty", seed="ignored"
        ).model_dump(mode="json"),
    )

    assert response.status_code == 202
    assert response.json()["result"]["generator"] == "empty"
    assert response.json()["result"]["seed"] == "empty"


def test_pause_and_resume_tolerate_loops_without_publish(scenario):
    testclient = pytest.importorskip("fastapi.testclient")

    class QuietLoop:
        paused = False
        running = True

        def pause(self):
            self.paused = True
            return None

        def resume(self):
            self.paused = False
            return None

    app = create_app(scenario.actor, loop=QuietLoop(), with_admin=True)
    client = testclient.TestClient(app, headers=_ADMIN_HEADERS)

    paused = client.patch(
        "/v1/admin/world/runtime",
        json=RuntimePatchRequest(paused=True).model_dump(mode="json"),
    )
    resumed = client.patch(
        "/v1/admin/world/runtime",
        json=RuntimePatchRequest(paused=False).model_dump(mode="json"),
    )

    assert paused.status_code == 200
    assert paused.json()["paused"] is True
    assert resumed.status_code == 200
    assert resumed.json()["paused"] is False


async def test_fastapi_world_updates_websocket_handles_client_disconnect(scenario):
    app = create_app(scenario.actor, meta=WorldMeta(seed="moss"), with_admin=True)

    outputs = await _websocket_outputs(
        app,
        "/v1/admin/world/stream",
        headers=_ADMIN_HEADERS,
        messages=[
            {
                "type": "authenticate",
                "data": {"client_id": _ADMIN_HEADERS[CLIENT_ID_HEADER]},
            }
        ],
    )

    assert outputs[0]["type"] == "websocket.accept"
    assert json.loads(outputs[1]["text"])["type"] == "snapshot"


def test_admin_controller_assign_endpoint_uses_controller_handoff(scenario):
    controller = spawn_entity(
        scenario.actor.world,
        [WebControllerComponent(client_id="operator", label="graph")],
    )
    scenario.actor.world.get_entity(scenario.character).add_component(
        SuspendedComponent(reason="old")
    )
    command = CommandRequest(
        character_id=str(scenario.character),
        controller_id=str(scenario.controller),
        controller_generation=scenario.generation,
        command_type="say",
        payload={"text": "stale"},
        command_id="cmd-stale",
    ).to_submitted(submitted_at_epoch=42)
    scenario.actor.queues.enqueue(command)

    app = create_app(scenario.actor, with_admin=True)
    client = pytest.importorskip("fastapi.testclient").TestClient(app, headers=_ADMIN_HEADERS)
    response = client.put(
        f"/v1/admin/characters/{scenario.character}/controller",
        json=ControllerAssignment(controller_id=str(controller.id)).model_dump(mode="json"),
    )

    assert response.status_code == 200
    assert response.json()["changed_entities"][0]["id"] == str(scenario.character)
    character = scenario.actor.world.get_entity(scenario.character)
    controlled = character.get_relationships(ControlledBy)
    assert len(controlled) == 1
    edge, target = controlled[0]
    assert target == controller.id
    assert edge.generation == scenario.generation + 1
    assert scenario.actor.queues.pending(str(scenario.character)) == []
    assert not character.has_component(SuspendedComponent)


def test_admin_controller_assign_endpoint_suspends_character(scenario):
    controller = spawn_entity(
        scenario.actor.world,
        [SuspendedControllerComponent(reason="admin pause")],
    )

    app = create_app(scenario.actor, with_admin=True)
    client = pytest.importorskip("fastapi.testclient").TestClient(app, headers=_ADMIN_HEADERS)
    response = client.put(
        f"/v1/admin/characters/{scenario.character}/controller",
        json=ControllerAssignment(controller_id=str(controller.id)).model_dump(mode="json"),
    )

    assert response.status_code == 200
    character = scenario.actor.world.get_entity(scenario.character)
    assert character.get_component(SuspendedComponent).reason == "admin pause"
    edge, target = character.get_relationships(ControlledBy)[0]
    assert target == controller.id
    assert edge.generation == scenario.generation + 1


@pytest.mark.parametrize(
    ("character_id", "controller_id", "status", "message"),
    [
        (
            "entity_999",
            "$controller",
            404,
            "character does not exist",
        ),
        (
            "$character",
            "entity_999",
            404,
            "controller does not exist",
        ),
        (
            "$room",
            "$controller",
            400,
            "entity is not a character",
        ),
        (
            "$character",
            "$room",
            400,
            "entity is not a controller",
        ),
    ],
)
def test_admin_controller_assign_endpoint_rejects_invalid_targets(
    scenario,
    character_id,
    controller_id,
    status,
    message,
):
    app = create_app(scenario.actor, with_admin=True)
    client = pytest.importorskip("fastapi.testclient").TestClient(app, headers=_ADMIN_HEADERS)

    def render(value: str) -> str:
        return (
            value.replace("$character", str(scenario.character))
            .replace("$controller", str(scenario.controller))
            .replace("$room", str(scenario.room_a))
        )

    response = client.put(
        f"/v1/admin/characters/{render(character_id)}/controller",
        json=ControllerAssignment(controller_id=render(controller_id)).model_dump(mode="json"),
    )

    assert response.status_code == status
    assert response.json()["detail"] == message


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (
            GenerateRoomRequest(kind="room", door_entity_id="entity_999"),
            "door entity 'entity_999' does not exist",
        ),
        (
            GenerateCharacterRequest(kind="character", room_entity_id="entity_999"),
            "room entity 'entity_999' does not exist",
        ),
        (
            GenerateItemRequest(kind="item", container_entity_id="entity_999"),
            "container entity 'entity_999' does not exist",
        ),
        (
            GenerateEventRequest(kind="event", room_entity_id="entity_999"),
            "room entity 'entity_999' does not exist",
        ),
    ],
)
def test_admin_entity_generation_endpoints_translate_patch_errors(
    scenario,
    payload,
    message,
):
    app = create_app(scenario.actor, with_admin=True)
    client = pytest.importorskip("fastapi.testclient").TestClient(app, headers=_ADMIN_HEADERS)
    response = client.post(
        "/v1/admin/world/generation-jobs",
        json=payload.model_dump(mode="json", exclude_none=True),
    )

    assert response.status_code == 400
    assert response.json()["detail"] == message


def test_v1_claim_can_reactivate_after_fallback(scenario):
    app = create_app(scenario.actor)
    client = pytest.importorskip("fastapi.testclient").TestClient(app)
    claim, secret = _create_claim(
        client,
        ClaimCreateRequest(
            character_id=str(scenario.character),
            fallback_controller="llm",
        ),
    )
    headers = _claim_headers("client-a", secret)

    already_active = client.patch(
        f"/v1/play/claims/{claim['id']}",
        headers=headers,
        json=ClaimControlUpdate(kind="control", desired="active").model_dump(mode="json"),
    )
    released = client.patch(
        f"/v1/play/claims/{claim['id']}",
        headers=headers,
        json=ClaimControlUpdate(kind="control", desired="fallback").model_dump(mode="json"),
    )
    reactivated = client.patch(
        f"/v1/play/claims/{claim['id']}",
        headers=headers,
        json=ClaimControlUpdate(kind="control", desired="active").model_dump(mode="json"),
    )

    assert already_active.status_code == 200
    assert already_active.json()["control"] == "active"
    assert released.status_code == 200
    assert reactivated.status_code == 200
    assert reactivated.json()["control"] == "active"


def test_v1_claim_rejects_inactive_claim_controller(scenario):
    app = create_app(scenario.actor)
    client = pytest.importorskip("fastapi.testclient").TestClient(app)
    claim, secret = _create_claim(client, ClaimCreateRequest(character_id=str(scenario.character)))
    replacement = spawn_entity(
        scenario.actor.world,
        [LLMControllerComponent(profile_name="idle", model="claim-model")],
    )
    scenario.actor.assign_controller(scenario.character, replacement.id)

    response = client.get(
        f"/v1/play/claims/{claim['id']}/projection",
        headers=_claim_headers("client-a", secret),
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "claim controller is not active"


async def test_v1_claim_endpoint_requires_client_identity_when_called_directly(scenario):
    app = create_app(scenario.actor)
    route = next(
        route for route in app.routes if route.path == "/v1/play/claims/{claim_id}/projection"
    )

    with pytest.raises(server_app.HTTPException, match=f"{CLIENT_ID_HEADER} header is required"):
        await route.endpoint("missing", None, None)


def test_v1_claim_events_support_incremental_reads(scenario):
    app = create_app(scenario.actor)
    client = pytest.importorskip("fastapi.testclient").TestClient(app)
    claim, secret = _create_claim(client, ClaimCreateRequest(character_id=str(scenario.character)))

    response = client.get(
        f"/v1/play/claims/{claim['id']}/events?since=0",
        headers=_claim_headers("client-a", secret),
    )

    assert response.status_code == 200
    assert response.json()["complete"] is True
    assert response.json()["available_after_epoch"] is not None


def test_v1_player_jobs_get_list_and_isolate_claims(scenario):
    class FakeImageService:
        def __init__(self) -> None:
            self.next_id = 0
            self.jobs: dict[str, ImageGenJob] = {}

        async def start(self, entity_id: str, purpose: ImagePurpose, **_kwargs) -> ImageGenJob:
            self.next_id += 1
            job = ImageGenJob(
                job_id=f"scene-{self.next_id}",
                entity_id=entity_id,
                purpose=purpose,
                status="complete",
            )
            self.jobs[job.job_id] = job
            return job

        def job(self, job_id: str) -> ImageGenJob | None:
            return None

    other = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="Hazel", kind="character"), CharacterComponent()],
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), other.id
    )
    app = create_app(scenario.actor, imagegen=FakeImageService())
    client = pytest.importorskip("fastapi.testclient").TestClient(app)
    first, first_secret = _create_claim(
        client, ClaimCreateRequest(character_id=str(scenario.character))
    )
    second, second_secret = _create_claim(client, ClaimCreateRequest(character_id=str(other.id)))

    first_job = client.post(
        f"/v1/play/claims/{first['id']}/jobs",
        headers=_claim_headers("client-a", first_secret),
        json={"kind": "scene_image"},
    )
    second_job = client.post(
        f"/v1/play/claims/{second['id']}/jobs",
        headers=_claim_headers("client-a", second_secret),
        json={"kind": "scene_image"},
    )
    listed = client.get(
        f"/v1/play/claims/{first['id']}/jobs",
        headers=_claim_headers("client-a", first_secret),
    )
    fetched = client.get(
        f"/v1/play/claims/{first['id']}/jobs/{first_job.json()['id']}",
        headers=_claim_headers("client-a", first_secret),
    )
    missing = client.get(
        f"/v1/play/claims/{first['id']}/jobs/missing",
        headers=_claim_headers("client-a", first_secret),
    )

    assert first_job.status_code == 202
    assert second_job.status_code == 202
    assert [job["id"] for job in listed.json()] == [first_job.json()["id"]]
    assert fetched.json()["id"] == first_job.json()["id"]
    assert missing.status_code == 404


def test_v1_chat_job_keeps_existing_llm_controller(scenario):
    class FakeChat:
        allowed_tools: tuple[str, ...] = ()

        async def chat(self, character_id: str, request) -> CharacterChatResponse:
            return CharacterChatResponse(
                world_epoch=scenario.actor.epoch,
                character_id=character_id,
                reply=request.message,
            )

    app = create_app(scenario.actor, character_chat=FakeChat())
    client = pytest.importorskip("fastapi.testclient").TestClient(app)
    llm = spawn_entity(
        scenario.actor.world,
        [LLMControllerComponent(profile_name="idle", model="claim-model")],
    )
    scenario.actor.assign_controller(scenario.character, llm.id)

    response = client.post(
        f"/v1/chat/characters/{scenario.character}/jobs",
        headers={CLIENT_ID_HEADER: "client-a"},
        json=ChatJobRequest(kind="chat", message="hello").model_dump(mode="json"),
    )
    for _attempt in range(20):
        result = client.get(response.headers["Location"], headers={CLIENT_ID_HEADER: "client-a"})
        if result.json()["status"] == "succeeded":
            break

    assert response.status_code == 202
    assert result.json()["result"]["reply"] == "hello"
    assert (
        current_controller(scenario.actor, scenario.actor.world.get_entity(scenario.character))[
            0
        ].id
        == llm.id
    )


def test_v1_generation_jobs_normalize_status_and_refresh_absent_jobs(scenario):
    class FakeImageService:
        def __init__(self, status: str, *, retain: bool = True) -> None:
            self.status = status
            self.retain = retain
            self.jobs: dict[str, ImageGenJob] = {}

        async def start(self, entity_id: str, purpose: ImagePurpose, **_kwargs) -> ImageGenJob:
            job = ImageGenJob(
                job_id=f"job-{self.status}",
                entity_id=entity_id,
                purpose=purpose,
                status=self.status,
                error="generation failed" if self.status == "mystery" else None,
            )
            self.jobs[job.job_id] = job
            return job

        def job(self, job_id: str) -> ImageGenJob | None:
            return self.jobs.get(job_id) if self.retain else None

    request = GenerateImageRequest(
        kind="image",
        entity_id=str(scenario.character),
        purpose="portrait",
    )
    testclient = pytest.importorskip("fastapi.testclient")

    completed = testclient.TestClient(
        create_app(scenario.actor, imagegen=FakeImageService("complete"), with_admin=True),
        headers=_ADMIN_HEADERS,
    ).post("/v1/admin/world/generation-jobs", json=request.model_dump(mode="json"))
    failed = testclient.TestClient(
        create_app(scenario.actor, imagegen=FakeImageService("mystery"), with_admin=True),
        headers=_ADMIN_HEADERS,
    ).post("/v1/admin/world/generation-jobs", json=request.model_dump(mode="json"))
    absent_client = testclient.TestClient(
        create_app(
            scenario.actor,
            imagegen=FakeImageService("queued", retain=False),
            with_admin=True,
        ),
        headers=_ADMIN_HEADERS,
    )
    absent = absent_client.post(
        "/v1/admin/world/generation-jobs", json=request.model_dump(mode="json")
    )
    absent_refreshed = absent_client.get(
        f"/v1/admin/world/generation-jobs/{absent.json()['id']}"
    )

    assert completed.json()["status"] == "succeeded"
    assert failed.json()["status"] == "failed"
    assert failed.json()["failure"]["code"] == "job_failed"
    assert absent.json()["status"] == "queued"
    assert absent_refreshed.json()["status"] == "queued"


def test_v1_non_world_generation_job_is_stable_on_refresh(scenario, monkeypatch):
    async def generated_room(*_args, **_kwargs) -> WorldRoomGenerationResponse:
        return WorldRoomGenerationResponse(
            source_room_id=str(scenario.room_a),
            door_entity_id="door:generated",
            generated_title="Moss Room",
            patch=WorldPatchRequest(operations=[]),
        )

    monkeypatch.setattr(server_app, "generate_room_patch", generated_room)
    app = create_app(scenario.actor, with_admin=True)
    client = pytest.importorskip("fastapi.testclient").TestClient(app, headers=_ADMIN_HEADERS)
    request = GenerateRoomRequest(kind="room", door_entity_id="door:any")

    created = client.post("/v1/admin/world/generation-jobs", json=request.model_dump(mode="json"))
    fetched = client.get(f"/v1/admin/world/generation-jobs/{created.json()['id']}")

    assert created.status_code == 202
    assert fetched.status_code == 200
    assert fetched.json() == created.json()


def test_v1_controller_definition_rejects_unknown_kind(scenario):
    app = create_app(scenario.actor, with_admin=True)
    client = pytest.importorskip("fastapi.testclient").TestClient(app, headers=_ADMIN_HEADERS)
    request = ControllerDefinitionRequest(definition={})

    response = client.put(
        "/v1/admin/controller-definitions/unknown/example",
        json=request.model_dump(mode="json"),
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "kind must be script or behavior"


def test_v1_memory_document_gets_existing_and_missing_documents(scenario):
    install_memory(scenario.actor, InMemoryStore())
    scenario.actor.world.get_entity(scenario.character).add_component(
        MemoryProfileComponent(vector_collection="juniper-private")
    )
    app = create_app(scenario.actor, with_admin=True)
    client = pytest.importorskip("fastapi.testclient").TestClient(app, headers=_ADMIN_HEADERS)
    request = MemoryDocumentUpdateRequest(document="A remembered path", metadata={})
    created = client.post(
        "/v1/admin/memory/collections/juniper-private/documents",
        json=request.model_dump(mode="json"),
    )

    found = client.get(
        f"/v1/admin/memory/collections/juniper-private/documents/{created.json()['document']['id']}"
    )
    missing = client.get("/v1/admin/memory/collections/juniper-private/documents/missing")

    assert found.status_code == 200
    assert found.json()["document"]["document"] == "A remembered path"
    assert missing.status_code == 404


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


def test_world_schema_includes_discord_room_feed_component(scenario):
    schema = world_schema(scenario.actor)

    assert "DiscordRoomFeedComponent" in schema.components
    room_feed_schema = schema.components["DiscordRoomFeedComponent"].json_schema
    assert room_feed_schema["properties"]["channel_id"]["type"] == "integer"
    assert "channel_id" in room_feed_schema["required"]


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


async def test_worldgen_passes_live_schema_context_to_dm_entity_generation(scenario, monkeypatch):
    captured = {}

    class CapturingBuilder:
        async def propose_room(
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

        async def propose_contents(self, room, *, known_rooms, schema_context=""):
            del room, known_rooms
            captured["contents"] = schema_context
            return RoomContentsProposal()

        async def propose_doors(self, room, *, schema_context=""):
            del room
            captured["doors"] = schema_context
            return [DoorProposal(direction="north")]

        async def propose_character(self, room, *, prompt, known_rooms, schema_context=""):
            del room, prompt, known_rooms
            captured["character"] = schema_context
            return CharacterProposal(name="Schema Bun")

        async def propose_item(
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

        async def propose_event(self, room, *, prompt, known_rooms, schema_context=""):
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

    await generate_room_patch(
        scenario.actor,
        WorldRoomGenerationRequest(door_entity_id=str(door.id), direction="east"),
        options=GenOptions(llm=True),
    )
    await generate_character_patch(
        scenario.actor,
        WorldCharacterGenerationRequest(room_entity_id=str(scenario.room_a), prompt="bun"),
        options=GenOptions(llm=True),
    )
    await generate_item_patch(
        scenario.actor,
        WorldItemGenerationRequest(container_entity_id=str(scenario.room_a), prompt="bell"),
        options=GenOptions(llm=True),
    )
    await generate_event_patch(
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


def test_world_patch_adds_component_to_existing_entity(scenario):
    response = apply_world_patch(
        scenario.actor,
        WorldPatchRequest.model_validate(
            {
                "operations": [
                    {
                        "op": "add_component",
                        "entity_id": str(scenario.character),
                        "component": {
                            "type": "SuspendedComponent",
                            "fields": {"reason": "editor"},
                        },
                    },
                ]
            }
        ),
    )

    character = scenario.actor.world.get_entity(scenario.character)
    assert response.ok is True
    assert response.changed_entities[0]["id"] == str(scenario.character)
    assert character.get_component(SuspendedComponent).reason == "editor"


def test_world_patch_adds_discord_room_feed_component_by_type_name(scenario):
    response = apply_world_patch(
        scenario.actor,
        WorldPatchRequest.model_validate(
            {
                "operations": [
                    {
                        "op": "add_component",
                        "entity_id": str(scenario.room_a),
                        "component": {
                            "type": "DiscordRoomFeedComponent",
                            "fields": {"channel_id": 123456789},
                        },
                    },
                ]
            }
        ),
    )

    room = scenario.actor.world.get_entity(scenario.room_a)
    assert response.ok is True
    assert room.get_component(DiscordRoomFeedComponent).channel_id == 123456789


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


def test_world_patch_can_delete_a_new_alias_atomically(scenario):
    before_ids = {entity.id for entity in scenario.actor.world.query().execute_entities()}

    response = apply_world_patch(
        scenario.actor,
        WorldPatchRequest.model_validate(
            {
                "operations": [
                    {
                        "op": "add_entity",
                        "client_id": "$temporary",
                        "components": [
                            {
                                "type": "IdentityComponent",
                                "fields": {"name": "Temporary", "kind": "item"},
                            }
                        ],
                    },
                    {
                        "op": "set_edge",
                        "source_id": str(scenario.room_a),
                        "target_id": "$temporary",
                        "edge": {
                            "type": "Contains",
                            "fields": {"mode": "room_content"},
                        },
                    },
                    {"op": "delete_entity", "entity_id": "$temporary"},
                ]
            }
        ),
    )

    assert len(response.deleted_entities) == 1
    assert response.changed_entities[0]["id"] == str(scenario.room_a)
    assert {entity.id for entity in scenario.actor.world.query().execute_entities()} == before_ids


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
                "components": [{"type": "IdentityComponent", "fields": {"name": "bad"}}],
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


def test_world_patch_preflight_prevents_partial_mutation(scenario):
    world = scenario.actor.world
    before_entities = len(list(world.query().execute_entities()))
    before_identity = world.get_entity(scenario.character).get_component(IdentityComponent)

    with pytest.raises(WorldPatchError, match="entity 'entity_999' does not exist"):
        apply_world_patch(
            scenario.actor,
            WorldPatchRequest.model_validate(
                {
                    "operations": [
                        {
                            "op": "add_entity",
                            "client_id": "$lantern",
                            "components": [
                                {
                                    "type": "IdentityComponent",
                                    "fields": {"name": "Lantern", "kind": "item"},
                                }
                            ],
                        },
                        {
                            "op": "set_component",
                            "entity_id": str(scenario.character),
                            "component": {
                                "type": "IdentityComponent",
                                "fields": {"name": "Hazel", "kind": "character"},
                            },
                        },
                        {
                            "op": "set_edge",
                            "source_id": "$lantern",
                            "target_id": "entity_999",
                            "edge": {"type": "Contains", "fields": {}},
                        },
                    ]
                }
            ),
        )

    identities = [
        entity.get_component(IdentityComponent).name
        for entity in world.query().with_all([IdentityComponent]).execute_entities()
    ]
    after_identity = world.get_entity(scenario.character).get_component(IdentityComponent)
    assert len(list(world.query().execute_entities())) == before_entities
    assert after_identity == before_identity
    assert "Lantern" not in identities


@pytest.mark.parametrize(
    ("operations", "message"),
    [
        (
            [
                {
                    "op": "add_entity",
                    "client_id": "$new",
                    "components": [
                        {
                            "type": "IdentityComponent",
                            "fields": {"name": "One", "kind": "item"},
                        },
                        {
                            "type": "IdentityComponent",
                            "fields": {"name": "Two", "kind": "item"},
                        },
                    ],
                }
            ],
            "duplicate component 'IdentityComponent'",
        ),
        (
            [
                {"op": "add_entity", "client_id": "$new"},
                {
                    "op": "add_component",
                    "entity_id": "$new",
                    "component": {
                        "type": "IdentityComponent",
                        "fields": {"name": "One", "kind": "item"},
                    },
                },
                {
                    "op": "add_component",
                    "entity_id": "$new",
                    "component": {
                        "type": "IdentityComponent",
                        "fields": {"name": "Two", "kind": "item"},
                    },
                },
            ],
            r"entity '\$new' already has component IdentityComponent",
        ),
        (
            [
                {"op": "add_entity", "client_id": "$new"},
                {
                    "op": "remove_component",
                    "entity_id": "$new",
                    "component_type": "IdentityComponent",
                },
            ],
            r"entity '\$new' does not have component IdentityComponent",
        ),
        (
            [
                {"op": "add_entity", "client_id": "$new"},
                {"op": "delete_entity", "entity_id": "$new"},
                {
                    "op": "set_component",
                    "entity_id": "$new",
                    "component": {
                        "type": "IdentityComponent",
                        "fields": {"name": "Gone", "kind": "item"},
                    },
                },
            ],
            r"entity '\$new' does not exist",
        ),
    ],
)
def test_world_patch_preflight_rejects_alias_component_errors_atomically(
    scenario, operations, message
):
    before_entities = len(list(scenario.actor.world.query().execute_entities()))

    with pytest.raises(WorldPatchError, match=message):
        apply_world_patch(
            scenario.actor,
            WorldPatchRequest.model_validate({"operations": operations}),
        )

    assert len(list(scenario.actor.world.query().execute_entities())) == before_entities


def test_world_patch_preflight_rejects_duplicate_existing_component_atomically(scenario):
    identity = scenario.actor.world.get_entity(scenario.character).get_component(IdentityComponent)

    with pytest.raises(WorldPatchError, match="already has component IdentityComponent"):
        apply_world_patch(
            scenario.actor,
            WorldPatchRequest.model_validate(
                {
                    "operations": [
                        {
                            "op": "add_component",
                            "entity_id": str(scenario.character),
                            "component": {
                                "type": "IdentityComponent",
                                "fields": {"name": "Hazel", "kind": "character"},
                            },
                        }
                    ]
                }
            ),
        )

    assert (
        scenario.actor.world.get_entity(scenario.character).get_component(IdentityComponent)
        == identity
    )


def test_world_patch_preflight_allows_pending_component_add_then_remove(scenario):
    response = apply_world_patch(
        scenario.actor,
        WorldPatchRequest.model_validate(
            {
                "operations": [
                    {
                        "op": "add_component",
                        "entity_id": str(scenario.character),
                        "component": {
                            "type": "SuspendedComponent",
                            "fields": {"reason": "editor"},
                        },
                    },
                    {
                        "op": "remove_component",
                        "entity_id": str(scenario.character),
                        "component_type": "SuspendedComponent",
                    },
                ]
            }
        ),
    )

    assert response.ok is True
    assert not scenario.actor.world.get_entity(scenario.character).has_component(SuspendedComponent)


def test_world_patch_rolls_back_earlier_operations_when_apply_fails(scenario):
    world = scenario.actor.world
    character = world.get_entity(scenario.character)
    original_identity = character.get_component(IdentityComponent)
    before_ids = {entity.id for entity in world.query().execute_entities()}
    world.register_prefab(
        "already-labeled",
        {IdentityComponent: IdentityComponent(name="default", kind="item")},
    )

    with pytest.raises(WorldPatchError, match="already has component IdentityComponent"):
        apply_world_patch(
            scenario.actor,
            WorldPatchRequest.model_validate(
                {
                    "operations": [
                        {
                            "op": "set_component",
                            "entity_id": str(scenario.character),
                            "component": {
                                "type": "IdentityComponent",
                                "fields": {"name": "Temporary", "kind": "character"},
                            },
                        },
                        {
                            "op": "add_entity",
                            "prefab": "already-labeled",
                            "components": [
                                {
                                    "type": "IdentityComponent",
                                    "fields": {"name": "Duplicate", "kind": "item"},
                                }
                            ],
                        },
                    ]
                }
            ),
        )

    assert character.get_component(IdentityComponent) == original_identity
    assert {entity.id for entity in world.query().execute_entities()} == before_ids


def test_world_patch_set_component_on_new_alias_entity(scenario):
    # set_component targeting a client alias exercises the alias branch of preflight
    # (alias_components.setdefault) and the apply path that has no existing fallback.
    response = apply_world_patch(
        scenario.actor,
        WorldPatchRequest.model_validate(
            {
                "operations": [
                    {"op": "add_entity", "client_id": "$thing"},
                    {
                        "op": "set_component",
                        "entity_id": "$thing",
                        "component": {
                            "type": "IdentityComponent",
                            "fields": {"name": "Sprig", "kind": "item"},
                        },
                    },
                ]
            }
        ),
    )

    assert response.ok is True
    entity_id = response.changed_entities[0]["id"]
    entity = scenario.actor.world.get_entity(parse_entity_id(entity_id))
    assert entity.get_component(IdentityComponent).name == "Sprig"


def test_world_patch_set_component_adds_new_type_to_existing_entity(scenario):
    # The character has no SuspendedComponent, so set_component takes the no-fallback path
    # (component_type registered but entity lacks it) and adds it fresh.
    response = apply_world_patch(
        scenario.actor,
        WorldPatchRequest.model_validate(
            {
                "operations": [
                    {
                        "op": "set_component",
                        "entity_id": str(scenario.character),
                        "component": {
                            "type": "SuspendedComponent",
                            "fields": {"reason": "editor"},
                        },
                    }
                ]
            }
        ),
    )

    assert response.ok is True
    assert (
        scenario.actor.world.get_entity(scenario.character).get_component(SuspendedComponent).reason
        == "editor"
    )


def test_world_patch_remove_component_from_new_alias_entity(scenario):
    # remove_component on a client alias that DID receive the component (via add_component)
    # exercises the alias-remove preflight branch (alias_components.remove).
    response = apply_world_patch(
        scenario.actor,
        WorldPatchRequest.model_validate(
            {
                "operations": [
                    {"op": "add_entity", "client_id": "$thing"},
                    {
                        "op": "add_component",
                        "entity_id": "$thing",
                        "component": {
                            "type": "IdentityComponent",
                            "fields": {"name": "Sprig", "kind": "item"},
                        },
                    },
                    {
                        "op": "remove_component",
                        "entity_id": "$thing",
                        "component_type": "IdentityComponent",
                    },
                ]
            }
        ),
    )

    assert response.ok is True
    entity_id = response.changed_entities[0]["id"]
    entity = scenario.actor.world.get_entity(parse_entity_id(entity_id))
    assert not entity.has_component(IdentityComponent)


def test_world_patch_remove_component_rejects_pending_missing_on_existing_entity(scenario):
    # The character lacks SuspendedComponent; removing it must fail in preflight via the
    # pending-component "does not have component" branch, leaving the world untouched.
    with pytest.raises(WorldPatchError, match="does not have component SuspendedComponent"):
        apply_world_patch(
            scenario.actor,
            WorldPatchRequest.model_validate(
                {
                    "operations": [
                        {
                            "op": "remove_component",
                            "entity_id": str(scenario.character),
                            "component_type": "SuspendedComponent",
                        }
                    ]
                }
            ),
        )


def test_world_patch_removes_existing_component_from_existing_entity(scenario):
    # The character genuinely has an IdentityComponent, so preflight takes the "entity already
    # has the component" branch (it is removable) and apply strips it.
    assert scenario.actor.world.get_entity(scenario.character).has_component(IdentityComponent)

    response = apply_world_patch(
        scenario.actor,
        WorldPatchRequest.model_validate(
            {
                "operations": [
                    {
                        "op": "remove_component",
                        "entity_id": str(scenario.character),
                        "component_type": "IdentityComponent",
                    }
                ]
            }
        ),
    )

    assert response.ok is True
    assert not scenario.actor.world.get_entity(scenario.character).has_component(IdentityComponent)


def test_world_patch_removes_existing_edge(scenario):
    # room_a has an ExitTo room_b from the scenario fixture; removing it passes the
    # valid-edge preflight branch and exercises _apply_remove_edge end to end.
    before = scenario.actor.world.get_entity(scenario.room_a).get_relationships(ExitTo)
    assert any(target == scenario.room_b for _edge, target in before)

    response = apply_world_patch(
        scenario.actor,
        WorldPatchRequest.model_validate(
            {
                "operations": [
                    {
                        "op": "remove_edge",
                        "source_id": str(scenario.room_a),
                        "target_id": str(scenario.room_b),
                        "edge_type": "ExitTo",
                    }
                ]
            }
        ),
    )

    assert response.ok is True
    after = scenario.actor.world.get_entity(scenario.room_a).get_relationships(ExitTo)
    assert not any(target == scenario.room_b for _edge, target in after)
    assert str(scenario.room_a) in {e["id"] for e in response.changed_entities}


def test_world_patch_delete_entity_marks_incoming_relationship_sources(scenario):
    # room_b holds an ExitTo back to room_a (the south exit). Deleting room_a must report
    # room_b as changed because its incoming relationship source list is walked.
    response = apply_world_patch(
        scenario.actor,
        WorldPatchRequest.model_validate(
            {"operations": [{"op": "delete_entity", "entity_id": str(scenario.room_a)}]}
        ),
    )

    assert response.ok is True
    assert str(scenario.room_a) in response.deleted_entities
    assert str(scenario.room_b) in {e["id"] for e in response.changed_entities}


async def test_worldgen_room_patch_expands_selected_door(scenario):
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

    generated = await generate_room_patch(
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


def test_worldgen_room_expansion_context_rejects_invalid_door_states(scenario):
    not_door = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="painted arch", kind="arch")],
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT),
        not_door.id,
    )
    with pytest.raises(WorldPatchError, match="is not a door"):
        collect_room_expansion_context(
            scenario.actor,
            WorldRoomGenerationRequest(door_entity_id=str(not_door.id), direction="east"),
        )

    orphan = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="north door", kind="door"), DoorComponent(open=False)],
    )
    with pytest.raises(WorldPatchError, match="door is not contained by a room"):
        collect_room_expansion_context(
            scenario.actor,
            WorldRoomGenerationRequest(door_entity_id=str(orphan.id)),
        )

    container = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="door rack", kind="container"), ContainerComponent()],
    )
    contained = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="south door", kind="door"), DoorComponent(open=False)],
    )
    container.add_relationship(Contains(mode=ContainmentMode.CONTAINER), contained.id)
    with pytest.raises(WorldPatchError, match="door container is not a room"):
        collect_room_expansion_context(
            scenario.actor,
            WorldRoomGenerationRequest(door_entity_id=str(contained.id)),
        )

    vague = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="sealed portal", kind="door"), DoorComponent(open=False)],
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT),
        vague.id,
    )
    with pytest.raises(WorldPatchError, match="direction is required"):
        collect_room_expansion_context(
            scenario.actor,
            WorldRoomGenerationRequest(door_entity_id=str(vague.id)),
        )


def test_worldgen_room_selection_uses_short_description_fallback(scenario):
    room = scenario.actor.world.get_entity(scenario.room_a)
    room.add_component(DescriptionComponent(short="short room"))

    context = collect_room_selection_context(
        scenario.actor,
        WorldCharacterGenerationRequest(room_entity_id=str(scenario.room_a)),
    )

    assert context.room.description == "short room"


def test_worldgen_room_selection_prefers_long_description(scenario):
    room = scenario.actor.world.get_entity(scenario.room_a)
    room.add_component(DescriptionComponent(short="short room", long="a long vivid room"))

    context = collect_room_selection_context(
        scenario.actor,
        WorldCharacterGenerationRequest(room_entity_id=str(scenario.room_a)),
    )

    # Long is present, so the short fallback is skipped (branch 194->196).
    assert context.room.description == "a long vivid room"


def test_worldgen_room_selection_rejects_non_room_entity(scenario):
    with pytest.raises(WorldPatchError, match="is not a room"):
        collect_room_selection_context(
            scenario.actor,
            WorldCharacterGenerationRequest(room_entity_id=str(scenario.character)),
        )


async def test_worldgen_character_patch_places_character_in_selected_room(scenario):
    generated = await generate_character_patch(
        scenario.actor,
        WorldCharacterGenerationRequest(
            room_entity_id=str(scenario.room_a),
            prompt="Mossy Sage",
        ),
    )
    response = apply_world_patch(scenario.actor, generated.patch)

    assert generated.generated_name == "Mossy Sage"
    room_contains = scenario.actor.world.get_entity(scenario.room_a).get_relationships(Contains)
    character_ids = [
        target
        for edge, target in room_contains
        if edge.mode == ContainmentMode.ROOM_CONTENT
        and scenario.actor.world.get_entity(target).has_component(CharacterComponent)
    ]
    assert response.ok is True
    assert len(character_ids) == 2


def test_worldgen_character_response_can_assign_llm_controller(scenario):
    generated = build_character_generation_response(
        collect_room_selection_context(
            scenario.actor,
            WorldCharacterGenerationRequest(room_entity_id=str(scenario.room_a)),
        ),
        CharacterProposal(
            name="Mossy Guide",
            controller="llm",
            llm_profile="guide",
            llm_model="local-model",
        ),
        epoch=scenario.actor.epoch,
    )

    controller_op = generated.patch.operations[2]
    assert controller_op.components[0].type == "LLMControllerComponent"
    assert controller_op.components[0].fields["profile_name"] == "guide"
    assert controller_op.components[0].fields["model"] == "local-model"


async def test_worldgen_item_patch_accepts_room_character_and_container_destinations(scenario):
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
        generated = await generate_item_patch(
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


def test_worldgen_item_context_rejects_non_container_destination(scenario):
    rock = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="flat rock", kind="item")],
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT),
        rock.id,
    )

    with pytest.raises(WorldPatchError, match="cannot contain generated items"):
        collect_container_selection_context(
            scenario.actor,
            WorldItemGenerationRequest(container_entity_id=str(rock.id)),
        )


def test_worldgen_room_response_can_generate_locked_hidden_doors(scenario):
    door = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="east door", kind="door"),
            DoorComponent(open=False),
            LockableComponent(locked=True),
        ],
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT),
        door.id,
    )
    context = collect_room_expansion_context(
        scenario.actor,
        WorldRoomGenerationRequest(door_entity_id=str(door.id), prompt="cellar"),
    )

    response = build_room_generation_response(
        context,
        room=RoomNodeProposal(title="Cellar"),
        contents=RoomContentsProposal(),
        doors=[DoorProposal(direction="south", locked=True, hidden=True)],
        epoch=scenario.actor.epoch,
    )

    generated_door = response.patch.operations[-2]
    assert generated_door.components[0].fields["name"] == "a hidden south door"
    assert generated_door.components[2].type == "LockableComponent"
    exit_edge = response.patch.operations[1].edge.fields
    assert exit_edge["locked"] is True


def test_worldgen_room_generation_response_includes_generated_characters(scenario):
    door = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="north door", kind="door"), DoorComponent(open=False)],
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT),
        door.id,
    )
    context = collect_room_expansion_context(
        scenario.actor,
        WorldRoomGenerationRequest(door_entity_id=str(door.id), prompt="north"),
    )

    proposal = CharacterProposal(name="Wandering Hare")
    response = build_room_generation_response(
        context,
        room=RoomNodeProposal(title="Glade"),
        contents=RoomContentsProposal(characters=[proposal]),
        doors=[DoorProposal(direction="north")],
        epoch=scenario.actor.epoch,
    )

    # The character loop assigns the generator key and emits operations (lines 474-475).
    assert proposal.key == "generated_character_0"
    character_ops = [
        op
        for op in response.patch.operations
        if op.op == "add_entity" and op.client_id == "$generated_character_0"
    ]
    assert len(character_ops) == 1


async def test_worldgen_event_patch_frames_story_event_as_ecs(scenario):
    generated = await generate_event_patch(
        scenario.actor,
        WorldEventGenerationRequest(
            room_entity_id=str(scenario.room_a),
            prompt="a bell rings",
        ),
    )
    response = apply_world_patch(scenario.actor, generated.patch)

    assert generated.generated_title == "a bell rings"
    assert response.ok is True
    room_contains = scenario.actor.world.get_entity(scenario.room_a).get_relationships(Contains)
    incidents = [
        scenario.actor.world.get_entity(target)
        for _edge, target in room_contains
        if scenario.actor.world.get_entity(target).has_component(IncidentComponent)
    ]
    assert incidents
    incident = incidents[0].get_component(IncidentComponent)
    assert incident.kind == "story_event"
    assert any(
        scenario.actor.world.get_entity(target).get_component(IdentityComponent).name
        == "a dropped clue"
        for _edge, target in room_contains
        if scenario.actor.world.get_entity(target).has_component(IdentityComponent)
    )


def test_worldgen_event_response_can_include_generated_characters(scenario):
    context = collect_room_selection_context(
        scenario.actor,
        WorldEventGenerationRequest(room_entity_id=str(scenario.room_a)),
    )

    response = build_event_generation_response(
        context,
        StoryEventProposal(
            title="Market Day",
            characters=[CharacterProposal(name="Visiting Merchant")],
        ),
        epoch=scenario.actor.epoch,
    )

    client_ids = [
        operation.client_id
        for operation in response.patch.operations
        if getattr(operation, "op", "") == "add_entity"
    ]
    assert "$generated_event_character_0" in client_ids
    assert "$generated_event_controller_0" in client_ids


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


def test_player_update_filter_preserves_visible_events_and_redacts_system_state(scenario):
    character_id = str(scenario.character)

    def message(visibility, **event):
        return {
            "type": "event",
            "data": {
                "event_type": "PluginEvent",
                "event": {
                    "event_id": visibility,
                    "world_epoch": 7,
                    "visibility": visibility,
                    **event,
                },
            },
        }

    public = message("public", payload="safe")
    room = message("room", room_id=str(scenario.room_a), payload="nearby")
    directed = message("directed", target_ids=[character_id], payload="for-player")
    private = message("private", actor_id=character_id, payload="own-private")
    hidden = message("private", actor_id="other", payload="must-not-leak")
    system = message("system", payload="admin-only")

    filtered = recent_player_updates(
        scenario.actor,
        character_id,
        [public, room, directed, private, hidden, system],
    )

    assert filtered[:4] == [public, room, directed, private]
    assert filtered[4] == {"type": "invalidate", "data": {"world_epoch": 7}}
    assert "admin-only" not in json.dumps(filtered)
    assert "must-not-leak" not in json.dumps(filtered)
    assert player_update_for_message(
        scenario.actor,
        character_id,
        {"type": "snapshot", "data": {"secret": "world"}},
    ) == {"type": "invalidate", "data": {"world_epoch": scenario.actor.epoch}}
    assert (
        player_update_for_message(
            scenario.actor,
            "ghost_9",
            room,
        )
        is None
    )
    assert (
        player_update_for_message(
            scenario.actor,
            character_id,
            {"type": "event", "data": None},
        )
        is None
    )
    assert (
        player_update_for_message(
            scenario.actor,
            character_id,
            {"type": "event", "data": {}},
        )
        is None
    )


async def test_player_update_reports_queue_overflow_as_resync(scenario):
    stream = EventStream(scenario.actor)
    subscription = stream.subscribe(max_queue_size=1)
    try:
        stream.broadcast({"type": "one", "data": {}})
        stream.broadcast({"type": "two", "data": {}})
        update = await next_player_update(
            scenario.actor,
            subscription,
            str(scenario.character),
        )
    finally:
        subscription.close()

    assert update == {
        "type": "resync",
        "data": {
            "world_epoch": scenario.actor.epoch,
            "reason": "queue_overflow",
            "resume_supported": False,
            "required_action": "fetch_character_projection",
        },
    }

    subscription = stream.subscribe(max_queue_size=1)
    try:
        waiting = asyncio.create_task(
            next_player_update(scenario.actor, subscription, str(scenario.character))
        )
        await asyncio.sleep(0)
        stream.broadcast({"type": "one", "data": {}})
        stream.broadcast({"type": "two", "data": {}})
        assert await waiting == {
            "type": "resync",
            "data": {
                "world_epoch": scenario.actor.epoch,
                "reason": "queue_overflow",
                "resume_supported": False,
                "required_action": "fetch_character_projection",
            },
        }
    finally:
        subscription.close()


async def test_player_update_skips_hidden_frames_until_visible_or_heartbeat(scenario, monkeypatch):
    stream = EventStream(scenario.actor)
    subscription = stream.subscribe(max_queue_size=2)
    hidden = {
        "type": "event",
        "data": {
            "event_type": "PrivateEvent",
            "event": {"visibility": "private", "actor_id": "other"},
        },
    }
    visible = {
        "type": "event",
        "data": {
            "event_type": "PublicEvent",
            "event": {"visibility": "public"},
        },
    }
    try:
        stream.broadcast(hidden)
        stream.broadcast(visible)
        assert (
            await next_player_update(
                scenario.actor,
                subscription,
                str(scenario.character),
            )
            == visible
        )
        monkeypatch.setattr(server_app, "WEBSOCKET_HEARTBEAT_SECONDS", 0.01)
        stream.broadcast(hidden)
        assert await next_player_update(
            scenario.actor,
            subscription,
            str(scenario.character),
        ) == {"type": "heartbeat", "data": {"world_epoch": scenario.actor.epoch}}
    finally:
        subscription.close()


async def test_character_updates_websocket_authenticates_before_ready(scenario):
    registry = ClaimSecretRegistry()
    claim = add_claim(
        scenario.actor.world.get_entity(scenario.controller),
        client_kind="web",
        client_id="client-a",
        character_id=str(scenario.character),
    )
    secret = registry.issue(claim.claim_id)
    app = create_app(scenario.actor, claim_secrets=registry)
    auth = {
        "type": "authenticate",
        "data": {"client_id": "client-a", "claim_secret": secret},
    }

    outputs = await _websocket_outputs(
        app,
        f"/v1/play/claims/{claim.claim_id}/stream",
        messages=[auth],
    )

    assert outputs[0]["type"] == "websocket.accept"
    ready = json.loads(outputs[1]["text"])
    assert {"type": ready["type"], "data": ready["data"]} == {
        "type": "ready",
        "data": {
            "character_id": str(scenario.character),
            "world_epoch": scenario.actor.epoch,
        },
    }
    assert ready["protocol_version"] == 1
    assert ready["projection_version"] == 1
    assert ready["stream_sequence"] == 1
    assert ready["world_id"]
    assert ready["event_id"] is None


@pytest.mark.parametrize(
    "auth",
    [
        {},
        {"type": "event", "data": {"claim_id": None, "claim_secret": None}},
        {"type": "authenticate", "data": {}},
        {"type": "authenticate", "data": {"claim_id": 1, "claim_secret": None}},
    ],
)
async def test_character_updates_websocket_rejects_malformed_auth(scenario, auth):
    registry = ClaimSecretRegistry()
    claim = add_claim(
        scenario.actor.world.get_entity(scenario.controller),
        client_kind="web",
        client_id="client-a",
        character_id=str(scenario.character),
    )
    registry.issue(claim.claim_id)
    app = create_app(scenario.actor, claim_secrets=registry)

    outputs = await _websocket_outputs(
        app,
        f"/v1/play/claims/{claim.claim_id}/stream",
        messages=[auth],
    )

    assert outputs == [
        {"type": "websocket.accept", "subprotocol": None, "headers": []},
        {"type": "websocket.close", "code": 1008, "reason": ""},
    ]


async def test_character_updates_websocket_times_out_before_sending_data(scenario, monkeypatch):
    monkeypatch.setattr(server_app, "PLAYER_WEBSOCKET_AUTH_SECONDS", 0.01)
    registry = ClaimSecretRegistry()
    claim = add_claim(
        scenario.actor.world.get_entity(scenario.controller),
        client_kind="web",
        client_id="client-a",
        character_id=str(scenario.character),
    )
    registry.issue(claim.claim_id)
    app = create_app(scenario.actor, claim_secrets=registry)

    outputs = await _websocket_outputs(
        app,
        f"/v1/play/claims/{claim.claim_id}/stream",
    )

    assert outputs == [
        {"type": "websocket.accept", "subprotocol": None, "headers": []},
        {"type": "websocket.close", "code": 1008, "reason": ""},
    ]


async def test_character_updates_websocket_rejects_wrong_secret_unknown_and_noncharacter(
    scenario,
):
    registry = ClaimSecretRegistry()
    controller = scenario.actor.world.get_entity(scenario.controller)
    claim = add_claim(
        controller,
        client_kind="web",
        client_id="client-a",
        character_id=str(scenario.character),
    )
    registry.issue(claim.claim_id)
    app = create_app(scenario.actor, claim_secrets=registry)
    wrong = {
        "type": "authenticate",
        "data": {"client_id": "client-a", "claim_secret": "wrong"},
    }

    for claim_id in (claim.claim_id, "missing"):
        outputs = await _websocket_outputs(
            app,
            f"/v1/play/claims/{claim_id}/stream",
            messages=[wrong],
        )
        assert outputs[-1]["type"] == "websocket.close"
        assert outputs[-1]["code"] == 1008

    remove_claim(controller, registry)
    nonnull_unclaimed = await _websocket_outputs(
        app,
        f"/v1/play/claims/{claim.claim_id}/stream",
        messages=[wrong],
    )
    assert nonnull_unclaimed[-1]["code"] == 1008


async def test_character_updates_websocket_revalidates_revoked_claim(scenario, monkeypatch):
    registry = ClaimSecretRegistry()
    controller = scenario.actor.world.get_entity(scenario.controller)
    claim = add_claim(
        controller,
        client_kind="web",
        client_id="client-a",
        character_id=str(scenario.character),
    )
    secret = registry.issue(claim.claim_id)
    app = create_app(scenario.actor, claim_secrets=registry)
    route = next(route for route in app.routes if route.path == "/v1/play/claims/{claim_id}/stream")
    monkeypatch.setattr(server_app, "WEBSOCKET_HEARTBEAT_SECONDS", 0.01)
    sent = []
    closed = []

    class FakeWebSocket:
        async def accept(self):
            return None

        async def receive_json(self):
            return {
                "type": "authenticate",
                "data": {"client_id": "client-a", "claim_secret": secret},
            }

        async def send_json(self, payload):
            sent.append(payload)
            remove_claim(controller, registry)

        async def close(self, code=1000):
            closed.append(code)

    await route.endpoint(FakeWebSocket(), claim.claim_id)

    assert sent[0]["type"] == "ready"
    assert closed == [1008]


async def test_character_updates_websocket_handles_revocation_before_ready_and_disconnect(
    scenario,
    monkeypatch,
):
    from fastapi import WebSocketDisconnect

    registry = ClaimSecretRegistry()
    controller = scenario.actor.world.get_entity(scenario.controller)
    claim = add_claim(
        controller,
        client_kind="web",
        client_id="client-a",
        character_id=str(scenario.character),
    )
    secret = registry.issue(claim.claim_id)
    app = create_app(scenario.actor, claim_secrets=registry)
    route = next(route for route in app.routes if route.path == "/v1/play/claims/{claim_id}/stream")
    closed = []

    class RevokedBeforeReady:
        async def accept(self):
            return None

        async def receive_json(self):
            remove_claim(controller, registry)
            return {
                "type": "authenticate",
                "data": {"client_id": "client-a", "claim_secret": secret},
            }

        async def close(self, code=1000):
            closed.append(code)

    await route.endpoint(RevokedBeforeReady(), claim.claim_id)
    assert closed == [1008]

    replacement = add_claim(
        controller,
        client_kind="web",
        client_id="client-a",
        character_id=str(scenario.character),
    )
    replacement_secret = registry.issue(replacement.claim_id)
    original_validate = registry.validate
    validation_calls = 0

    def revoke_after_auth(claim_id, supplied):
        nonlocal validation_calls
        validation_calls += 1
        return validation_calls == 1 and original_validate(claim_id, supplied)

    registry.validate = revoke_after_auth

    class RejectedBeforeReady:
        async def accept(self):
            return None

        async def receive_json(self):
            return {
                "type": "authenticate",
                "data": {
                    "client_id": "client-a",
                    "claim_secret": replacement_secret,
                },
            }

        async def close(self, code=1000):
            closed.append(code)

    await route.endpoint(RejectedBeforeReady(), replacement.claim_id)
    assert closed[-1] == 1008
    registry.validate = original_validate
    monkeypatch.setattr(server_app, "WEBSOCKET_HEARTBEAT_SECONDS", 0.01)

    class DisconnectOnReady:
        sent = 0

        async def accept(self):
            return None

        async def receive_json(self):
            return {
                "type": "authenticate",
                "data": {
                    "client_id": "client-a",
                    "claim_secret": replacement_secret,
                },
            }

        async def send_json(self, _payload):
            self.sent += 1
            if self.sent >= 3:
                raise WebSocketDisconnect(code=1006)

    await route.endpoint(DisconnectOnReady(), replacement.claim_id)


async def test_fastapi_world_updates_websocket_sends_initial_snapshot(scenario):
    app = create_app(scenario.actor, meta=WorldMeta(seed="moss"), with_admin=True)

    outputs = await _websocket_outputs(
        app,
        "/v1/admin/world/stream",
        headers=_ADMIN_HEADERS,
        messages=[
            {
                "type": "authenticate",
                "data": {"client_id": _ADMIN_HEADERS[CLIENT_ID_HEADER]},
            }
        ],
    )
    message = json.loads(outputs[1]["text"])

    assert message["type"] == "snapshot"
    assert message["data"]["metadata"]["seed"] == "moss"
    assert message["data"]["world_epoch"] == scenario.actor.epoch


async def test_fastapi_world_updates_websocket_requires_admin_scope(scenario):
    app = create_app(scenario.actor, meta=WorldMeta(seed="moss"), with_admin=True)

    auth_frame = [{"type": "authenticate", "data": {"client_id": "admin-a"}}]
    missing = await _websocket_outputs(app, "/v1/admin/world/stream", messages=auth_frame)
    assert missing[-1] == {"type": "websocket.close", "code": 1008, "reason": ""}

    # A token in the query string is no longer honored -- only the injected header is.
    query = await _websocket_outputs(
        app, "/v1/admin/world/stream?credential=secret", messages=auth_frame
    )
    assert query[-1] == {"type": "websocket.close", "code": 1008, "reason": ""}

    wrong = await _websocket_outputs(
        app,
        "/v1/admin/world/stream",
        headers={"Authorization": "Bearer invalid", CLIENT_ID_HEADER: "admin-a"},
        messages=auth_frame,
    )
    assert wrong[-1] == {"type": "websocket.close", "code": 1008, "reason": ""}

    missing_identity = await _websocket_outputs(
        app,
        "/v1/admin/world/stream",
        headers={"Authorization": _ADMIN_HEADERS["Authorization"]},
        messages=[{"type": "authenticate", "data": {}}],
    )
    assert missing_identity[-1] == {
        "type": "websocket.close",
        "code": 1008,
        "reason": "",
    }


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
