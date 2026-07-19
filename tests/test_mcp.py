from __future__ import annotations

import asyncio
import inspect
import json
import socket
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType, SimpleNamespace

import httpx
import pytest
from pydantic import AnyUrl

import bunnyland.mcp.server as mcp_server
from bunnyland.claims import ClaimSecretRegistry, add_claim
from bunnyland.cli import select_plugins
from bunnyland.core import (
    CharacterComponent,
    ClaimedComponent,
    ControlledBy,
    IdentityComponent,
    LLMControllerComponent,
    MCPControllerComponent,
    SuspendedComponent,
    WebControllerComponent,
    WorldActor,
    parse_entity_id,
    spawn_entity,
)
from bunnyland.core.events import ActorMovedEvent
from bunnyland.mcp import (
    EVENTS_RESOURCE_URI,
    assign_mcp_controller,
    create_bunnyland_mcp_app,
    mcp_controlled_character,
    mcp_enabled,
    release_mcp_claim,
    release_mcp_controller,
    render_mcp_client_prompt,
)
from bunnyland.persistence import WorldMeta
from bunnyland.plugins import (
    McpContribution,
    Plugin,
    RuntimeContribution,
    bunnyland_plugins,
    select,
)
from bunnyland.plugins.ids import MCP, WORLDGEN
from bunnyland.server.app import create_app
from bunnyland.server.auth import WORLD_ADMIN_SCOPE, WORLD_PLAY_SCOPE, TokenPrincipal, TokenStore
from bunnyland.server.client_ids import CLIENT_ID_HEADER
from bunnyland.server.models import (
    CharacterChatResponse,
    WorldCharacterGenerationResponse,
    WorldEventGenerationResponse,
    WorldGenerateResponse,
    WorldGenerationStatusResponse,
    WorldImageGenerationResponse,
    WorldItemGenerationResponse,
    WorldPatchRequest,
    WorldPatchResponse,
    WorldRoomGenerationResponse,
)
from bunnyland.simpacks.lifesim.mechanics import LifeStageComponent

_AUTHENTICATED_REQUEST = object()


def _authenticated_mcp_context():
    principal = TokenPrincipal(
        token_id="test-token",
        subject="test-admin",
        scopes=frozenset({WORLD_PLAY_SCOPE, WORLD_ADMIN_SCOPE}),
        created_at=1,
        rotate_after=None,
        expires_at=2**31,
        automatic_rotation=False,
        family_id="test-family",
    )
    return SimpleNamespace(
        session=object(),
        request_context=SimpleNamespace(
            request=SimpleNamespace(
                headers={},
                state=SimpleNamespace(auth_principal=principal),
            )
        ),
    )


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _tool_result(result) -> dict:
    if result.structuredContent is not None:
        return result.structuredContent
    return json.loads(result.content[0].text)


def _claim_args(claimed: dict) -> dict[str, str]:
    return {
        "claim_id": claimed["claim_id"],
        "claim_secret": claimed["claim_secret"],
    }


def test_select_plugins_can_add_mcp_without_disabling_defaults():
    selected = select_plugins(None, extra_enabled_ids=(MCP,))
    ids = {plugin.id for plugin in selected}

    assert MCP in ids
    assert WORLDGEN in ids


def test_mcp_plugin_is_not_enabled_by_default():
    assert mcp_enabled(bunnyland_plugins()) is True
    assert mcp_enabled(select(bunnyland_plugins(), None)) is False


def test_mcp_uri_and_character_summary_helpers_cover_edge_cases():
    actor = WorldActor()
    suspended = spawn_entity(
        actor.world,
        [
            IdentityComponent(name="Clover", kind="character"),
            CharacterComponent(species="bunny"),
            SuspendedComponent(reason="waiting"),
        ],
    )
    active = spawn_entity(
        actor.world,
        [
            IdentityComponent(name="Juniper", kind="character"),
            CharacterComponent(species="bunny"),
        ],
    )

    prompt_uri = mcp_server._client_prompt_uri("agent/a b")

    assert prompt_uri == "bunnyland://clients/agent%2Fa%20b/prompt"
    assert mcp_server._client_id_from_uri(prompt_uri, "/prompt") == "agent/a b"
    assert mcp_server._client_id_from_uri(prompt_uri, "/events") is None
    assert mcp_server._client_id_from_uri("bunnyland://rooms/1/prompt", "/prompt") is None
    assert mcp_server._active_controller_kind(actor, active) == "other"
    assert mcp_server._character_summary(actor, suspended)["controller_status"] == "suspended"
    assert {
        item["name"]: item["controller_status"] for item in mcp_server.list_mcp_characters(actor)
    } == {"Clover": "suspended", "Juniper": "other"}


def test_active_controller_kind_covers_controller_relationship_paths():
    actor = WorldActor()
    character = spawn_entity(
        actor.world,
        [
            IdentityComponent(name="Juniper", kind="character"),
            CharacterComponent(species="bunny"),
        ],
    )

    assert mcp_server._active_controller_kind(actor, character) == "other"

    actor.world._relationships.setdefault(character.id, {}).setdefault(ControlledBy, {})[
        parse_entity_id("entity_999")
    ] = ControlledBy(generation=0)

    assert mcp_server._active_controller_kind(actor, character) == "other"

    llm_controller = spawn_entity(
        actor.world,
        [
            LLMControllerComponent(
                profile_name="test",
                model="tiny",
            )
        ],
    )
    character.add_relationship(ControlledBy(generation=1), llm_controller.id)

    assert mcp_server._active_controller_kind(actor, character) == "other"

    mcp_controller = spawn_entity(
        actor.world,
        [MCPControllerComponent(client_id="client-a")],
    )
    character.add_relationship(ControlledBy(generation=2), mcp_controller.id)

    assert mcp_server._active_controller_kind(actor, character) == "MCP controller"


def test_mcp_match_and_controlled_character_helpers_cover_edge_cases():
    actor = WorldActor()
    non_character = spawn_entity(actor.world, [IdentityComponent(name="Rock", kind="prop")])
    child = spawn_entity(
        actor.world,
        [
            IdentityComponent(name="Clover", kind="character"),
            CharacterComponent(species="bunny"),
            LifeStageComponent(stage="child"),
            SuspendedComponent(reason="unclaimed"),
        ],
    )

    with pytest.raises(RuntimeError, match="no suspended claimable character"):
        mcp_server._match_character(
            actor,
            None,
            None,
            allow_child_claims=False,
        )
    with pytest.raises(RuntimeError, match="no character with id"):
        mcp_server._match_character(
            actor,
            None,
            str(non_character.id),
            allow_child_claims=True,
        )

    matched = mcp_server._match_character(
        actor,
        None,
        None,
        allow_child_claims=True,
    )
    assert matched.id == child.id
    assert mcp_server._is_child_character(non_character) is False
    assert mcp_server._mcp_controller_for(actor, "missing") is None
    assert mcp_controlled_character(actor, "missing") is None


def test_mcp_controlled_or_requested_character_validation():
    actor = WorldActor()
    character = spawn_entity(
        actor.world,
        [
            IdentityComponent(name="Juniper", kind="character"),
            CharacterComponent(species="bunny"),
            SuspendedComponent(reason="unclaimed"),
        ],
    )
    other = spawn_entity(
        actor.world,
        [
            IdentityComponent(name="Hazel", kind="character"),
            CharacterComponent(species="bunny"),
        ],
    )

    with pytest.raises(RuntimeError, match="client is not controlling"):
        mcp_server._controlled_or_requested_character(actor, None, "client-a", None)
    with pytest.raises(RuntimeError, match="client is not controlling"):
        mcp_server._controlled_or_requested_character(actor, None, "client-a", "entity_999")

    claimed = assign_mcp_controller(
        actor,
        client_id="client-a",
        character_name="Juniper",
    )

    with pytest.raises(RuntimeError, match="does not exist"):
        mcp_server._controlled_or_requested_character(
            actor,
            None,
            "client-a",
            "entity_999",
            **_claim_args(claimed),
        )

    assert (
        mcp_server._controlled_or_requested_character(
            actor,
            None,
            "client-a",
            None,
            **_claim_args(claimed),
        )[0]
        == character.id
    )
    assert (
        mcp_server._controlled_or_requested_character(
            actor,
            None,
            "client-a",
            str(character.id),
            **_claim_args(claimed),
        )[0]
        == character.id
    )
    with pytest.raises(RuntimeError, match="does not control the requested character"):
        mcp_server._controlled_or_requested_character(
            actor,
            None,
            "client-a",
            str(other.id),
            **_claim_args(claimed),
        )


async def test_mcp_event_bridge_unsubscribe_and_stale_session_cleanup(scenario):
    class Session:
        def __init__(self, *, fail: bool = False) -> None:
            self.fail = fail
            self.updated: list[str] = []

        async def send_resource_updated(self, uri: AnyUrl) -> None:
            if self.fail:
                raise RuntimeError("gone")
            self.updated.append(str(uri))

    bridge = mcp_server.MCPEventBridge(scenario.actor)
    session = Session()
    stale = Session(fail=True)
    bridge.unsubscribe(EVENTS_RESOURCE_URI, session)
    bridge.subscribe(EVENTS_RESOURCE_URI, session)
    bridge.unsubscribe(EVENTS_RESOURCE_URI, session)
    bridge.subscribe(EVENTS_RESOURCE_URI, stale)

    try:
        await bridge._notify_uri(EVENTS_RESOURCE_URI)

        assert stale.updated == []
        assert EVENTS_RESOURCE_URI not in bridge._subscriptions
    finally:
        bridge.close()


def test_assign_mcp_controller_claims_suspended_character():
    actor = WorldActor()
    character = spawn_entity(
        actor.world,
        [
            IdentityComponent(name="Juniper", kind="character"),
            CharacterComponent(species="bunny"),
            SuspendedComponent(reason="unclaimed"),
        ],
    )

    claimed = assign_mcp_controller(
        actor,
        client_id="client-a",
        claim_id="client-chosen-claim",
        character_name="Juniper",
    )

    assert claimed["character_name"] == "Juniper"
    assert claimed["claim_id"] != "client-chosen-claim"
    assert not character.has_component(SuspendedComponent)
    controller_id = character.get_relationships(ControlledBy)[0][1]
    controller = actor.world.get_entity(controller_id)
    mcp = controller.get_component(MCPControllerComponent)
    assert mcp.client_id == "client-a"
    assert mcp_controlled_character(actor, "client-a") == (character.id, controller_id, 0)


def test_assign_mcp_controller_moves_portable_claim_from_web_controller():
    actor = WorldActor()
    registry = ClaimSecretRegistry()
    character = spawn_entity(
        actor.world,
        [
            IdentityComponent(name="Juniper", kind="character"),
            CharacterComponent(species="bunny"),
        ],
    )
    web = spawn_entity(actor.world, [WebControllerComponent(client_id="client-a")])
    actor.assign_controller(character.id, web.id)
    claim = add_claim(
        web,
        client_kind="web",
        client_id="client-a",
        character_id=str(character.id),
        claim_id="server-issued-claim",
    )
    secret = registry.issue(claim.claim_id)

    moved = assign_mcp_controller(
        actor,
        claim_secrets=registry,
        client_id="client-a",
        claim_id="server-issued-claim",
        claim_secret=secret,
        character_name="Juniper",
    )

    controller = actor.world.get_entity(parse_entity_id(moved["controller_id"]))
    assert moved["claim_id"] == "server-issued-claim"
    assert controller.get_component(ClaimedComponent).client_kind == "mcp"
    assert not web.has_component(ClaimedComponent)


def test_assign_mcp_controller_skips_child_character_for_default_claim():
    actor = WorldActor()
    child = spawn_entity(
        actor.world,
        [
            IdentityComponent(name="Clover", kind="character"),
            CharacterComponent(species="bunny"),
            LifeStageComponent(stage="child"),
            SuspendedComponent(reason="unclaimed"),
        ],
    )
    adult = spawn_entity(
        actor.world,
        [
            IdentityComponent(name="Juniper", kind="character"),
            CharacterComponent(species="bunny"),
            LifeStageComponent(stage="adult"),
            SuspendedComponent(reason="unclaimed"),
        ],
    )

    claimed = assign_mcp_controller(actor, client_id="client-a")

    assert claimed["character_name"] == "Juniper"
    assert child.has_component(SuspendedComponent)
    assert not adult.has_component(SuspendedComponent)
    assert mcp_controlled_character(actor, "client-a")[0] == adult.id


