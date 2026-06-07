from __future__ import annotations

import asyncio
import json
import socket
import sys
from datetime import UTC, datetime
from types import ModuleType, SimpleNamespace

import pytest
from pydantic import AnyUrl

import bunnyland.mcp.server as mcp_server
from bunnyland.cli import select_plugins
from bunnyland.core import (
    CharacterComponent,
    ControlledBy,
    IdentityComponent,
    MCPControllerComponent,
    SuspendedComponent,
    WorldActor,
    spawn_entity,
)
from bunnyland.core.events import ActorMovedEvent
from bunnyland.mcp import (
    EVENTS_RESOURCE_URI,
    assign_mcp_controller,
    mcp_controlled_character,
    mcp_enabled,
    release_mcp_controller,
    render_mcp_agent_prompt,
)
from bunnyland.mechanics.lifesim import LifeStageComponent
from bunnyland.plugins import bunnyland_plugins, select
from bunnyland.plugins.builtin import MCP, WORLDGEN
from bunnyland.server.app import create_app


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _tool_result(result) -> dict:
    if result.structuredContent is not None:
        return result.structuredContent
    return json.loads(result.content[0].text)


def test_select_plugins_can_add_mcp_without_disabling_defaults():
    selected = select_plugins([], None, extra_enabled_ids=(MCP,))
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

    prompt_uri = mcp_server._agent_prompt_uri("agent/a b")

    assert prompt_uri == "bunnyland://agents/agent%2Fa%20b/prompt"
    assert mcp_server._agent_id_from_uri(prompt_uri, "/prompt") == "agent/a b"
    assert mcp_server._agent_id_from_uri(prompt_uri, "/events") is None
    assert mcp_server._agent_id_from_uri("bunnyland://rooms/1/prompt", "/prompt") is None
    assert mcp_server._active_controller_kind(actor, active) == "other"
    assert mcp_server._character_summary(actor, suspended)["controller_status"] == "suspended"
    assert {
        item["name"]: item["controller_status"]
        for item in mcp_server.list_mcp_characters(actor)
    } == {"Clover": "suspended", "Juniper": "other"}


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

    with pytest.raises(RuntimeError, match="agent is not controlling"):
        mcp_server._controlled_or_requested_character(actor, "agent-a", None)
    with pytest.raises(RuntimeError, match="does not exist"):
        mcp_server._controlled_or_requested_character(actor, "agent-a", "entity_999")

    assign_mcp_controller(actor, agent_id="agent-a", character_name="Juniper")

    assert mcp_server._controlled_or_requested_character(actor, "agent-a", None)[0] == character.id
    assert (
        mcp_server._controlled_or_requested_character(actor, "agent-a", str(character.id))[0]
        == character.id
    )
    with pytest.raises(RuntimeError, match="does not control the requested character"):
        mcp_server._controlled_or_requested_character(actor, "agent-a", str(other.id))


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

    claimed = assign_mcp_controller(actor, agent_id="agent-a", character_name="Juniper")

    assert claimed["character_name"] == "Juniper"
    assert not character.has_component(SuspendedComponent)
    controller_id = character.get_relationships(ControlledBy)[0][1]
    controller = actor.world.get_entity(controller_id)
    mcp = controller.get_component(MCPControllerComponent)
    assert mcp.agent_id == "agent-a"
    assert mcp_controlled_character(actor, "agent-a") == (character.id, controller_id, 0)


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

    claimed = assign_mcp_controller(actor, agent_id="agent-a")

    assert claimed["character_name"] == "Juniper"
    assert child.has_component(SuspendedComponent)
    assert not adult.has_component(SuspendedComponent)
    assert mcp_controlled_character(actor, "agent-a")[0] == adult.id


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

    with pytest.raises(RuntimeError, match="agent_id is required"):
        assign_mcp_controller(actor, agent_id=" ")

    with pytest.raises(RuntimeError, match="no character with id 'entity_999' exists"):
        assign_mcp_controller(actor, agent_id="agent-a", character_id="entity_999")

    with pytest.raises(RuntimeError, match="multiple characters match 'Jun'"):
        assign_mcp_controller(actor, agent_id="agent-a", character_name="Jun")

    with pytest.raises(RuntimeError, match="no character named 'Hazel' exists"):
        assign_mcp_controller(actor, agent_id="agent-a", character_name="Hazel")

    with pytest.raises(RuntimeError, match="child character"):
        assign_mcp_controller(actor, agent_id="agent-a", character_id=str(child.id))

    claimed = assign_mcp_controller(
        actor,
        agent_id="agent-a",
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

    with pytest.raises(RuntimeError, match="agent is not controlling a character yet"):
        release_mcp_controller(actor, agent_id="agent-a")

    assign_mcp_controller(actor, agent_id="agent-a", character_name="Juniper")
    with pytest.raises(RuntimeError, match="mode must be 'suspend' or 'llm'"):
        release_mcp_controller(actor, agent_id="agent-a", mode="manual")

    assign_mcp_controller(actor, agent_id="agent-a", character_name="Juniper")
    monkeypatch.setenv("BUNNYLAND_CHARACTER_MODEL", "env-model")
    released = release_mcp_controller(
        actor,
        agent_id="agent-a",
        mode="llm",
        provider="openrouter",
    )
    controller_id = character.get_relationships(ControlledBy)[0][1]
    controller = actor.world.get_entity(controller_id)
    llm = controller.get_component(mcp_server.LLMControllerComponent)

    assert released["controller_kind"] == "llm"
    assert released["controller_id"] == str(controller_id)
    assert llm.model == "env-model"
    assert llm.provider == "openrouter"
    assert not character.has_component(SuspendedComponent)


def test_mcp_admin_token_and_prompt_errors(monkeypatch, scenario):
    monkeypatch.delenv(mcp_server.ADMIN_TOKEN_ENV, raising=False)

    with pytest.raises(PermissionError, match="BUNNYLAND_MCP_ADMIN_TOKEN is not configured"):
        mcp_server._require_admin_token("secret", None)

    monkeypatch.setenv(mcp_server.ADMIN_TOKEN_ENV, "secret")
    with pytest.raises(PermissionError, match="invalid MCP admin token"):
        mcp_server._require_admin_token("wrong", None)
    mcp_server._require_admin_token("secret", None)

    with pytest.raises(RuntimeError, match="agent is not controlling a character yet"):
        render_mcp_agent_prompt(scenario.actor, agent_id="agent-a")


async def test_mcp_event_bridge_filters_and_notifies_agent_resources(scenario):
    class Session:
        def __init__(self, *, fail: bool = False) -> None:
            self.fail = fail
            self.updated: list[str] = []

        async def send_resource_updated(self, uri: AnyUrl) -> None:
            if self.fail:
                raise RuntimeError("gone")
            self.updated.append(str(uri))

    assign_mcp_controller(scenario.actor, agent_id="agent-a", character_name="Juniper")
    bridge = mcp_server.MCPEventBridge(scenario.actor)
    world_session = Session()
    agent_session = Session()
    prompt_session = Session()
    stale_session = Session(fail=True)
    bridge.subscribe(EVENTS_RESOURCE_URI, world_session)
    bridge.subscribe(mcp_server._agent_events_uri("agent-a"), agent_session)
    bridge.subscribe(mcp_server._agent_prompt_uri("agent-a"), prompt_session)
    bridge.subscribe(mcp_server._agent_events_uri("missing"), stale_session)

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
        assert bridge.recent_for_agent("agent-a")
        assert bridge.recent_for_agent("missing") == []
        assert world_session.updated == [EVENTS_RESOURCE_URI]
        assert agent_session.updated == [mcp_server._agent_events_uri("agent-a")]
        assert prompt_session.updated == [mcp_server._agent_prompt_uri("agent-a")]
        assert stale_session.updated == []
    finally:
        bridge.close()


def test_create_app_mounts_mcp_inside_existing_fastapi_app(monkeypatch, scenario):
    captured = {}
    registered_tools = []
    registered_resources = []

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
        def __init__(self, *args, **kwargs):
            captured["args"] = args
            captured["kwargs"] = kwargs
            self._mcp_server = FakeLowServer()

        def tool(self):
            def decorate(func):
                registered_tools.append(func.__name__)
                return func

            return decorate

        def resource(self, uri, **_kwargs):
            def decorate(func):
                registered_resources.append((uri, func.__name__))
                return func

            return decorate

        def get_context(self):
            raise AssertionError("not used during app creation")

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

    app = create_app(
        scenario.actor,
        plugins=select(bunnyland_plugins(), [MCP, WORLDGEN]),
        mcp_admin_token="secret",
    )

    paths = {route.path for route in app.routes}
    assert "/mcp" in paths
    assert captured["args"] == ("Bunnyland",)
    assert captured["kwargs"]["stateless_http"] is False
    assert captured["kwargs"]["json_response"] is True
    assert captured["kwargs"]["streamable_http_path"] == "/"
    assert "claim_character" in registered_tools
    assert "release_character" in registered_tools
    assert "send_command" in registered_tools
    assert "agent_prompt" in registered_tools
    assert "patch_world_admin" in registered_tools
    assert (EVENTS_RESOURCE_URI, "recent_world_events_resource") in registered_resources


async def test_mcp_streamable_client_claims_plays_receives_events_and_releases(scenario):
    import uvicorn
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client
    from mcp.types import ResourceUpdatedNotification, ServerNotification

    plugins = select(bunnyland_plugins(), [MCP, WORLDGEN])
    app = create_app(scenario.actor, plugins=plugins, mcp_admin_token="secret")
    port = _free_port()
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    )
    server_task = asyncio.create_task(server.serve())
    try:
        for _ in range(100):
            if server.started:
                break
            await asyncio.sleep(0.01)
        assert server.started

        notifications = []

        async def message_handler(message) -> None:
            notifications.append(message)

        async with streamable_http_client(f"http://127.0.0.1:{port}/mcp") as (
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

                agent_id = "e2e-agent"
                agent_events_uri = f"bunnyland://agents/{agent_id}/events"
                agent_prompt_uri = f"bunnyland://agents/{agent_id}/prompt"
                await session.subscribe_resource(AnyUrl(EVENTS_RESOURCE_URI))
                await session.subscribe_resource(AnyUrl(agent_events_uri))
                await session.subscribe_resource(AnyUrl(agent_prompt_uri))

                claimed = _tool_result(
                    await session.call_tool(
                        "claim_character",
                        {"agent_id": agent_id, "character_name": "Juniper"},
                    )
                )
                assert claimed["character_name"] == "Juniper"

                prompt = _tool_result(
                    await session.call_tool("agent_prompt", {"agent_id": agent_id})
                )
                assert "You are Juniper" in prompt["prompt"]
                assert "controlled by an MCP agent" in prompt["prompt"]

                queued = _tool_result(
                    await session.call_tool(
                        "send_command",
                        {
                            "agent_id": agent_id,
                            "command_type": "move",
                            "payload": {"direction": "north"},
                        },
                    )
                )
                assert queued["queued"] is True

                await scenario.actor.tick(0.0)

                for _ in range(100):
                    if any(
                        isinstance(message, ServerNotification)
                        and isinstance(message.root, ResourceUpdatedNotification)
                        for message in notifications
                    ):
                        break
                    await asyncio.sleep(0.01)

                updated_uris = [
                    str(message.root.params.uri)
                    for message in notifications
                    if isinstance(message, ServerNotification)
                    and isinstance(message.root, ResourceUpdatedNotification)
                ]
                assert EVENTS_RESOURCE_URI in updated_uris
                assert agent_events_uri in updated_uris
                assert agent_prompt_uri in updated_uris

                agent_events = await session.read_resource(AnyUrl(agent_events_uri))
                events_payload = json.loads(agent_events.contents[0].text)
                event_types = {
                    message["data"]["event_type"] for message in events_payload["events"]
                }
                assert "ActorMovedEvent" in event_types
                assert "ActionPointsChangedEvent" in event_types

                prompt_resource = await session.read_resource(AnyUrl(agent_prompt_uri))
                assert "North Tunnel" in prompt_resource.contents[0].text

                released = _tool_result(
                    await session.call_tool("release_character", {"agent_id": agent_id})
                )
                assert released["controller_kind"] == "suspended"
                assert mcp_controlled_character(scenario.actor, agent_id) is None
                assert scenario.actor.world.get_entity(scenario.character).has_component(
                    SuspendedComponent
                )
    finally:
        server.should_exit = True
        await server_task
