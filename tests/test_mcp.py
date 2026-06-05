from __future__ import annotations

import asyncio
import json
import socket
import sys
from types import ModuleType, SimpleNamespace

from pydantic import AnyUrl

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
from bunnyland.mcp import (
    EVENTS_RESOURCE_URI,
    assign_mcp_controller,
    mcp_controlled_character,
    mcp_enabled,
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