def test_mcp_controller_claim_validation_errors_and_child_override():
    actor = WorldActor()
    child = spawn_entity(
        actor.world,
        [
            IdentityComponent(name="Clover", kind="character"),
            CharacterComponent(species="bunny"),
            LifeStageComponent(stage="child"),
            SuspendedComponent(reason="unclaimed"),
        ],
    )
    spawn_entity(
        actor.world,
        [
            IdentityComponent(name="Juniper", kind="character"),
            CharacterComponent(species="bunny"),
        ],
    )
    spawn_entity(
        actor.world,
        [
            IdentityComponent(name="June", kind="character"),
            CharacterComponent(species="bunny"),
        ],
    )

    with pytest.raises(RuntimeError, match="client_id is required"):
        assign_mcp_controller(actor, client_id=" ")

    with pytest.raises(RuntimeError, match="no character with id 'entity_999' exists"):
        assign_mcp_controller(actor, client_id="client-a", character_id="entity_999")

    with pytest.raises(RuntimeError, match="multiple characters match 'Jun'"):
        assign_mcp_controller(actor, client_id="client-a", character_name="Jun")

    with pytest.raises(RuntimeError, match="no character named 'Hazel' exists"):
        assign_mcp_controller(actor, client_id="client-a", character_name="Hazel")

    with pytest.raises(RuntimeError, match="child character"):
        assign_mcp_controller(actor, client_id="client-a", character_id=str(child.id))

    claimed = assign_mcp_controller(
        actor,
        client_id="client-a",
        character_id=str(child.id),
        allow_child_claims=True,
    )
    assert claimed["character_name"] == "Clover"


def test_mcp_release_validation_and_llm_fallback(monkeypatch):
    actor = WorldActor()
    character = spawn_entity(
        actor.world,
        [
            IdentityComponent(name="Juniper", kind="character"),
            CharacterComponent(species="bunny"),
            SuspendedComponent(reason="unclaimed"),
        ],
    )

    with pytest.raises(RuntimeError, match="client is not controlling a character yet"):
        release_mcp_controller(actor, client_id="client-a")

    claimed = assign_mcp_controller(
        actor,
        client_id="client-a",
        character_name="Juniper",
    )
    with pytest.raises(RuntimeError, match="character is already claimed"):
        assign_mcp_controller(
            actor,
            client_id="client-b",
            character_name="Juniper",
        )
    with pytest.raises(RuntimeError, match="invalid claim secret"):
        assign_mcp_controller(
            actor,
            client_id="client-a",
            character_name="Juniper",
            claim_id=claimed["claim_id"],
            claim_secret="wrong",
        )
    with pytest.raises(RuntimeError, match="invalid claim secret"):
        release_mcp_controller(
            actor,
            client_id="client-a",
            claim_id=claimed["claim_id"],
            claim_secret="wrong",
        )
    with pytest.raises(RuntimeError, match="invalid claim secret"):
        release_mcp_claim(
            actor,
            client_id="client-a",
            claim_id=claimed["claim_id"],
            claim_secret="wrong",
        )
    with pytest.raises(RuntimeError, match="invalid claim secret"):
        asyncio.run(
            render_mcp_client_prompt(
                actor,
                client_id="client-a",
                claim_id=claimed["claim_id"],
                claim_secret="wrong",
            )
        )

    unknown = spawn_entity(actor.world)
    with pytest.raises(RuntimeError, match="fallback_controller is not a controller"):
        release_mcp_controller(
            actor,
            client_id="client-a",
            fallback_controller=str(unknown.id),
            **_claim_args(claimed),
        )
    with pytest.raises(RuntimeError, match="fallback_controller is not a controller"):
        release_mcp_controller(
            actor,
            client_id="client-a",
            fallback_controller="manual",
            **_claim_args(claimed),
        )

    claimed = assign_mcp_controller(
        actor,
        client_id="client-a",
        character_name="Juniper",
        **_claim_args(claimed),
    )
    monkeypatch.setenv("BUNNYLAND_CHARACTER_MODEL", "env-model")
    released = release_mcp_controller(
        actor,
        client_id="client-a",
        fallback_controller="llm",
        provider="openrouter",
        **_claim_args(claimed),
    )
    controller_id = character.get_relationships(ControlledBy)[0][1]
    controller = actor.world.get_entity(controller_id)
    llm = controller.get_component(mcp_server.LLMControllerComponent)

    assert released["controller_kind"] == "llm"
    assert released["controller_id"] == str(controller_id)
    assert llm.model == "env-model"
    assert llm.provider == "openrouter"
    assert not character.has_component(SuspendedComponent)


def test_mcp_release_to_existing_controller_and_claim_release():
    actor = WorldActor()
    character = spawn_entity(
        actor.world,
        [
            IdentityComponent(name="Juniper", kind="character"),
            CharacterComponent(species="bunny"),
            SuspendedComponent(reason="unclaimed"),
        ],
    )
    existing = spawn_entity(
        actor.world,
        [LLMControllerComponent(profile_name="idle", model="claim-model")],
    )
    claimed = assign_mcp_controller(
        actor,
        client_id="client-a",
        character_name="Juniper",
    )
    character.add_component(SuspendedComponent(reason="manual"))

    released = release_mcp_controller(
        actor,
        client_id="client-a",
        fallback_controller=str(existing.id),
        **_claim_args(claimed),
    )
    default_prompt = asyncio.run(
        render_mcp_client_prompt(actor, client_id="client-a", **_claim_args(claimed))
    )
    from bunnyland.prompts.filters import PromptFilterRuntime

    actor.prompt_filter_runtime = PromptFilterRuntime.from_actor(actor)
    prompt = asyncio.run(
        render_mcp_client_prompt(actor, client_id="client-a", **_claim_args(claimed))
    )
    claim_released = release_mcp_claim(actor, client_id="client-a", **_claim_args(claimed))

    assert released["controller_id"] == str(existing.id)
    assert released["controller_kind"] == "llm"
    assert not character.has_component(SuspendedComponent)
    assert default_prompt["character_id"] == str(character.id)
    assert prompt["character_id"] == str(character.id)
    assert claim_released["claim_id"] == claimed["claim_id"]
    with pytest.raises(RuntimeError, match="client is not controlling a character yet"):
        release_mcp_controller(actor, client_id="client-a", **_claim_args(claimed))
    with pytest.raises(RuntimeError, match="client is not controlling a character yet"):
        release_mcp_claim(actor, client_id="client-a", **_claim_args(claimed))


def test_mcp_release_rejects_active_controller_missing_claim():
    actor = WorldActor()
    spawn_entity(
        actor.world,
        [
            IdentityComponent(name="Juniper", kind="character"),
            CharacterComponent(species="bunny"),
            SuspendedComponent(reason="unclaimed"),
        ],
    )
    claimed = assign_mcp_controller(actor, client_id="client-a", character_name="Juniper")
    controller = actor.world.get_entity(parse_entity_id(claimed["controller_id"]))
    controller.remove_component(ClaimedComponent)

    with pytest.raises(RuntimeError, match="client does not hold the claim"):
        release_mcp_controller(actor, client_id="client-a", **_claim_args(claimed))


def test_mcp_release_rejects_fallback_controller_claimed_by_another_client():
    actor = WorldActor()
    spawn_entity(
        actor.world,
        [
            IdentityComponent(name="Juniper", kind="character"),
            CharacterComponent(species="bunny"),
            SuspendedComponent(reason="unclaimed"),
        ],
    )
    spawn_entity(
        actor.world,
        [
            IdentityComponent(name="Hazel", kind="character"),
            CharacterComponent(species="bunny"),
            SuspendedComponent(reason="unclaimed"),
        ],
    )
    first = assign_mcp_controller(actor, client_id="client-a", character_name="Juniper")
    other = assign_mcp_controller(actor, client_id="client-b", character_name="Hazel")
    other_controller_id = parse_entity_id(other["controller_id"])

    with pytest.raises(RuntimeError, match="fallback controller is already claimed"):
        release_mcp_controller(
            actor,
            client_id="client-a",
            fallback_controller=str(other_controller_id),
            **_claim_args(first),
        )


def test_mcp_same_client_claims_second_character_with_new_controller():
    actor = WorldActor()
    spawn_entity(
        actor.world,
        [
            IdentityComponent(name="Juniper", kind="character"),
            CharacterComponent(species="bunny"),
            SuspendedComponent(reason="unclaimed"),
        ],
    )
    spawn_entity(
        actor.world,
        [
            IdentityComponent(name="Hazel", kind="character"),
            CharacterComponent(species="bunny"),
            SuspendedComponent(reason="unclaimed"),
        ],
    )

    first = assign_mcp_controller(actor, client_id="client-a", character_name="Juniper")
    second = assign_mcp_controller(actor, client_id="client-a", character_name="Hazel")

    assert first["controller_id"] != second["controller_id"]


def test_mcp_claim_skips_dangling_active_controller_edge(monkeypatch, scenario):
    original_has_entity = scenario.actor.world.has_entity

    def has_entity(entity_id):
        if entity_id == scenario.controller:
            return False
        return original_has_entity(entity_id)

    monkeypatch.setattr(scenario.actor.world, "has_entity", has_entity)

    claimed = assign_mcp_controller(
        scenario.actor,
        client_id="client-a",
        character_name="Juniper",
    )

    assert claimed["client_id"] == "client-a"


def test_mcp_release_to_existing_llm_keeps_active_character_active():
    actor = WorldActor()
    character = spawn_entity(
        actor.world,
        [
            IdentityComponent(name="Juniper", kind="character"),
            CharacterComponent(species="bunny"),
            SuspendedComponent(reason="unclaimed"),
        ],
    )
    existing = spawn_entity(
        actor.world,
        [LLMControllerComponent(profile_name="idle", model="claim-model")],
    )
    claimed = assign_mcp_controller(
        actor,
        client_id="client-a",
        character_name="Juniper",
    )

    released = release_mcp_controller(
        actor,
        client_id="client-a",
        fallback_controller=str(existing.id),
        **_claim_args(claimed),
    )

    assert released["controller_id"] == str(existing.id)
    assert not character.has_component(SuspendedComponent)


def test_mcp_prompt_errors(scenario):
    with pytest.raises(RuntimeError, match="client is not controlling a character yet"):
        asyncio.run(render_mcp_client_prompt(scenario.actor, client_id="client-a"))


async def test_mcp_event_bridge_filters_and_notifies_client_resources(scenario):
    class Session:
        def __init__(self, *, fail: bool = False) -> None:
            self.fail = fail
            self.updated: list[str] = []

        async def send_resource_updated(self, uri: AnyUrl) -> None:
            if self.fail:
                raise RuntimeError("gone")
            self.updated.append(str(uri))

    assign_mcp_controller(scenario.actor, client_id="client-a", character_name="Juniper")
    bridge = mcp_server.MCPEventBridge(scenario.actor)
    world_session = Session()
    client_session = Session()
    prompt_session = Session()
    stale_session = Session(fail=True)
    bridge.subscribe(EVENTS_RESOURCE_URI, world_session)
    bridge.subscribe(mcp_server._client_events_uri("client-a"), client_session)
    bridge.subscribe(mcp_server._client_prompt_uri("client-a"), prompt_session)
    bridge.subscribe(mcp_server._client_events_uri("missing"), stale_session)

    try:
        event = ActorMovedEvent(
            event_id="move",
            world_epoch=0,
            created_at=datetime.now(UTC),
            actor_id=str(scenario.character),
            from_room_id=str(scenario.room_a),
            to_room_id=str(scenario.room_b),
        )
        await bridge.record(event)

        assert bridge.recent_messages()
        assert bridge.recent_for_client("client-a")
        assert bridge.recent_for_client("missing") == []
        assert world_session.updated == [EVENTS_RESOURCE_URI]
        assert client_session.updated == [mcp_server._client_events_uri("client-a")]
        assert prompt_session.updated == [mcp_server._client_prompt_uri("client-a")]
        assert stale_session.updated == []
    finally:
        bridge.close()


def test_create_app_mounts_mcp_inside_existing_fastapi_app(monkeypatch, scenario, tmp_path):
    captured = {}
    registered_tools = {}
    registered_resources = {}
    registered_prompts = {}
    registered_low_server = {}

    class FakeLowServer:
        def __init__(self):
            self.get_capabilities = lambda _notifications, _experimental: SimpleNamespace(
                resources=SimpleNamespace(subscribe=False, listChanged=False)
            )

        def subscribe_resource(self):
            def decorate(func):
                registered_low_server["subscribe_resource"] = func
                return func

            return decorate

        def unsubscribe_resource(self):
            def decorate(func):
                registered_low_server["unsubscribe_resource"] = func
                return func

            return decorate

    class FakeFastMCP:
        def __init__(self, *args, **kwargs):
            captured["args"] = args
            captured["kwargs"] = kwargs
            self._mcp_server = FakeLowServer()

        def tool(self):
            def decorate(func):
                registered_tools[func.__name__] = func
                return func

            return decorate

        def resource(self, uri, **_kwargs):
            def decorate(func):
                registered_resources[uri] = func
                return func

            return decorate

        def prompt(self, *, name, **_kwargs):
            def decorate(func):
                registered_prompts[name] = func
                return func

            return decorate

        def get_context(self):
            return _authenticated_mcp_context()

        def streamable_http_app(self):
            async def asgi_app(scope, receive, send):
                del scope, receive, send

            return asgi_app

    mcp_module = ModuleType("mcp")
    server_module = ModuleType("mcp.server")
    fastmcp_module = ModuleType("mcp.server.fastmcp")
    exceptions_module = ModuleType("mcp.server.fastmcp.exceptions")
    fastmcp_module.FastMCP = FakeFastMCP
    exceptions_module.ToolError = RuntimeError
    monkeypatch.setitem(sys.modules, "mcp", mcp_module)
    monkeypatch.setitem(sys.modules, "mcp.server", server_module)
    monkeypatch.setitem(sys.modules, "mcp.server.fastmcp", fastmcp_module)
    monkeypatch.setitem(sys.modules, "mcp.server.fastmcp.exceptions", exceptions_module)

    # Pass an imagegen service so the player camera tool is wired into the MCP app too.
    from bunnyland.imagegen.config import ImageGenConfig
    from bunnyland.imagegen.media import MediaStore
    from bunnyland.imagegen.prompt import CatalogExampleSource, StubPromptEnhancer
    from bunnyland.imagegen.service import ImageGenService
    from bunnyland.imagegen.store import WorkflowTemplateStore, default_templates

    class _FakeComfy:
        async def generate(self, graph, *, output_node_id=""):
            return b"PNG"

    imagegen = ImageGenService(
        scenario.actor,
        ImageGenConfig(server_url="http://comfy.local"),
        client=_FakeComfy(),
        templates=WorkflowTemplateStore(defaults=default_templates()),
        enhancer=StubPromptEnhancer(),
        examples=CatalogExampleSource(),
        media=MediaStore(tmp_path),
    )

    app = create_app(
        scenario.actor,
        plugins=select(bunnyland_plugins(), [MCP, WORLDGEN]),
        imagegen=imagegen,
    )

    paths = {route.path for route in app.routes}
    assert "/v1/mcp" in paths
    assert "play_request_scene_image" in registered_tools
    assert captured["args"] == ("Bunnyland",)
    assert captured["kwargs"]["stateless_http"] is False
    assert captured["kwargs"]["json_response"] is True
    assert captured["kwargs"]["streamable_http_path"] == "/"
    assert "play_claim_character" in registered_tools
    assert "play_release_control" in registered_tools
    assert "play_send_command" in registered_tools
    assert "play_get_projection" in registered_tools
    assert "admin_patch_world" in registered_tools
    assert "bunnyland://v1/features" in registered_resources
    assert "bunnyland://v1/catalog" in registered_resources
    assert "bunnyland://v1/characters" in registered_resources
    assert registered_prompts["play_bunnyland"]().startswith("List and claim")
    claimed = asyncio.run(
        registered_tools["play_claim_character"](client_id="client-a", character_name="Juniper")
    )
    assert claimed["claim_id"]
    asyncio.run(registered_low_server["subscribe_resource"](AnyUrl(EVENTS_RESOURCE_URI)))
    assert registered_low_server["unsubscribe_resource"].__name__ == "unsubscribe_resource"
    asyncio.run(registered_low_server["unsubscribe_resource"](AnyUrl(EVENTS_RESOURCE_URI)))

    with pytest.raises(RuntimeError, match="client is not controlling"):
        registered_tools["play_get_projection"](client_id="missing")

    admin_patch_world = registered_tools["admin_patch_world"]
    assert list(inspect.signature(admin_patch_world).parameters) == ["operations"]
    patched = asyncio.run(admin_patch_world(operations=[]))
    assert patched["ok"] is True


async def test_mcp_registered_tools_return_expected_payloads(monkeypatch, scenario):
    registered_tools = {}
    registered_resources = {}
    calls = {}

    class FakeLowServer:
        def __init__(self):
            self.get_capabilities = lambda _notifications, _experimental: SimpleNamespace(
                resources=SimpleNamespace(subscribe=False, listChanged=False)
            )

        def subscribe_resource(self):
            def decorate(func):
                return func

            return decorate

        def unsubscribe_resource(self):
            def decorate(func):
                return func

            return decorate

    class FakeFastMCP:
        def __init__(self, *_args, **_kwargs):
            self._mcp_server = FakeLowServer()

        def tool(self):
            def decorate(func):
                registered_tools[func.__name__] = func
                return func

            return decorate

        def resource(self, uri, **_kwargs):
            def decorate(func):
                registered_resources[uri] = func
                return func

            return decorate

        def prompt(self, *_args, **_kwargs):
            def decorate(func):
                return func

            return decorate

        def get_context(self):
            return _authenticated_mcp_context()

        def streamable_http_app(self):
            return SimpleNamespace()

    mcp_module = ModuleType("mcp")
    server_module = ModuleType("mcp.server")
    fastmcp_module = ModuleType("mcp.server.fastmcp")
    exceptions_module = ModuleType("mcp.server.fastmcp.exceptions")
    fastmcp_module.FastMCP = FakeFastMCP
    exceptions_module.ToolError = RuntimeError
    monkeypatch.setitem(sys.modules, "mcp", mcp_module)
    monkeypatch.setitem(sys.modules, "mcp.server", server_module)
    monkeypatch.setitem(sys.modules, "mcp.server.fastmcp", fastmcp_module)
    monkeypatch.setitem(sys.modules, "mcp.server.fastmcp.exceptions", exceptions_module)

    async def patch_world(request):
        calls["patch_world"] = request
        return WorldPatchResponse(world_epoch=scenario.actor.epoch)

    async def generate_world(request):
        calls["generate_world"] = request
        return WorldGenerateResponse(
            job_id="job-1",
            status="running",
            seed=request.seed or "",
            generator=request.generator or "",
            world_epoch=scenario.actor.epoch,
        )

    async def generation_status():
        return WorldGenerationStatusResponse(world_epoch=scenario.actor.epoch)

    async def generate_room(request):
        calls["generate_room"] = request
        return WorldRoomGenerationResponse(
            source_room_id=str(scenario.room_a),
            door_entity_id=request.door_entity_id,
            generated_title="Generated Room",
            patch=WorldPatchRequest(),
        )

    async def generate_character(request):
        calls["generate_character"] = request
        return WorldCharacterGenerationResponse(
            room_entity_id=request.room_entity_id,
            generated_name="Generated Character",
            patch=WorldPatchRequest(),
        )

    async def generate_item(request):
        calls["generate_item"] = request
        return WorldItemGenerationResponse(
            container_entity_id=request.container_entity_id,
            generated_name="Generated Item",
            patch=WorldPatchRequest(),
        )

    async def generate_event(request):
        calls["generate_event"] = request
        return WorldEventGenerationResponse(
            room_entity_id=request.room_entity_id,
            generated_title="Generated Event",
            generated_kind="scene",
            patch=WorldPatchRequest(),
        )

    async def generate_image(request):
        calls["generate_image"] = request
        return WorldImageGenerationResponse(
            world_epoch=scenario.actor.epoch,
            job_id="img-1",
            status="queued",
            entity_id=request.entity_id,
            purpose=request.purpose,
        )

    create_kwargs = dict(
        actor=scenario.actor,
        meta=WorldMeta(seed="moss"),
        loop=SimpleNamespace(running=True, paused=False),
        patch_world=patch_world,
        generate_world=generate_world,
        generation_status=generation_status,
        generate_room=generate_room,
        generate_character=generate_character,
        generate_item=generate_item,
        generate_event=generate_event,
    )
    create_bunnyland_mcp_app(generate_image=generate_image, **create_kwargs)

    assert json.loads(registered_resources["bunnyland://v1/admin/controller-definitions"]()) == {
        "scripts": [],
        "behaviors": [],
    }
    assert registered_tools["admin_list_generators"]() == {"generators": []}
    with pytest.raises(RuntimeError, match="assignment is not configured"):
        await registered_tools["admin_assign_controller"](
            character_id=str(scenario.character), controller_id=str(scenario.controller)
        )
    with pytest.raises(RuntimeError, match="chat is not configured"):
        await registered_tools["play_chat"](client_id="client-a", message="hello")

    characters = registered_tools["play_list_characters"]()
    assert characters["ok"] is True
    assert [character["name"] for character in characters["characters"]] == ["Juniper"]

    snapshot = registered_tools["admin_world_snapshot"]()
    assert snapshot["metadata"]["seed"] == "moss"
    assert any(entity["id"] == str(scenario.character) for entity in snapshot["entities"])

    assert "admin_save_world" in registered_tools

    status = registered_tools["admin_runtime_status"]()
    assert status == {
        "ok": True,
        "world_epoch": scenario.actor.epoch,
        "running": True,
        "paused": False,
        "tick_seconds": None,
        "time_scale": None,
        "game_seconds_per_tick": None,
    }

    claimed = await registered_tools["play_claim_character"](
        client_id="client-a",
        character_name="Juniper",
    )
    assert claimed["character_id"] == str(scenario.character)

    projection = registered_tools["play_get_projection"](
        client_id="client-a", **_claim_args(claimed)
    )
    assert projection["character_id"] == str(scenario.character)
    assert projection["character_name"] == "Juniper"

    released = await registered_tools["play_release_control"](
        client_id="client-a",
        **_claim_args(claimed),
    )
    assert released["controller_kind"] == "suspended"

    patched = await registered_tools["admin_patch_world"](operations=[])
    assert patched["world_epoch"] == scenario.actor.epoch
    assert calls["patch_world"].operations == []

    generated_world = await registered_tools["admin_generate_world"](
        seed="seed-a",
        generator="stub",
        max_rooms=2,
        confirm_reset=True,
        save=True,
    )
    assert generated_world["job_id"] == "job-1"
    assert calls["generate_world"].seed == "seed-a"
    assert calls["generate_world"].max_rooms == 2
    assert calls["generate_world"].confirm_reset is True

    generation = await registered_tools["admin_generation_status"]()
    assert generation["world_epoch"] == scenario.actor.epoch

    room = await registered_tools["admin_generate_room"](
        door_entity_id="door-1",
        direction="north",
        prompt="room prompt",
    )
    assert room["generated_title"] == "Generated Room"
    assert calls["generate_room"].direction == "north"

    character = await registered_tools["admin_generate_character"](
        room_entity_id=str(scenario.room_a),
        prompt="character prompt",
    )
    assert character["generated_name"] == "Generated Character"
    assert calls["generate_character"].prompt == "character prompt"

    item = await registered_tools["admin_generate_item"](
        container_entity_id=str(scenario.room_a),
        prompt="item prompt",
    )
    assert item["generated_name"] == "Generated Item"
    assert calls["generate_item"].container_entity_id == str(scenario.room_a)

    event = await registered_tools["admin_generate_event"](
        room_entity_id=str(scenario.room_a),
        prompt="event prompt",
    )
    assert event["generated_kind"] == "scene"
    assert calls["generate_event"].prompt == "event prompt"

    assert list(inspect.signature(registered_tools["admin_generate_image"]).parameters) == [
        "entity_id",
        "purpose",
        "template",
        "extra",
        "alpha",
        "force",
    ]
    image = await registered_tools["admin_generate_image"](
        entity_id=str(scenario.character), purpose="portrait"
    )
    assert image["job_id"] == "img-1"
    assert calls["generate_image"].entity_id == str(scenario.character)

    # Re-create without an image callback: the tool reports it is not configured.
    create_bunnyland_mcp_app(**create_kwargs)
    with pytest.raises(RuntimeError, match="not configured"):
        await registered_tools["admin_generate_image"](entity_id=str(scenario.character))

    # Player-facing scene-image request (camera affordance, no admin scope required).
    claimed = await registered_tools["play_claim_character"](
        client_id="client-a",
        character_name="Juniper",
        **_claim_args(claimed),
    )

    async def scene_image(character_id):
        calls["scene_image"] = character_id
        return WorldImageGenerationResponse(
            world_epoch=scenario.actor.epoch,
            job_id="scene-1",
            status="queued",
            entity_id=character_id,
            purpose="event",
        )

    create_bunnyland_mcp_app(scene_image=scene_image, **create_kwargs)
    scene = await registered_tools["play_request_scene_image"](
        client_id="client-a",
        **_claim_args(claimed),
    )
    assert scene["job_id"] == "scene-1"
    assert calls["scene_image"] == str(scenario.character)

    with pytest.raises(RuntimeError, match="not controlling"):
        await registered_tools["play_request_scene_image"](client_id="ghost")

    # The character has no room to illustrate: the callback returns None.
    async def scene_image_none(_character_id):
        return None

    create_bunnyland_mcp_app(scene_image=scene_image_none, **create_kwargs)
    with pytest.raises(RuntimeError, match="no room"):
        await registered_tools["play_request_scene_image"](
            client_id="client-a",
            **_claim_args(claimed),
        )

    # Without the callback the tool reports image generation is off.
    create_bunnyland_mcp_app(**create_kwargs)
    with pytest.raises(RuntimeError, match="not configured"):
        await registered_tools["play_request_scene_image"](
            client_id="client-a",
            **_claim_args(claimed),
        )


async def test_mcp_registered_tools_wrap_runtime_errors(monkeypatch, scenario):
    registered_tools = {}

    class FakeToolError(RuntimeError):
        pass

    class FakeLowServer:
        def __init__(self):
            self.get_capabilities = lambda _notifications, _experimental: SimpleNamespace(
                resources=SimpleNamespace(subscribe=False, listChanged=False)
            )

        def subscribe_resource(self):
            def decorate(func):
                return func

            return decorate

        def unsubscribe_resource(self):
            def decorate(func):
                return func

            return decorate

    class FakeFastMCP:
        def __init__(self, *_args, **_kwargs):
            self._mcp_server = FakeLowServer()

        def tool(self):
            def decorate(func):
                registered_tools[func.__name__] = func
                return func

            return decorate

        def resource(self, _uri, **_kwargs):
            def decorate(func):
                return func

            return decorate

        def get_context(self):
            return _authenticated_mcp_context()

        def streamable_http_app(self):
            return SimpleNamespace()

    mcp_module = ModuleType("mcp")
    server_module = ModuleType("mcp.server")
    fastmcp_module = ModuleType("mcp.server.fastmcp")
    exceptions_module = ModuleType("mcp.server.fastmcp.exceptions")
    fastmcp_module.FastMCP = FakeFastMCP
    exceptions_module.ToolError = FakeToolError
    monkeypatch.setitem(sys.modules, "mcp", mcp_module)
    monkeypatch.setitem(sys.modules, "mcp.server", server_module)
    monkeypatch.setitem(sys.modules, "mcp.server.fastmcp", fastmcp_module)
    monkeypatch.setitem(sys.modules, "mcp.server.fastmcp.exceptions", exceptions_module)

    async def patch_world(_request):
        raise AssertionError("patch_world should not be called")

    async def generate_world(_request):
        raise AssertionError("generate_world should not be called")

    async def generation_status():
        raise AssertionError("generation_status should not be called")

    async def generate_room(_request):
        raise AssertionError("generate_room should not be called")

    create_bunnyland_mcp_app(
        actor=scenario.actor,
        meta=WorldMeta(seed="moss"),
        loop=None,
        patch_world=patch_world,
        generate_world=generate_world,
        generation_status=generation_status,
        generate_room=generate_room,
        generate_character=generate_room,
        generate_item=generate_room,
        generate_event=generate_room,
    )

    with pytest.raises(FakeToolError, match="client is not controlling") as projection_error:
        registered_tools["play_get_projection"](client_id="missing")
    assert isinstance(projection_error.value.__cause__, RuntimeError)

    with pytest.raises(FakeToolError, match="client_id is required") as claim_error:
        await registered_tools["play_claim_character"](client_id=" ")
    assert isinstance(claim_error.value.__cause__, RuntimeError)

    with pytest.raises(FakeToolError, match="client is not controlling") as release_error:
        await registered_tools["play_release_control"](client_id="missing")
    assert isinstance(release_error.value.__cause__, RuntimeError)

    with pytest.raises(FakeToolError, match="client is not controlling") as claim_release_error:
        await registered_tools["play_release_claim"](client_id="missing")
    assert isinstance(claim_release_error.value.__cause__, RuntimeError)

    with pytest.raises(FakeToolError, match="client is not controlling") as command_error:
        await registered_tools["play_send_command"](
            client_id="missing",
            command_type="move",
        )
    assert isinstance(command_error.value.__cause__, RuntimeError)

    claimed = await registered_tools["play_claim_character"](
        client_id="client-a",
        character_name="Juniper",
    )
    with pytest.raises(FakeToolError, match="'not-a-lane' is not a valid Lane") as lane_error:
        await registered_tools["play_send_command"](
            client_id="client-a",
            command_type="move",
            lane="not-a-lane",
            **_claim_args(claimed),
        )
    assert isinstance(lane_error.value.__cause__, ValueError)


def test_mcp_release_to_llm_clears_resuspended_character(monkeypatch):
    actor = WorldActor()
    character = spawn_entity(
        actor.world,
        [
            IdentityComponent(name="Juniper", kind="character"),
            CharacterComponent(species="bunny"),
            SuspendedComponent(reason="unclaimed"),
        ],
    )
    claimed = assign_mcp_controller(actor, client_id="client-a", character_name="Juniper")
    # Claiming clears suspension; re-add it so the LLM release path removes it (line 425).
    character.add_component(SuspendedComponent(reason="napping"))

    released = release_mcp_controller(
        actor,
        client_id="client-a",
        fallback_controller="llm",
        **_claim_args(claimed),
    )

    assert released["controller_kind"] == "llm"
    assert not character.has_component(SuspendedComponent)


async def test_mcp_event_bridge_skips_events_from_other_actors(scenario):
    other = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="Hazel", kind="character"), CharacterComponent()],
    )
    assign_mcp_controller(scenario.actor, client_id="client-a", character_name="Juniper")
    bridge = mcp_server.MCPEventBridge(scenario.actor)
    try:
        # An event by another actor must be skipped (190->188 continue path).
        await bridge.record(
            ActorMovedEvent(
                event_id="other-move",
                world_epoch=0,
                created_at=datetime.now(UTC),
                actor_id=str(other.id),
                from_room_id=str(scenario.room_a),
                to_room_id=str(scenario.room_b),
            )
        )
        await bridge.record(
            ActorMovedEvent(
                event_id="own-move",
                world_epoch=0,
                created_at=datetime.now(UTC),
                actor_id=str(scenario.character),
                from_room_id=str(scenario.room_a),
                to_room_id=str(scenario.room_b),
            )
        )

        client_events = bridge.recent_for_client("client-a")
        assert len(client_events) == 1
        assert client_events[0]["data"]["event"]["event_id"] == "own-move"
    finally:
        bridge.close()


def test_mcp_event_bridge_unsubscribe_keeps_uri_with_remaining_sessions(scenario):
    bridge = mcp_server.MCPEventBridge(scenario.actor)
    try:
        first = object()
        second = object()
        bridge.subscribe(EVENTS_RESOURCE_URI, first)
        bridge.subscribe(EVENTS_RESOURCE_URI, second)

        # Removing one session leaves the other, so the uri is not popped (243->exit).
        bridge.unsubscribe(EVENTS_RESOURCE_URI, first)
        assert EVENTS_RESOURCE_URI in bridge._subscriptions

        # Unsubscribing an unknown uri is a no-op.
        bridge.unsubscribe("bunnyland://clients/none/events", first)
    finally:
        bridge.close()


def _install_fake_fastmcp(monkeypatch, *, registered_tools, low_server, get_context=None):
    class FakeFastMCP:
        def __init__(self, *_args, **_kwargs):
            self._mcp_server = low_server

        def tool(self):
            def decorate(func):
                registered_tools[func.__name__] = func
                return func

            return decorate

        def resource(self, _uri, **_kwargs):
            def decorate(func):
                return func

            return decorate

        def prompt(self, *_args, **_kwargs):
            def decorate(func):
                return func

            return decorate

        def get_context(self):
            return _authenticated_mcp_context() if get_context is None else get_context()

        def streamable_http_app(self):
            return SimpleNamespace()

    mcp_module = ModuleType("mcp")
    server_module = ModuleType("mcp.server")
    fastmcp_module = ModuleType("mcp.server.fastmcp")
    exceptions_module = ModuleType("mcp.server.fastmcp.exceptions")
    fastmcp_module.FastMCP = FakeFastMCP
    exceptions_module.ToolError = RuntimeError
    monkeypatch.setitem(sys.modules, "mcp", mcp_module)
    monkeypatch.setitem(sys.modules, "mcp.server", server_module)
    monkeypatch.setitem(sys.modules, "mcp.server.fastmcp", fastmcp_module)
    monkeypatch.setitem(sys.modules, "mcp.server.fastmcp.exceptions", exceptions_module)


def test_mcp_addon_capability_requires_explicit_policy(monkeypatch, scenario):
    registered_tools = {}

    class FakeLowServer:
        def __init__(self):
            self.get_capabilities = lambda _n, _e: SimpleNamespace(resources=None)

        def subscribe_resource(self):
            return lambda func: func

        def unsubscribe_resource(self):
            return lambda func: func

    _install_fake_fastmcp(
        monkeypatch,
        registered_tools=registered_tools,
        low_server=FakeLowServer(),
    )

    def missing_policy(registrar, _actor, **_context):
        @registrar.tool()
        def unsafe_tool():
            return {"ok": True}

    plugin = Plugin(
        id="test.unsafe-mcp",
        name="Unsafe MCP",
        runtime=RuntimeContribution(
            mcp=(McpContribution(registrars=(missing_policy,)),),
        ),
    )

    async def unused(_request=None):
        raise AssertionError("unused")

    with pytest.raises(TypeError, match="scopes"):
        create_bunnyland_mcp_app(
            actor=scenario.actor,
            meta=WorldMeta(seed="moss"),
            loop=None,
            patch_world=unused,
            generate_world=unused,
            generation_status=unused,
            generate_room=unused,
            generate_character=unused,
            generate_item=unused,
            generate_event=unused,
            plugins=(plugin,),
        )


@pytest.mark.parametrize("scopes", [(), ("world:unknown",)])
def test_mcp_addon_capability_rejects_empty_or_unknown_policy(monkeypatch, scenario, scopes):
    registered_tools = {}

    class FakeLowServer:
        def __init__(self):
            self.get_capabilities = lambda _n, _e: SimpleNamespace(resources=None)

        def subscribe_resource(self):
            return lambda func: func

        def unsubscribe_resource(self):
            return lambda func: func

    _install_fake_fastmcp(
        monkeypatch,
        registered_tools=registered_tools,
        low_server=FakeLowServer(),
    )

    def invalid_policy(registrar, _actor, **_context):
        @registrar.tool(scopes=scopes)
        def unsafe_tool():
            return {"ok": True}

    plugin = Plugin(
        id="test.invalid-mcp-policy",
        name="Invalid MCP Policy",
        runtime=RuntimeContribution(
            mcp=(McpContribution(registrars=(invalid_policy,)),),
        ),
    )

    async def unused(_request=None):
        raise AssertionError("unused")

    with pytest.raises(ValueError, match="explicit play/admin access policy"):
        create_bunnyland_mcp_app(
            actor=scenario.actor,
            meta=WorldMeta(seed="moss"),
            loop=None,
            patch_world=unused,
            generate_world=unused,
            generation_status=unused,
            generate_room=unused,
            generate_character=unused,
            generate_item=unused,
            generate_event=unused,
            plugins=(plugin,),
        )


def test_mcp_addon_declares_tool_resource_and_prompt_policies(monkeypatch, scenario):
    registered_tools = {}

    class FakeLowServer:
        def __init__(self):
            self.get_capabilities = lambda _n, _e: SimpleNamespace(resources=None)

        def subscribe_resource(self):
            return lambda func: func

        def unsubscribe_resource(self):
            return lambda func: func

    _install_fake_fastmcp(
        monkeypatch,
        registered_tools=registered_tools,
        low_server=FakeLowServer(),
    )

    def declared_policies(registrar, _actor, **_context):
        @registrar.tool(scopes=(WORLD_PLAY_SCOPE,))
        def safe_tool():
            return {"ok": True}

        @registrar.resource("test://resource", scopes=(WORLD_PLAY_SCOPE,), name="safe_resource")
        def safe_resource():
            return {"ok": True}

        @registrar.resource("test://unnamed", scopes=(WORLD_PLAY_SCOPE,))
        def unnamed_resource():
            return {"ok": True}

        @registrar.prompt(scopes=(WORLD_ADMIN_SCOPE,), name="safe_prompt")
        def safe_prompt():
            return "safe"

        @registrar.prompt(scopes=(WORLD_ADMIN_SCOPE,))
        def unnamed_prompt():
            return "safe"

    plugin = Plugin(
        id="test.declared-mcp-policy",
        name="Declared MCP Policy",
        runtime=RuntimeContribution(
            mcp=(
                McpContribution(registrars=()),
                McpContribution(registrars=(declared_policies,)),
            ),
        ),
    )

    async def unused(_request=None):
        raise AssertionError("unused")

    app = create_bunnyland_mcp_app(
        actor=scenario.actor,
        meta=WorldMeta(seed="moss"),
        loop=None,
        patch_world=unused,
        generate_world=unused,
        generation_status=unused,
        generate_room=unused,
        generate_character=unused,
        generate_item=unused,
        generate_event=unused,
        plugins=(plugin,),
    )
    assert "test_declared_mcp_policy__safe_tool" in registered_tools
    app.bunnyland_mcp_event_bridge.close()


async def test_mcp_admin_tools_wrap_generator_failures_and_definition_tools(monkeypatch, scenario):
    from bunnyland.server.models import ControllerDefinitionListResponse

    registered_tools = {}

    class FakeLowServer:
        def __init__(self):
            # resources is None so the capabilities patch takes the 575->578 skip branch.
            self.get_capabilities = lambda _n, _e: SimpleNamespace(resources=None)

        def subscribe_resource(self):
            return lambda func: func

        def unsubscribe_resource(self):
            return lambda func: func

    low_server = FakeLowServer()
    _install_fake_fastmcp(monkeypatch, registered_tools=registered_tools, low_server=low_server)

    async def boom(_request):
        raise ValueError("generator unavailable")

    async def boom_status():
        raise ValueError("status unavailable")

    register_calls = {}

    async def register_script(spec):
        register_calls["script"] = spec
        return ControllerDefinitionListResponse(scripts=[spec.name])

    async def register_behavior(spec):
        register_calls["behavior"] = spec
        return ControllerDefinitionListResponse(behaviors=[spec.name])

    def list_controller_definitions():
        return ControllerDefinitionListResponse(scripts=["existing"])

    create_bunnyland_mcp_app(
        actor=scenario.actor,
        meta=WorldMeta(seed="moss"),
        loop=None,
        patch_world=boom,
        generate_world=boom,
        generation_status=boom_status,
        generate_room=boom,
        generate_character=boom,
        generate_item=boom,
        generate_event=boom,
        generate_image=boom,
        register_script=register_script,
        register_behavior=register_behavior,
        list_controller_definitions=list_controller_definitions,
    )

    # Calling get_capabilities exercises the resources-is-None skip branch (575->578).
    assert low_server.get_capabilities(None, None).resources is None

    # Each admin generator wraps its underlying ValueError in a ToolError.
    for tool_name, kwargs in [
        ("admin_patch_world", {"operations": []}),
        ("admin_generate_world", {}),
        ("admin_generate_room", {"door_entity_id": "door-1"}),
        ("admin_generate_character", {"room_entity_id": str(scenario.room_a)}),
        ("admin_generate_item", {"container_entity_id": str(scenario.room_a)}),
        ("admin_generate_event", {"room_entity_id": str(scenario.room_a)}),
        ("admin_generate_image", {"entity_id": str(scenario.character)}),
    ]:
        with pytest.raises(RuntimeError, match="generator unavailable"):
            await registered_tools[tool_name](**kwargs)

    # Controller-definition tools succeed and a registration failure wraps as ToolError.
    listed = registered_tools["admin_list_controller_definitions"]()
    assert listed["scripts"] == ["existing"]

    script = await registered_tools["admin_register_script"](
        name="patrol",
        calls=[{"name": "wait", "arguments": {}}],
    )
    assert script["scripts"] == ["patrol"]

    behavior = await registered_tools["admin_register_behavior"](
        name="guard",
        root={"kind": "action", "ref": "wait"},
    )
    assert behavior["behaviors"] == ["guard"]

    with pytest.raises(RuntimeError):
        await registered_tools["admin_register_script"](
            name="bad",
            calls="not-a-list",
        )

    # An invalid behavior tree root fails validation and wraps as ToolError (1081-1082).
    with pytest.raises(RuntimeError):
        await registered_tools["admin_register_behavior"](
            name="bad",
            root="not-a-node",
        )

    with pytest.raises(RuntimeError, match="not controlling"):
        await registered_tools["play_pending_commands"](client_id="missing")


async def test_mcp_controller_definition_tools_report_when_unconfigured(monkeypatch, scenario):
    registered_tools = {}

    class FakeLowServer:
        def __init__(self):
            self.get_capabilities = lambda _n, _e: SimpleNamespace(
                resources=SimpleNamespace(subscribe=False, listChanged=False)
            )

        def subscribe_resource(self):
            return lambda func: func

        def unsubscribe_resource(self):
            return lambda func: func

    _install_fake_fastmcp(
        monkeypatch, registered_tools=registered_tools, low_server=FakeLowServer()
    )

    async def boom(_request):
        raise AssertionError("unused")

    # register_script / register_behavior / list_controller_definitions default to None.
    create_bunnyland_mcp_app(
        actor=scenario.actor,
        meta=WorldMeta(seed="moss"),
        loop=None,
        patch_world=boom,
        generate_world=boom,
        generation_status=boom,
        generate_room=boom,
        generate_character=boom,
        generate_item=boom,
        generate_event=boom,
    )

    with pytest.raises(RuntimeError, match="not configured"):
        registered_tools["admin_list_controller_definitions"]()
    with pytest.raises(RuntimeError, match="not configured"):
        await registered_tools["admin_register_script"](name="x", calls=[])
    with pytest.raises(RuntimeError, match="not configured"):
        await registered_tools["admin_register_behavior"](
            name="x", root={"kind": "action", "ref": "wait"}
        )


async def test_mcp_play_send_command_reports_submission_rejection(monkeypatch, scenario):
    registered_tools = {}

    class FakeLowServer:
        def __init__(self):
            self.get_capabilities = lambda _n, _e: SimpleNamespace(
                resources=SimpleNamespace(subscribe=False, listChanged=False)
            )

        def subscribe_resource(self):
            return lambda func: func

        def unsubscribe_resource(self):
            return lambda func: func

    _install_fake_fastmcp(
        monkeypatch, registered_tools=registered_tools, low_server=FakeLowServer()
    )

    async def boom(_request):
        raise AssertionError("unused")

    create_bunnyland_mcp_app(
        actor=scenario.actor,
        meta=WorldMeta(seed="moss"),
        loop=None,
        patch_world=boom,
        generate_world=boom,
        generation_status=boom,
        generate_room=boom,
        generate_character=boom,
        generate_item=boom,
        generate_event=boom,
    )

    claimed = await registered_tools["play_claim_character"](
        client_id="client-a",
        character_name="Juniper",
    )

    # An unaffordable command under DENY is rejected synchronously (line 977 path) instead
    # of being queued.
    result = await registered_tools["play_send_command"](
        client_id="client-a",
        command_type="move",
        payload={"direction": "north"},
        cost_action=100,
        on_insufficient_points="deny",
        **_claim_args(claimed),
    )

    assert result["ok"] is False
    assert result["queued"] is False
    assert result["reason"]

    # A valid move queues successfully (the accepted branch).
    queued = await registered_tools["play_send_command"](
        client_id="client-a",
        command_type="move",
        payload={"direction": "north"},
        **_claim_args(claimed),
    )
    assert queued["ok"] is True
    assert queued["queued"] is True


@pytest.mark.parametrize("verb", ["take-control", "release-to-llm", "suspend", "resume"])
async def test_mcp_play_send_command_rejects_control_verbs(monkeypatch, scenario, verb):
    # play_send_command must not accept controller-changing verbs: they bypass the
    # generation/ownership gates and would let a claim holder repoint their character at an
    # arbitrary controller. (ToolError is monkeypatched to RuntimeError by the fake fastmcp.)
    registered_tools = {}

    class FakeLowServer:
        def __init__(self):
            self.get_capabilities = lambda _n, _e: SimpleNamespace(
                resources=SimpleNamespace(subscribe=False, listChanged=False)
            )

        def subscribe_resource(self):
            return lambda func: func

        def unsubscribe_resource(self):
            return lambda func: func

    _install_fake_fastmcp(
        monkeypatch, registered_tools=registered_tools, low_server=FakeLowServer()
    )

    async def boom(_request):
        raise AssertionError("unused")

    create_bunnyland_mcp_app(
        actor=scenario.actor,
        meta=WorldMeta(seed="moss"),
        loop=None,
        patch_world=boom,
        generate_world=boom,
        generation_status=boom,
        generate_room=boom,
        generate_character=boom,
        generate_item=boom,
        generate_event=boom,
    )

    claimed = await registered_tools["play_claim_character"](
        client_id="client-a",
        character_name="Juniper",
    )
    other = spawn_entity(
        scenario.actor.world, [WebControllerComponent(client_id="victim", label="other")]
    )

    with pytest.raises(RuntimeError, match="control verb"):
        await registered_tools["play_send_command"](
            client_id="client-a",
            command_type=verb,
            payload={"controller_id": str(other.id)},
            **_claim_args(claimed),
        )


async def test_mcp_admin_fails_closed_when_request_is_absent(monkeypatch, scenario):
    registered_tools = {}

    class FakeLowServer:
        def __init__(self):
            self.get_capabilities = lambda _n, _e: SimpleNamespace(
                resources=SimpleNamespace(subscribe=False, listChanged=False)
            )

        def subscribe_resource(self):
            return lambda func: func

        def unsubscribe_resource(self):
            return lambda func: func

    def context_with_no_request():
        return SimpleNamespace(request_context=SimpleNamespace(request=None), session=object())

    _install_fake_fastmcp(
        monkeypatch,
        registered_tools=registered_tools,
        low_server=FakeLowServer(),
        get_context=context_with_no_request,
    )

    async def boom(_request):
        raise AssertionError("unused")

    create_bunnyland_mcp_app(
        actor=scenario.actor,
        meta=WorldMeta(seed="moss"),
        loop=None,
        patch_world=boom,
        generate_world=boom,
        generation_status=boom,
        generate_room=boom,
        generate_character=boom,
        generate_item=boom,
        generate_event=boom,
    )

    with pytest.raises(RuntimeError, match="authenticated MCP request context required"):
        await registered_tools["admin_patch_world"](operations=[])


async def test_mcp_admin_fails_closed_when_request_context_is_absent(monkeypatch, scenario):
    registered_tools = {}

    class FakeLowServer:
        def __init__(self):
            self.get_capabilities = lambda _n, _e: SimpleNamespace(
                resources=SimpleNamespace(subscribe=False, listChanged=False)
            )

        def subscribe_resource(self):
            return lambda func: func

        def unsubscribe_resource(self):
            return lambda func: func

    _install_fake_fastmcp(
        monkeypatch,
        registered_tools=registered_tools,
        low_server=FakeLowServer(),
        get_context=lambda: SimpleNamespace(session=object()),
    )

    async def boom(_request):
        raise AssertionError("unused")

    create_bunnyland_mcp_app(
        actor=scenario.actor,
        meta=WorldMeta(seed="moss"),
        loop=None,
        patch_world=boom,
        generate_world=boom,
        generation_status=boom,
        generate_room=boom,
        generate_character=boom,
        generate_item=boom,
        generate_event=boom,
    )

    with pytest.raises(RuntimeError, match="authenticated MCP request context required"):
        await registered_tools["admin_patch_world"](operations=[])


async def test_mcp_streamable_client_claims_plays_receives_events_and_releases(scenario):
    import uvicorn
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    plugins = select(bunnyland_plugins(), [MCP, WORLDGEN])
    token_store = TokenStore(":memory:")
    play_token, _principal = token_store.issue(
        "mcp-player", [WORLD_PLAY_SCOPE], automatic_rotation=False
    )
    admin_token, _admin_principal = token_store.issue(
        "mcp-admin", [WORLD_ADMIN_SCOPE], automatic_rotation=False
    )
    port = _free_port()
    app = create_app(
        scenario.actor,
        plugins=plugins,
        token_store=token_store,
        cors_origins=[f"http://127.0.0.1:{port}"],
    )
    mcp_http_client = httpx.AsyncClient(
        headers={
            "Authorization": f"Bearer {play_token}",
            "X-Bunnyland-Client-Id": "e2e-client",
            "Origin": f"http://127.0.0.1:{port}",
        }
    )
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    server_task = asyncio.create_task(server.serve())
    try:
        for _ in range(100):
            if server.started:
                break
            await asyncio.sleep(0.01)
        assert server.started

        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}") as raw_client:
            assert (await raw_client.post("/v1/mcp/", json={})).status_code == 401
            assert (
                await raw_client.post(
                    "/v1/mcp/",
                    headers={"Authorization": "Bearer malformed"},
                    json={},
                )
            ).status_code == 401
            assert (
                await raw_client.post(
                    "/v1/mcp/",
                    headers={
                        "Authorization": f"Bearer {play_token}",
                        "X-Bunnyland-Client-Id": "e2e-client",
                        "Host": "hostile.invalid",
                    },
                    json={},
                )
            ).status_code == 421
            assert (
                await raw_client.post(
                    "/v1/mcp/",
                    headers={
                        "Authorization": f"Bearer {play_token}",
                        "X-Bunnyland-Client-Id": "e2e-client",
                        "Origin": "https://hostile.invalid",
                    },
                    json={},
                )
            ).status_code == 403

        notifications = []

        async def message_handler(message) -> None:
            notifications.append(message)

        async with streamable_http_client(
            f"http://127.0.0.1:{port}/v1/mcp/",
            http_client=mcp_http_client,
        ) as (
            read_stream,
            write_stream,
            _get_session_id,
        ):
            async with ClientSession(
                read_stream,
                write_stream,
                message_handler=message_handler,
            ) as session:
                init = await session.initialize()
                assert init.capabilities.resources is not None
                assert init.capabilities.resources.subscribe is True

                admin_result = await session.call_tool("admin_world_overview", {})
                assert admin_result.isError is True
                assert "world:admin scope required" in admin_result.content[0].text

                client_id = "e2e-client"
                claimed = _tool_result(
                    await session.call_tool(
                        "play_claim_character",
                        {"client_id": client_id, "character_name": "Juniper"},
                    )
                )
                assert claimed["character_name"] == "Juniper"
                claim_payload = _claim_args(claimed)
                mcp_http_client.headers["X-Bunnyland-Claim-Id"] = claimed["claim_id"]
                mcp_http_client.headers["X-Bunnyland-Claim-Secret"] = claimed["claim_secret"]

                projection = _tool_result(
                    await session.call_tool(
                        "play_get_projection",
                        {"client_id": client_id, **claim_payload},
                    )
                )
                assert projection["character_name"] == "Juniper"

                queued = _tool_result(
                    await session.call_tool(
                        "play_send_command",
                        {
                            "client_id": client_id,
                            "command_type": "move",
                            "payload": {"direction": "north"},
                            **claim_payload,
                        },
                    )
                )
                assert queued["queued"] is True

                await scenario.actor.tick(0.0)

                events_payload = _tool_result(
                    await session.call_tool(
                        "play_recent_events",
                        {"client_id": client_id, **claim_payload},
                    )
                )
                event_types = {
                    message["data"]["event_type"] for message in events_payload["events"]
                }
                assert "ActorMovedEvent" in event_types
                assert "ActionPointsChangedEvent" in event_types

                projection = _tool_result(
                    await session.call_tool(
                        "play_get_projection",
                        {"client_id": client_id, **claim_payload},
                    )
                )
                assert projection["room"]["title"] == "North Tunnel"

                released = _tool_result(
                    await session.call_tool(
                        "play_release_control",
                        {"client_id": client_id, **claim_payload},
                    )
                )
                assert released["controller_kind"] == "suspended"
                assert mcp_controlled_character(scenario.actor, client_id) is None
                assert scenario.actor.world.get_entity(scenario.character).has_component(
                    SuspendedComponent
                )

        admin_http_client = httpx.AsyncClient(
            headers={
                "Authorization": f"Bearer {admin_token}",
                "X-Bunnyland-Client-Id": "mcp-admin",
            }
        )
        try:
            async with streamable_http_client(
                f"http://127.0.0.1:{port}/v1/mcp/",
                http_client=admin_http_client,
            ) as (read_stream, write_stream, _get_session_id):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    characters = await session.call_tool("play_list_characters", {})
                    overview = await session.call_tool("admin_world_overview", {})
                    assert characters.isError is False
                    assert overview.isError is False
        finally:
            await admin_http_client.aclose()
    finally:
        server.should_exit = True
        await server_task
        await mcp_http_client.aclose()
        token_store.close()


def _capture_mcp_tools(
    monkeypatch,
    actor,
    *,
    player_client_ids=None,
    admin_client_ids=None,
    loop=None,
    request_headers=_AUTHENTICATED_REQUEST,
    request_scopes=None,
    registered_resources: dict | None = None,
    save_path=None,
    character_chat=None,
) -> dict:
    """Build the MCP app with a fake FastMCP and return its registered tool closures.

    ``request_headers`` simulates the headers an authenticating proxy attaches to the
    streamable-HTTP request the tools run under; when None,
    ``get_context()`` exposes no request, matching a direct/argument-only caller."""

    registered_tools: dict = {}
    resolved_request_headers = {} if request_headers is _AUTHENTICATED_REQUEST else request_headers

    class FakeLowServer:
        def __init__(self):
            self.get_capabilities = lambda _n, _e: SimpleNamespace(
                resources=SimpleNamespace(subscribe=False, listChanged=False)
            )

        def subscribe_resource(self):
            return lambda func: func

        def unsubscribe_resource(self):
            return lambda func: func

    class FakeFastMCP:
        def __init__(self, *args, **kwargs):
            self._mcp_server = FakeLowServer()

        def tool(self):
            def decorate(func):
                registered_tools[func.__name__] = func
                return func

            return decorate

        def resource(self, uri, **_kwargs):
            def decorate(func):
                if registered_resources is not None:
                    registered_resources[uri] = func
                return func

            return decorate

        def get_context(self):
            if resolved_request_headers is None:
                return SimpleNamespace(session=object())
            scopes = (
                [WORLD_PLAY_SCOPE, WORLD_ADMIN_SCOPE] if request_scopes is None else request_scopes
            )
            principal = TokenPrincipal(
                token_id="test-token",
                subject="test-admin",
                scopes=frozenset(scopes),
                created_at=1,
                rotate_after=None,
                expires_at=2**31,
                automatic_rotation=False,
                family_id="test-family",
            )
            return SimpleNamespace(
                session=object(),
                request_context=SimpleNamespace(
                    request=SimpleNamespace(
                        headers=resolved_request_headers,
                        state=SimpleNamespace(auth_principal=principal),
                    )
                ),
            )

        def streamable_http_app(self):
            async def asgi_app(scope, receive, send):
                del scope, receive, send

            return asgi_app

    fastmcp_module = ModuleType("mcp.server.fastmcp")
    exceptions_module = ModuleType("mcp.server.fastmcp.exceptions")
    fastmcp_module.FastMCP = FakeFastMCP
    exceptions_module.ToolError = RuntimeError
    monkeypatch.setitem(sys.modules, "mcp", ModuleType("mcp"))
    monkeypatch.setitem(sys.modules, "mcp.server", ModuleType("mcp.server"))
    monkeypatch.setitem(sys.modules, "mcp.server.fastmcp", fastmcp_module)
    monkeypatch.setitem(sys.modules, "mcp.server.fastmcp.exceptions", exceptions_module)
    create_app(
        actor,
        plugins=select(bunnyland_plugins(), [MCP, WORLDGEN]),
        player_client_ids=player_client_ids,
        admin_client_ids=admin_client_ids,
        loop=loop,
        save_path=save_path,
        character_chat=character_chat,
    )
    return registered_tools


def test_formal_v1_mcp_tool_catalog_is_exact(monkeypatch, scenario):
    expected = json.loads(
        (Path(__file__).parents[1] / "contracts" / "mcp-v1-tools.json").read_text()
    )
    tools = _capture_mcp_tools(monkeypatch, scenario.actor)

    assert set(tools) == set(expected["player"] + expected["admin"])
    assert "list_characters" not in tools
    assert "character_view" not in tools
    assert "world_overview_admin" not in tools


def test_admin_runtime_status_reports_tick_cadence(monkeypatch, scenario):
    loop = SimpleNamespace(running=True, paused=False, tick_seconds=2.0, time_scale=1800.0)
    tools = _capture_mcp_tools(monkeypatch, scenario.actor, loop=loop)

    status = tools["admin_runtime_status"]()
    assert status["running"] is True
    assert status["tick_seconds"] == 2.0
    assert status["time_scale"] == 1800.0
    assert status["game_seconds_per_tick"] == 3600.0

    # No loop -> cadence fields are null rather than missing.
    no_loop = _capture_mcp_tools(monkeypatch, scenario.actor)["admin_runtime_status"]()
    assert no_loop["tick_seconds"] is None
    assert no_loop["game_seconds_per_tick"] is None


def test_play_query_world_uses_claimed_perspective_registry(monkeypatch, scenario):
    from bunnyland.core.perspective import V1_PERSPECTIVE_QUERIES
    from bunnyland.foundation.social.mechanics import SocialBond, create_obligation
    from bunnyland.foundation.social.queries import SOCIAL_PERSPECTIVE_QUERIES

    for definition in V1_PERSPECTIVE_QUERIES:
        scenario.actor.perspective_queries.register(definition, owner="bunnyland.core_verbs")
    for definition in SOCIAL_PERSPECTIVE_QUERIES:
        scenario.actor.perspective_queries.register(definition, owner="bunnyland.social")
    hazel = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="Hazel", kind="character"), CharacterComponent()],
    )
    scenario.actor.world.get_entity(scenario.character).add_relationship(
        SocialBond(familiarity=0.6), hazel.id
    )
    create_obligation(
        scenario.actor.world,
        kind="promise",
        text="Return the key",
        debtor_id=scenario.character,
        creditor_id=hazel.id,
        due_epoch=77,
    )
    tools = _capture_mcp_tools(monkeypatch, scenario.actor)
    claimed = asyncio.run(
        tools["play_claim_character"](client_id="query-client", character_name="Juniper")
    )

    result = tools["play_query_world"](
        client_id="query-client",
        query="valid_targets",
        arguments={"action": "move"},
        claim_id=claimed["claim_id"],
        claim_secret=claimed["claim_secret"],
    )

    assert result["owner"] == "bunnyland.core_verbs"
    assert result["actor_id"] == str(scenario.character)
    assert result["result"]["exit_id"][0]["id"] == str(scenario.room_b)
    connections = tools["play_query_world"](
        client_id="query-client",
        query="social_connections",
        claim_id=claimed["claim_id"],
        claim_secret=claimed["claim_secret"],
    )
    obligations = tools["play_query_world"](
        client_id="query-client",
        query="open_obligations",
        claim_id=claimed["claim_id"],
        claim_secret=claimed["claim_secret"],
    )
    assert connections["result"][0]["character"]["id"] == str(hazel.id)
    assert obligations["result"][0]["role"] == "debtor"
    assert obligations["result"][0]["due_epoch"] == 77
    with pytest.raises(RuntimeError, match="unknown perspective query"):
        tools["play_query_world"](
            client_id="query-client",
            query="raw_relics",
            claim_id=claimed["claim_id"],
            claim_secret=claimed["claim_secret"],
        )


def test_formal_mcp_resources_are_exact_and_scope_enforced(monkeypatch, scenario):
    resources: dict = {}
    _capture_mcp_tools(
        monkeypatch,
        scenario.actor,
        request_scopes=[WORLD_PLAY_SCOPE],
        registered_resources=resources,
    )

    assert set(resources) == {
        "bunnyland://v1/features",
        "bunnyland://v1/catalog",
        "bunnyland://v1/characters",
        "bunnyland://v1/admin/world",
        "bunnyland://v1/admin/runtime",
        "bunnyland://v1/admin/generators",
        "bunnyland://v1/admin/controller-definitions",
        "bunnyland://v1/admin/generation-jobs/current",
    }
    features = json.loads(resources["bunnyland://v1/features"]())
    characters = json.loads(resources["bunnyland://v1/characters"]())
    assert features["mcp"] is True
    assert characters["characters"][0]["name"] == "Juniper"
    with pytest.raises(RuntimeError, match="world:admin scope required"):
        resources["bunnyland://v1/admin/world"]()


def test_formal_admin_mcp_resources_return_operational_state(monkeypatch, scenario):
    resources: dict = {}
    loop = SimpleNamespace(
        running=True,
        paused=False,
        tick_seconds=2.0,
        time_scale=30.0,
    )
    _capture_mcp_tools(
        monkeypatch,
        scenario.actor,
        loop=loop,
        registered_resources=resources,
    )

    world = json.loads(resources["bunnyland://v1/admin/world"]())
    runtime = json.loads(resources["bunnyland://v1/admin/runtime"]())
    generators = json.loads(resources["bunnyland://v1/admin/generators"]())
    definitions = json.loads(resources["bunnyland://v1/admin/controller-definitions"]())
    generation = json.loads(
        asyncio.run(resources["bunnyland://v1/admin/generation-jobs/current"]())
    )

    assert world["room_count"] == 2
    assert runtime["game_seconds_per_tick"] == 60.0
    assert {item["name"] for item in generators["generators"]} >= {
        "empty",
        "oneshot",
        "recursive",
    }
    assert "scripts" in definitions
    assert generation["world_epoch"] == scenario.actor.epoch


async def test_curated_mcp_player_and_admin_workflows(monkeypatch, scenario):
    from bunnyland.core.perspective import V1_PERSPECTIVE_QUERIES

    for definition in V1_PERSPECTIVE_QUERIES:
        scenario.actor.perspective_queries.register(definition, owner="bunnyland.core_verbs")

    class RuntimeLoop:
        running = True
        paused = False
        tick_seconds = 2.0
        time_scale = 30.0

        async def _published(self):
            return None

        def pause(self):
            self.paused = True
            return self._published()

        def resume(self):
            self.paused = False
            return self._published()

    async def chat(character_id, request):
        if request.message == "bad":
            raise ValueError("bad chat")
        assert request.message == "Hello"
        return CharacterChatResponse(
            world_epoch=scenario.actor.epoch,
            character_id=character_id,
            reply="Hello from Juniper.",
        )

    tools = _capture_mcp_tools(
        monkeypatch,
        scenario.actor,
        loop=RuntimeLoop(),
        character_chat=SimpleNamespace(allowed_tools=[], chat=chat),
    )
    claimed = await tools["play_claim_character"](
        client_id="workflow-client", character_name="Juniper"
    )
    claim_args = _claim_args(claimed)

    look = tools["play_look"](client_id="workflow-client", **claim_args)
    help_result = tools["play_action_help"](
        client_id="workflow-client", action="move", **claim_args
    )
    recent = tools["play_recent_events"](client_id="workflow-client", **claim_args)
    changed = tools["play_what_changed"](client_id="workflow-client", since_epoch=0, **claim_args)
    assert "Juniper" in look["summary"]
    assert help_result["action"]["command_type"] == "move"
    assert recent["events"][0]["data"]["event_type"] == "CharacterClaimedEvent"
    assert changed["summary"].startswith("0 visible change")
    with pytest.raises(RuntimeError, match="not controlling"):
        tools["play_look"](client_id="missing")
    with pytest.raises(RuntimeError, match="unknown action"):
        tools["play_action_help"](client_id="workflow-client", action="missing", **claim_args)

    original_execute = scenario.actor.perspective_queries.execute

    def unavailable(*_args, **_kwargs):
        raise TimeoutError("query timed out")

    scenario.actor.perspective_queries.execute = unavailable
    try:
        with pytest.raises(RuntimeError, match="query timed out"):
            tools["play_what_changed"](client_id="workflow-client", since_epoch=0, **claim_args)
    finally:
        scenario.actor.perspective_queries.execute = original_execute

    queued = await tools["play_send_command"](
        client_id="workflow-client",
        command_type="move",
        payload={"direction": "north"},
        **claim_args,
    )
    cancelled = await tools["play_cancel_command"](
        client_id="workflow-client",
        command_id=queued["command_id"],
        **claim_args,
    )
    assert cancelled["status"] == "cancelled"
    with pytest.raises(RuntimeError, match="not pending"):
        await tools["play_cancel_command"](
            client_id="workflow-client",
            command_id=queued["command_id"],
            **claim_args,
        )

    reply = await tools["play_chat"](
        client_id="workflow-client",
        message="Hello",
        **claim_args,
    )
    assert reply["reply"] == "Hello from Juniper."
    with pytest.raises(RuntimeError, match="bad chat"):
        await tools["play_chat"](
            client_id="workflow-client",
            message="bad",
            **claim_args,
        )

    released = await tools["play_release_control"](client_id="workflow-client", **claim_args)
    assert released["controller_kind"] == "suspended"
    reclaimed = await tools["play_reclaim_character"](client_id="workflow-client", **claim_args)
    assert reclaimed["character_id"] == str(scenario.character)

    paused = await tools["admin_pause_world"]()
    resumed = await tools["admin_resume_world"]()
    assert paused["paused"] is True
    assert resumed["paused"] is False
    assert tools["admin_list_controller_definitions"]()["scripts"]
    assert tools["admin_list_generators"]()["generators"]

    await tools["play_release_claim"](client_id="workflow-client", **_claim_args(reclaimed))

    controller = spawn_entity(
        scenario.actor.world,
        [WebControllerComponent(client_id="admin", label="manual")],
    )
    assigned = await tools["admin_assign_controller"](
        character_id=str(scenario.character), controller_id=str(controller.id)
    )
    assert assigned["changed_entities"][0]["id"] == str(scenario.character)
    with pytest.raises(RuntimeError, match="controller does not exist"):
        await tools["admin_assign_controller"](
            character_id=str(scenario.character), controller_id="entity_999"
        )

    script = await tools["admin_register_script"](
        name="workflow_wait", calls=[{"name": "wait", "arguments": {}}]
    )
    behavior = await tools["admin_register_behavior"](
        name="workflow_take",
        root={"kind": "action", "ref": "take_first_item"},
    )
    assert "workflow_wait" in script["stored"]["scripts"]
    assert "workflow_take" in behavior["stored"]["behaviors"]

    without_runtime = _capture_mcp_tools(monkeypatch, scenario.actor)
    with pytest.raises(RuntimeError, match="runtime is not attached"):
        await without_runtime["admin_pause_world"]()
    with pytest.raises(RuntimeError, match="runtime is not attached"):
        await without_runtime["admin_resume_world"]()

    quiet_runtime = SimpleNamespace(
        running=True,
        paused=False,
        tick_seconds=1.0,
        time_scale=1.0,
        pause=lambda: None,
        resume=lambda: None,
    )
    quiet_tools = _capture_mcp_tools(monkeypatch, scenario.actor, loop=quiet_runtime)
    await quiet_tools["admin_pause_world"]()
    await quiet_tools["admin_resume_world"]()

    with pytest.raises(RuntimeError, match="does not own"):
        await tools["play_reclaim_character"](client_id="workflow-client", **_claim_args(reclaimed))


def test_admin_save_world_uses_configured_path(monkeypatch, scenario, tmp_path):
    path = tmp_path / "mcp-save.json"
    tools = _capture_mcp_tools(monkeypatch, scenario.actor, save_path=path)

    saved = asyncio.run(tools["admin_save_world"]())

    assert saved["path"] == str(path)
    assert saved["world_epoch"] == scenario.actor.epoch
    assert path.exists()
    assert json.loads(path.read_text())["bunnyland"]["seed"] == ""


def test_admin_save_world_requires_configured_path(monkeypatch, scenario):
    tools = _capture_mcp_tools(monkeypatch, scenario.actor)

    with pytest.raises(RuntimeError, match="server was not started with --save"):
        asyncio.run(tools["admin_save_world"]())


def test_admin_save_world_wraps_save_errors(monkeypatch, scenario, tmp_path):
    def raise_save_error(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(mcp_server, "save_configured_world", raise_save_error)
    tools = _capture_mcp_tools(
        monkeypatch,
        scenario.actor,
        save_path=tmp_path / "mcp-save.json",
    )

    with pytest.raises(RuntimeError, match="disk full"):
        asyncio.run(tools["admin_save_world"]())


def test_play_send_command_and_queue_report_resolves_at_epoch(monkeypatch, scenario):
    loop = SimpleNamespace(running=True, paused=False, tick_seconds=2.0, time_scale=1800.0)
    tools = _capture_mcp_tools(monkeypatch, scenario.actor, loop=loop)
    claimed = asyncio.run(tools["play_claim_character"](client_id="a", character_name="Juniper"))

    expected = scenario.actor.epoch + 3600  # tick_seconds * time_scale
    queued = asyncio.run(
        tools["play_send_command"](
            client_id="a",
            command_type="move",
            payload={"direction": "north"},
            **_claim_args(claimed),
        )
    )
    assert queued["resolves_at_epoch"] == expected

    pending = tools["play_pending_commands"](client_id="a", **_claim_args(claimed))
    assert pending["commands"][0]["resolves_at_epoch"] == expected

    # With no loop attached, the estimate is null rather than wrong.
    no_loop = _capture_mcp_tools(monkeypatch, scenario.actor, loop=None)
    claimed_no_loop = asyncio.run(
        no_loop["play_claim_character"](
            client_id="a",
            character_name="Juniper",
            **_claim_args(claimed),
        )
    )
    queued_no_loop = asyncio.run(
        no_loop["play_send_command"](
            client_id="a",
            command_type="move",
            payload={"direction": "north"},
            **_claim_args(claimed_no_loop),
        )
    )
    assert queued_no_loop["resolves_at_epoch"] is None


def test_play_get_projection_exposes_actions_and_resolved_target_ids(monkeypatch, scenario):
    from bunnyland.core import ContainmentMode, Contains
    from bunnyland.core.components import PortableComponent

    world = scenario.actor.world
    bun = spawn_entity(
        world,
        [IdentityComponent(name="steamed bun", kind="object"), PortableComponent()],
    )
    world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), bun.id
    )
    tools = _capture_mcp_tools(monkeypatch, scenario.actor)
    claimed = asyncio.run(tools["play_claim_character"](client_id="a", character_name="Juniper"))

    view = tools["play_get_projection"](client_id="a", **_claim_args(claimed))
    assert view["character_name"] == "Juniper"
    # Progressive disclosure: the full action catalogue is omitted here.
    assert "actions" not in view
    assert view["action_count"] >= 1
    assert "play_search_actions" in view["actions_hint"]
    # The portable item still resolves to a concrete entity id the agent can target.
    reachable_ids = {target["id"] for target in view["target_groups"]["reachableItems"]}
    assert str(bun.id) in reachable_ids
    exit_ids = {target["id"] for target in view["target_groups"]["exits"]}
    assert str(scenario.room_b) in exit_ids

    with pytest.raises(RuntimeError, match="not controlling"):
        tools["play_get_projection"](client_id="missing")


def test_examine_inspects_perceivable_entity_and_self(monkeypatch, scenario):
    from bunnyland.core import ContainmentMode, Contains
    from bunnyland.core.components import PortableComponent
    from bunnyland.foundation.consumables.components import FoodComponent

    world = scenario.actor.world
    bun = spawn_entity(
        world,
        [
            IdentityComponent(name="steamed bun", kind="food"),
            PortableComponent(),
            FoodComponent(nutrition=5.0, satiety=10.0),
        ],
    )
    world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), bun.id
    )
    tools = _capture_mcp_tools(monkeypatch, scenario.actor)
    claimed = asyncio.run(tools["play_claim_character"](client_id="a", character_name="Juniper"))

    # Examining a perceivable item exposes its component values.
    item = tools["play_examine"](client_id="a", entity_id=str(bun.id), **_claim_args(claimed))
    assert item["is_self"] is False
    assert item["name"] == "steamed bun"
    assert item["details"]["food"]["satiety"] == 10.0
    assert "portable" in item["details"]
    assert item["points"] is None

    # Examining yourself (default target) adds points + the is_self flag.
    me = tools["play_examine"](client_id="a", **_claim_args(claimed))
    assert me["is_self"] is True
    assert me["name"] == "Juniper"
    assert me["points"]["action"] == 5.0

    # An entity the character cannot perceive (an adjacent room) is rejected.
    with pytest.raises(RuntimeError, match="not perceivable"):
        tools["play_examine"](client_id="a", entity_id=str(scenario.room_b), **_claim_args(claimed))


def test_serialize_examine_self_needs_and_targets(scenario):
    from bunnyland.core import (
        ActionPointsComponent,
        CharacterComponent,
        ContainmentMode,
        Contains,
        FocusPointsComponent,
    )
    from bunnyland.core.components import AffectComponent, DoorComponent, SleepingComponent
    from bunnyland.foundation.meters.mechanics import Meter
    from bunnyland.foundation.needs.mechanics import HungerComponent, need_fragments
    from bunnyland.server.serialization import serialize_examine

    world = scenario.actor.world
    room = world.get_entity(scenario.room_a)
    me = spawn_entity(
        world,
        [
            IdentityComponent(name="Mossy", kind="character"),
            CharacterComponent(species="bunny"),
            ActionPointsComponent(current=3.0, maximum=5.0, regen_per_hour=1.0),
            FocusPointsComponent(current=1.0, maximum=3.0, regen_per_hour=0.5),
            HungerComponent(),
            AffectComponent(labels=("content",)),
        ],
    )
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), me.id)

    me_view = serialize_examine(
        scenario.actor,
        str(me.id),
        fragment_providers=[lambda _world, _entity: ["feeling peckish"]],
    )
    assert me_view.is_self is True
    assert "hunger" in me_view.details
    assert me_view.details["affect"]["labels"] == ["content"]
    assert me_view.status == ["feeling peckish"]
    assert len(me_view.facts) == 1
    assert me_view.facts[0].key.endswith(".fact-0")
    assert me_view.facts[0].text == "feeling peckish"
    assert me_view.facts[0].detail == 10
    assert me_view.points.action == 3.0

    # A sleeping neighbour: outward condition is visible, private needs are not.
    sleeper = spawn_entity(
        world,
        [
            IdentityComponent(name="Drowsy", kind="character"),
            CharacterComponent(species="bunny"),
            HungerComponent(),
            SleepingComponent(),
        ],
    )
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), sleeper.id)
    sleeper_view = serialize_examine(
        scenario.actor,
        str(me.id),
        str(sleeper.id),
        fragment_providers=[need_fragments],
    )
    assert sleeper_view.is_self is False
    assert "asleep" in sleeper_view.details["condition"]
    assert "hunger" not in sleeper_view.details  # private state stays hidden
    assert sleeper_view.facts == []  # calm internal state is not outwardly observable

    starving = spawn_entity(
        world,
        [
            IdentityComponent(name="Gaunt", kind="character"),
            CharacterComponent(species="bunny"),
            HungerComponent(meter=Meter(value=95.0)),
        ],
    )
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), starving.id)
    starving_view = serialize_examine(
        scenario.actor,
        str(me.id),
        str(starving.id),
        fragment_providers=[need_fragments],
    )
    assert [fact.model_dump() for fact in starving_view.facts] == [
        {
            "key": "needs.hunger",
            "text": "They are starving and feel weak.",
            "detail": 0,
        }
    ]

    door = spawn_entity(world, [IdentityComponent(name="hatch", kind="door"), DoorComponent()])
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), door.id)
    door_view = serialize_examine(scenario.actor, str(me.id), str(door.id))
    assert door_view.is_self is False
    assert "door" in door_view.details

    with pytest.raises(ValueError, match="does not exist"):
        serialize_examine(scenario.actor, str(me.id), "entity_999")


def test_search_and_list_actions_tools(monkeypatch, scenario):
    tools = _capture_mcp_tools(monkeypatch, scenario.actor)

    found = tools["play_search_actions"](query="move")
    assert found["query"] == "move"
    assert "move" in {action["command_type"] for action in found["actions"]}
    assert found["returned"] == len(found["actions"])

    empty = tools["play_search_actions"](query="zzznotaverb")
    assert empty["actions"] == []
    assert empty["total_available"] == 0

    # limit caps the returned page while total_available reflects the full match count.
    capped = tools["play_search_actions"](query="", limit=1)
    assert capped["returned"] == 1
    assert capped["total_available"] >= 1

    # An empty search returns the whole available catalogue.
    full = tools["play_search_actions"](query="", limit=0)
    assert "move" in {action["command_type"] for action in full["actions"]}
    assert full["returned"] >= found["returned"]
    assert full["returned"] == full["total_available"]


def test_play_search_actions_substring_vs_word_mode(monkeypatch, scenario):
    tools = _capture_mcp_tools(monkeypatch, scenario.actor)

    # "ove" is inside "move" -> substring matches, word (boundary) does not.
    substring = tools["play_search_actions"](query="ove", mode="substring")
    assert substring["mode"] == "substring"
    assert "move" in {action["command_type"] for action in substring["actions"]}

    word = tools["play_search_actions"](query="ove", mode="word")
    assert word["mode"] == "word"
    assert "move" not in {action["command_type"] for action in word["actions"]}

    # A word-start query still finds it under word mode.
    word_hit = tools["play_search_actions"](query="mov", mode="word")
    assert "move" in {action["command_type"] for action in word_hit["actions"]}

    with pytest.raises(RuntimeError, match="mode must be"):
        tools["play_search_actions"](query="move", mode="bogus")


def test_play_search_actions_smart_mode_uses_chroma(monkeypatch, scenario):
    import bunnyland.server.action_search as action_search

    class _Handler:
        def __init__(self, command_type: str) -> None:
            self.command_type = command_type

    for command_type in ("inspect", "say", "take"):
        scenario.actor.register_handler(_Handler(command_type))

    class FakeCollection:
        def __init__(self) -> None:
            self.ids: list[str] = []
            self.documents: list[str] = []
            self.metadatas: list[dict] = []

        def upsert(self, *, ids, documents, metadatas):
            self.ids = list(ids)
            self.documents = list(documents)
            self.metadatas = list(metadatas)

        def query(self, *, query_texts, n_results):
            query_tokens = set(query_texts[0].lower().split())

            def score(row):
                id_, document = row
                doc_tokens = set(document.lower().split())
                return (len(query_tokens & doc_tokens), id_ == "move", id_)

            ranked = sorted(zip(self.ids, self.documents, strict=False), key=score, reverse=True)
            return {"ids": [[id_ for id_, _document in ranked[:n_results]]]}

    class FakeClient:
        def __init__(self) -> None:
            self.collection = FakeCollection()

        def get_or_create_collection(self, *, name, **kwargs):
            assert name.startswith("bunnyland-action-verbs-")
            assert kwargs["embedding_function"].name() == "bunnyland-action-search"
            return self.collection

    fake_client = FakeClient()
    fake_chromadb = ModuleType("chromadb")
    fake_chromadb.EphemeralClient = lambda: fake_client
    monkeypatch.setitem(sys.modules, "chromadb", fake_chromadb)
    monkeypatch.setattr(action_search, "_SMART_ACTION_INDEX", None)
    tools = _capture_mcp_tools(monkeypatch, scenario.actor)

    result = tools["play_search_actions"](query="walk north", mode="smart", limit=3)

    assert result["query"] == "walk north"
    assert result["mode"] == "smart"
    assert result["returned"] == 3
    assert result["actions"][0]["command_type"] == "move"
    assert {"inspect", "move", "say", "take"}.issubset(set(fake_client.collection.ids))
    assert len(fake_client.collection.documents) == result["total_available"]
    action_search._SMART_ACTION_INDEX = None


def test_play_search_actions_smart_mode_reports_missing_chroma(monkeypatch, scenario):
    import bunnyland.server.action_search as action_search

    monkeypatch.setitem(sys.modules, "chromadb", None)
    monkeypatch.setattr(action_search, "_SMART_ACTION_INDEX", None)
    tools = _capture_mcp_tools(monkeypatch, scenario.actor)

    with pytest.raises(RuntimeError, match="smart action search requires"):
        tools["play_search_actions"](query="walk north", mode="smart")
    action_search._SMART_ACTION_INDEX = None


def test_admin_world_overview_tool_is_gated_and_returns_room_network(monkeypatch, scenario):
    tools = _capture_mcp_tools(monkeypatch, scenario.actor)
    assert not inspect.signature(tools["admin_world_overview"]).parameters
    overview = tools["admin_world_overview"]()
    assert overview["room_count"] == 2
    assert overview["character_count"] == 1
    titles = {room["title"] for room in overview["rooms"]}
    assert titles == {"Mosslit Burrow", "North Tunnel"}


def test_admin_tool_authorizes_via_request_principal(monkeypatch, scenario):
    tools = _capture_mcp_tools(
        monkeypatch,
        scenario.actor,
        request_headers={},
    )

    overview = tools["admin_world_overview"]()
    assert overview["room_count"] == 2

    # A valid play-only bearer principal cannot invoke an admin tool.
    rejected = _capture_mcp_tools(
        monkeypatch,
        scenario.actor,
        request_headers={},
        request_scopes=[WORLD_PLAY_SCOPE],
    )
    with pytest.raises(RuntimeError, match="world:admin scope required"):
        rejected["admin_world_overview"]()


def test_admin_tool_schema_has_no_credential_argument(monkeypatch, scenario):
    tools = _capture_mcp_tools(monkeypatch, scenario.actor)
    assert not inspect.signature(tools["admin_world_overview"]).parameters


def test_mcp_admin_client_id_allowlist_uses_injected_header(monkeypatch, scenario):
    missing = _capture_mcp_tools(
        monkeypatch,
        scenario.actor,
        admin_client_ids=["admin-a"],
    )
    with pytest.raises(RuntimeError, match="admin client_id is required"):
        missing["admin_world_overview"]()

    rejected = _capture_mcp_tools(
        monkeypatch,
        scenario.actor,
        admin_client_ids=["admin-a"],
        request_headers={
            CLIENT_ID_HEADER: "admin-b",
        },
    )
    with pytest.raises(RuntimeError, match="admin client_id is not allowed"):
        rejected["admin_world_overview"]()

    allowed = _capture_mcp_tools(
        monkeypatch,
        scenario.actor,
        admin_client_ids=["admin-a"],
        request_headers={
            CLIENT_ID_HEADER: "admin-a",
        },
    )
    assert allowed["admin_world_overview"]()["room_count"] == 2


def test_mcp_player_client_id_allowlist_gates_claim_tool(monkeypatch, scenario):
    tools = _capture_mcp_tools(
        monkeypatch,
        scenario.actor,
        player_client_ids=["client-a"],
    )

    with pytest.raises(RuntimeError, match="player client_id is not allowed"):
        asyncio.run(tools["play_claim_character"](client_id="client-b", character_name="Juniper"))

    claimed = asyncio.run(
        tools["play_claim_character"](client_id="client-a", character_name="Juniper")
    )
    assert claimed["client_id"] == "client-a"


def test_mcp_player_identity_and_claim_secret_come_from_request_headers(monkeypatch, scenario):
    tools = _capture_mcp_tools(
        monkeypatch,
        scenario.actor,
        request_headers={CLIENT_ID_HEADER: "header-client"},
    )

    with pytest.raises(RuntimeError, match="must match the authenticated request header"):
        asyncio.run(
            tools["play_claim_character"](client_id="argument-client", character_name="Juniper")
        )

    claimed = asyncio.run(
        tools["play_claim_character"](client_id="header-client", character_name="Juniper")
    )
    with pytest.raises(RuntimeError, match="must be supplied in X-Bunnyland-Claim-Secret"):
        tools["play_get_projection"](client_id="header-client", **_claim_args(claimed))


def test_catalog_resource_includes_component_schemas(monkeypatch, scenario):
    resources: dict = {}
    _capture_mcp_tools(monkeypatch, scenario.actor, registered_resources=resources)

    catalog = json.loads(resources["bunnyland://v1/catalog"]())
    assert "RoomComponent" in catalog["components"]
    assert "title" in catalog["components"]["RoomComponent"]["json_schema"]["properties"]
    assert len(catalog["components"]) > 1


def test_play_pending_commands_reflects_queue(monkeypatch, scenario):
    tools = _capture_mcp_tools(monkeypatch, scenario.actor)
    claimed = asyncio.run(tools["play_claim_character"](client_id="a", character_name="Juniper"))

    asyncio.run(
        tools["play_send_command"](
            client_id="a",
            command_type="move",
            payload={"direction": "north"},
            **_claim_args(claimed),
        )
    )
    pending = tools["play_pending_commands"](client_id="a", **_claim_args(claimed))
    assert [command["command_type"] for command in pending["commands"]] == ["move"]


def test_play_send_command_returns_outcome_hint(monkeypatch, scenario):
    tools = _capture_mcp_tools(monkeypatch, scenario.actor)
    claimed = asyncio.run(tools["play_claim_character"](client_id="a", character_name="Juniper"))

    queued = asyncio.run(
        tools["play_send_command"](
            client_id="a",
            command_type="move",
            payload={"direction": "north"},
            **_claim_args(claimed),
        )
    )
    assert queued["queued"] is True
    assert "play_recent_events" in queued["note"]


def test_play_send_command_rejects_unknown_command_type(monkeypatch, scenario):
    tools = _capture_mcp_tools(monkeypatch, scenario.actor)
    claimed = asyncio.run(tools["play_claim_character"](client_id="a", character_name="Juniper"))

    # Fail fast on a typo'd verb instead of queuing it for a tick-later rejection.
    with pytest.raises(RuntimeError, match="unknown command_type"):
        asyncio.run(
            tools["play_send_command"](
                client_id="a",
                command_type="flibber",
                **_claim_args(claimed),
            )
        )

    queued = asyncio.run(
        tools["play_send_command"](
            client_id="a",
            command_type="move",
            payload={"direction": "north"},
            **_claim_args(claimed),
        )
    )
    assert queued["queued"] is True


def test_play_recent_events_tool_reports_rejection(monkeypatch, scenario):
    tools = _capture_mcp_tools(monkeypatch, scenario.actor)
    claimed = asyncio.run(tools["play_claim_character"](client_id="a", character_name="Juniper"))

    # A valid verb that the handler rejects on resolution (no exit in that direction).
    asyncio.run(
        tools["play_send_command"](
            client_id="a",
            command_type="move",
            payload={"direction": "west"},
            **_claim_args(claimed),
        )
    )
    asyncio.run(scenario.actor.tick(0.0))

    first = tools["play_recent_events"](client_id="a", **_claim_args(claimed))
    assert first["ok"] is True
    rejected = [
        message["data"]["event"]
        for message in first["events"]
        if message["data"]["event_type"] == "CommandRejectedEvent"
    ]
    assert rejected and rejected[0]["command_type"] == "move"
    assert first["next_cursor"] > 0
    # The watermark advances: re-polling from it yields nothing new.
    second = tools["play_recent_events"](
        client_id="a",
        since=first["next_cursor"],
        **_claim_args(claimed),
    )
    assert second["events"] == []
    assert second["next_cursor"] == first["next_cursor"]


async def test_perceived_for_client_scopes_and_paginates(scenario):
    from bunnyland.core.events import CommandRejectedEvent

    assign_mcp_controller(scenario.actor, client_id="a", character_name="Juniper")
    bridge = mcp_server.MCPEventBridge(scenario.actor)
    character_id = str(scenario.character)

    def rejection(actor_id: str | None, room_id: str | None) -> CommandRejectedEvent:
        return CommandRejectedEvent(
            event_id=f"r{actor_id}{room_id}",
            world_epoch=0,
            created_at=datetime.now(UTC),
            actor_id=actor_id,
            room_id=room_id,
            command_id="c",
            command_type="use",
            reason="no handler",
        )

    # caused by character, perceived in the character's room, and an unrelated event.
    await bridge.record(rejection(character_id, None))
    await bridge.record(rejection("someone-else", str(scenario.room_a)))
    await bridge.record(rejection("someone-else", str(scenario.room_b)))

    first = bridge.perceived_for_client("a", limit=1)
    assert len(first["events"]) == 1  # paginated: more remain
    assert first["next_cursor"] == 1

    rest = bridge.perceived_for_client("a", since=first["next_cursor"])
    actor_ids = {message["data"]["event"]["actor_id"] for message in rest["events"]}
    assert actor_ids == {"someone-else"}  # only the same-room event, not room_b
    assert rest["next_cursor"] == 3

    assert bridge.perceived_for_client("missing")["ok"] is False
    bridge.close()


def test_create_bunnyland_mcp_app_missing_extra_raises(monkeypatch, scenario):
    monkeypatch.setitem(sys.modules, "mcp", None)
    monkeypatch.setitem(sys.modules, "mcp.server", None)
    monkeypatch.setitem(sys.modules, "mcp.server.fastmcp", None)
    monkeypatch.setitem(sys.modules, "mcp.server.fastmcp.exceptions", None)

    async def _unused(*_args, **_kwargs):  # pragma: no cover - never invoked
        raise AssertionError("callable should not run before the import guard")

    with pytest.raises(RuntimeError, match="the MCP server requires the 'mcp' extra"):
        create_bunnyland_mcp_app(
            actor=scenario.actor,
            meta=WorldMeta(seed="moss"),
            loop=None,
            patch_world=_unused,
            generate_world=_unused,
            generation_status=_unused,
            generate_room=_unused,
            generate_character=_unused,
            generate_item=_unused,
            generate_event=_unused,
        )
