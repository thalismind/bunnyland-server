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
    LLMControllerComponent,
    MCPControllerComponent,
    SuspendedComponent,
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
    release_mcp_controller,
    render_mcp_agent_prompt,
)
from bunnyland.mechanics.lifesim import LifeStageComponent
from bunnyland.persistence import WorldMeta
from bunnyland.plugins import bunnyland_plugins, select
from bunnyland.plugins.builtin import MCP, WORLDGEN
from bunnyland.server.app import create_app
from bunnyland.server.models import (
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
        [MCPControllerComponent(agent_id="agent-a")],
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

    with pytest.raises(PermissionError, match="BUNNYLAND_ADMIN_TOKEN is not configured"):
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


def test_create_app_mounts_mcp_inside_existing_fastapi_app(monkeypatch, scenario, tmp_path):
    captured = {}
    registered_tools = {}
    registered_resources = {}
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

        def get_context(self):
            return SimpleNamespace(session=object())

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
        admin_token="secret",
        imagegen=imagegen,
    )

    paths = {route.path for route in app.routes}
    assert "/mcp" in paths
    assert "request_scene_image" in registered_tools
    assert captured["args"] == ("Bunnyland",)
    assert captured["kwargs"]["stateless_http"] is False
    assert captured["kwargs"]["json_response"] is True
    assert captured["kwargs"]["streamable_http_path"] == "/"
    assert "claim_character" in registered_tools
    assert "release_character" in registered_tools
    assert "send_command" in registered_tools
    assert "agent_prompt" in registered_tools
    assert "patch_world_admin" in registered_tools
    assert registered_resources[EVENTS_RESOURCE_URI].__name__ == "recent_world_events_resource"
    recent_events = json.loads(registered_resources[EVENTS_RESOURCE_URI]())
    assert recent_events == {"ok": True, "events": []}
    assert registered_low_server["unsubscribe_resource"].__name__ == "unsubscribe_resource"
    asyncio.run(registered_low_server["unsubscribe_resource"](AnyUrl(EVENTS_RESOURCE_URI)))

    with pytest.raises(RuntimeError, match="agent is not controlling"):
        registered_tools["agent_prompt"](agent_id="missing")

    patch_world_admin = registered_tools["patch_world_admin"]
    with pytest.raises(RuntimeError, match="invalid MCP admin token"):
        asyncio.run(patch_world_admin(admin_token=None, operations=[]))
    with pytest.raises(RuntimeError, match="invalid MCP admin token"):
        asyncio.run(patch_world_admin(admin_token="wrong", operations=[]))

    patched = asyncio.run(patch_world_admin(admin_token="secret", operations=[]))
    assert patched["ok"] is True

    registered_tools.clear()
    monkeypatch.delenv(mcp_server.ADMIN_TOKEN_ENV, raising=False)
    create_app(
        scenario.actor,
        plugins=select(bunnyland_plugins(), [MCP, WORLDGEN]),
        admin_token=None,
    )
    patch_world_admin = registered_tools["patch_world_admin"]
    with pytest.raises(RuntimeError, match="BUNNYLAND_ADMIN_TOKEN is not configured"):
        asyncio.run(patch_world_admin(admin_token="secret", operations=[]))

    monkeypatch.setenv(mcp_server.ADMIN_TOKEN_ENV, "env-secret")
    with pytest.raises(RuntimeError, match="invalid MCP admin token"):
        asyncio.run(patch_world_admin(admin_token="secret", operations=[]))

    patched = asyncio.run(patch_world_admin(admin_token="env-secret", operations=[]))
    assert patched["ok"] is True


async def test_mcp_registered_tools_return_expected_payloads(monkeypatch, scenario):
    registered_tools = {}
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

        def resource(self, _uri, **_kwargs):
            def decorate(func):
                return func

            return decorate

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
        admin_token="secret",
        patch_world=patch_world,
        generate_world=generate_world,
        generation_status=generation_status,
        generate_room=generate_room,
        generate_character=generate_character,
        generate_item=generate_item,
        generate_event=generate_event,
    )
    create_bunnyland_mcp_app(generate_image=generate_image, **create_kwargs)

    characters = registered_tools["list_characters"]()
    assert characters["ok"] is True
    assert [character["name"] for character in characters["characters"]] == ["Juniper"]

    with pytest.raises(RuntimeError):  # ToolError is monkeypatched to RuntimeError above
        registered_tools["world_snapshot_admin"](admin_token="wrong")
    snapshot = registered_tools["world_snapshot_admin"](admin_token="secret")
    assert snapshot["metadata"]["seed"] == "moss"
    assert any(entity["id"] == str(scenario.character) for entity in snapshot["entities"])

    status = registered_tools["runtime_status"]()
    assert status == {
        "ok": True,
        "world_epoch": scenario.actor.epoch,
        "running": True,
        "paused": False,
        "tick_seconds": None,
        "time_scale": None,
        "game_seconds_per_tick": None,
    }

    claimed = await registered_tools["claim_character"](
        agent_id="agent-a",
        character_name="Juniper",
    )
    assert claimed["character_id"] == str(scenario.character)

    prompt = registered_tools["agent_prompt"](agent_id="agent-a")
    assert prompt["character_id"] == str(scenario.character)
    assert "You are Juniper" in prompt["prompt"]

    released = await registered_tools["release_character"](agent_id="agent-a")
    assert released["controller_kind"] == "suspended"

    patched = await registered_tools["patch_world_admin"](admin_token="secret", operations=[])
    assert patched["world_epoch"] == scenario.actor.epoch
    assert calls["patch_world"].operations == []

    generated_world = await registered_tools["generate_world_admin"](
        admin_token="secret",
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

    generation = await registered_tools["world_generation_status_admin"](
        admin_token="secret",
    )
    assert generation["world_epoch"] == scenario.actor.epoch

    room = await registered_tools["generate_room_patch_admin"](
        admin_token="secret",
        door_entity_id="door-1",
        direction="north",
        prompt="room prompt",
    )
    assert room["generated_title"] == "Generated Room"
    assert calls["generate_room"].direction == "north"

    character = await registered_tools["generate_character_patch_admin"](
        admin_token="secret",
        room_entity_id=str(scenario.room_a),
        prompt="character prompt",
    )
    assert character["generated_name"] == "Generated Character"
    assert calls["generate_character"].prompt == "character prompt"

    item = await registered_tools["generate_item_patch_admin"](
        admin_token="secret",
        container_entity_id=str(scenario.room_a),
        prompt="item prompt",
    )
    assert item["generated_name"] == "Generated Item"
    assert calls["generate_item"].container_entity_id == str(scenario.room_a)

    event = await registered_tools["generate_event_patch_admin"](
        admin_token="secret",
        room_entity_id=str(scenario.room_a),
        prompt="event prompt",
    )
    assert event["generated_kind"] == "scene"
    assert calls["generate_event"].prompt == "event prompt"

    with pytest.raises(RuntimeError):  # wrong admin token
        await registered_tools["generate_image_admin"](
            admin_token="wrong", entity_id=str(scenario.character)
        )
    image = await registered_tools["generate_image_admin"](
        admin_token="secret", entity_id=str(scenario.character), purpose="portrait"
    )
    assert image["job_id"] == "img-1"
    assert calls["generate_image"].entity_id == str(scenario.character)

    # Re-create without an image callback: the tool reports it is not configured.
    create_bunnyland_mcp_app(**create_kwargs)
    with pytest.raises(RuntimeError, match="not configured"):
        await registered_tools["generate_image_admin"](
            admin_token="secret", entity_id=str(scenario.character)
        )

    # Player-facing scene-image request (camera affordance, no admin token required).
    await registered_tools["claim_character"](agent_id="agent-a", character_name="Juniper")

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
    scene = await registered_tools["request_scene_image"](agent_id="agent-a")
    assert scene["job_id"] == "scene-1"
    assert calls["scene_image"] == str(scenario.character)

    with pytest.raises(RuntimeError, match="not controlling"):
        await registered_tools["request_scene_image"](agent_id="ghost")

    # The character has no room to illustrate: the callback returns None.
    async def scene_image_none(_character_id):
        return None

    create_bunnyland_mcp_app(scene_image=scene_image_none, **create_kwargs)
    with pytest.raises(RuntimeError, match="no room"):
        await registered_tools["request_scene_image"](agent_id="agent-a")

    # Without the callback the tool reports image generation is off.
    create_bunnyland_mcp_app(**create_kwargs)
    with pytest.raises(RuntimeError, match="not configured"):
        await registered_tools["request_scene_image"](agent_id="agent-a")


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
        admin_token="secret",
        patch_world=patch_world,
        generate_world=generate_world,
        generation_status=generation_status,
        generate_room=generate_room,
        generate_character=generate_room,
        generate_item=generate_room,
        generate_event=generate_room,
    )

    with pytest.raises(FakeToolError, match="agent is not controlling") as prompt_error:
        registered_tools["agent_prompt"](agent_id="missing")
    assert isinstance(prompt_error.value.__cause__, RuntimeError)

    with pytest.raises(FakeToolError, match="agent_id is required") as claim_error:
        await registered_tools["claim_character"](agent_id=" ")
    assert isinstance(claim_error.value.__cause__, RuntimeError)

    with pytest.raises(FakeToolError, match="agent is not controlling") as release_error:
        await registered_tools["release_character"](agent_id="missing")
    assert isinstance(release_error.value.__cause__, RuntimeError)

    with pytest.raises(FakeToolError, match="agent is not controlling") as command_error:
        await registered_tools["send_command"](
            agent_id="missing",
            command_type="move",
        )
    assert isinstance(command_error.value.__cause__, RuntimeError)

    await registered_tools["claim_character"](
        agent_id="agent-a",
        character_name="Juniper",
    )
    with pytest.raises(FakeToolError, match="'not-a-lane' is not a valid Lane") as lane_error:
        await registered_tools["send_command"](
            agent_id="agent-a",
            command_type="move",
            lane="not-a-lane",
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
    assign_mcp_controller(actor, agent_id="agent-a", character_name="Juniper")
    # Claiming clears suspension; re-add it so the LLM release path removes it (line 425).
    character.add_component(SuspendedComponent(reason="napping"))

    released = release_mcp_controller(actor, agent_id="agent-a", mode="llm")

    assert released["controller_kind"] == "llm"
    assert not character.has_component(SuspendedComponent)


async def test_mcp_event_bridge_skips_events_from_other_actors(scenario):
    other = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="Hazel", kind="character"), CharacterComponent()],
    )
    assign_mcp_controller(scenario.actor, agent_id="agent-a", character_name="Juniper")
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

        agent_events = bridge.recent_for_agent("agent-a")
        assert len(agent_events) == 1
        assert agent_events[0]["data"]["event"]["event_id"] == "own-move"
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
        bridge.unsubscribe("bunnyland://agents/none/events", first)
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

        def get_context(self):
            if get_context is None:
                raise LookupError("no context")
            return get_context()

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


async def test_mcp_admin_tools_wrap_generator_failures_and_definition_tools(
    monkeypatch, scenario
):
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
    _install_fake_fastmcp(
        monkeypatch, registered_tools=registered_tools, low_server=low_server
    )

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

    monkeypatch.setenv(mcp_server.ADMIN_TOKEN_ENV, "secret")
    create_bunnyland_mcp_app(
        actor=scenario.actor,
        meta=WorldMeta(seed="moss"),
        loop=None,
        admin_token="secret",
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
        ("patch_world_admin", {"operations": []}),
        ("generate_world_admin", {}),
        ("generate_room_patch_admin", {"door_entity_id": "door-1"}),
        ("generate_character_patch_admin", {"room_entity_id": str(scenario.room_a)}),
        ("generate_item_patch_admin", {"container_entity_id": str(scenario.room_a)}),
        ("generate_event_patch_admin", {"room_entity_id": str(scenario.room_a)}),
        ("generate_image_admin", {"entity_id": str(scenario.character)}),
    ]:
        with pytest.raises(RuntimeError, match="generator unavailable"):
            await registered_tools[tool_name](admin_token="secret", **kwargs)

    # Controller-definition tools succeed and a registration failure wraps as ToolError.
    listed = registered_tools["list_controller_definitions_admin"](admin_token="secret")
    assert listed["scripts"] == ["existing"]

    script = await registered_tools["register_script_admin"](
        admin_token="secret",
        name="patrol",
        calls=[{"name": "wait", "arguments": {}}],
    )
    assert script["scripts"] == ["patrol"]

    behavior = await registered_tools["register_behavior_admin"](
        admin_token="secret",
        name="guard",
        root={"kind": "action", "ref": "wait"},
    )
    assert behavior["behaviors"] == ["guard"]

    with pytest.raises(RuntimeError):
        await registered_tools["register_script_admin"](
            admin_token="secret",
            name="bad",
            calls="not-a-list",
        )

    # An invalid behavior tree root fails validation and wraps as ToolError (1081-1082).
    with pytest.raises(RuntimeError):
        await registered_tools["register_behavior_admin"](
            admin_token="secret",
            name="bad",
            root="not-a-node",
        )

    with pytest.raises(RuntimeError, match="not controlling"):
        await registered_tools["character_commands"](agent_id="missing")


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

    monkeypatch.setenv(mcp_server.ADMIN_TOKEN_ENV, "secret")
    # register_script / register_behavior / list_controller_definitions default to None.
    create_bunnyland_mcp_app(
        actor=scenario.actor,
        meta=WorldMeta(seed="moss"),
        loop=None,
        admin_token="secret",
        patch_world=boom,
        generate_world=boom,
        generation_status=boom,
        generate_room=boom,
        generate_character=boom,
        generate_item=boom,
        generate_event=boom,
    )

    with pytest.raises(RuntimeError, match="not configured"):
        registered_tools["list_controller_definitions_admin"](admin_token="secret")
    with pytest.raises(RuntimeError, match="not configured"):
        await registered_tools["register_script_admin"](
            admin_token="secret", name="x", calls=[]
        )
    with pytest.raises(RuntimeError, match="not configured"):
        await registered_tools["register_behavior_admin"](
            admin_token="secret", name="x", root={"kind": "action", "ref": "wait"}
        )


async def test_mcp_send_command_reports_submission_rejection(monkeypatch, scenario):
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
        admin_token="secret",
        patch_world=boom,
        generate_world=boom,
        generation_status=boom,
        generate_room=boom,
        generate_character=boom,
        generate_item=boom,
        generate_event=boom,
    )

    await registered_tools["claim_character"](agent_id="agent-a", character_name="Juniper")

    # An unaffordable command under DENY is rejected synchronously (line 977 path) instead
    # of being queued.
    result = await registered_tools["send_command"](
        agent_id="agent-a",
        command_type="move",
        payload={"direction": "north"},
        cost_action=100,
        on_insufficient_points="deny",
    )

    assert result["ok"] is False
    assert result["queued"] is False
    assert result["reason"]

    # A valid move queues successfully (the accepted branch).
    queued = await registered_tools["send_command"](
        agent_id="agent-a",
        command_type="move",
        payload={"direction": "north"},
    )
    assert queued["ok"] is True
    assert queued["queued"] is True


async def test_mcp_admin_header_fallback_when_request_is_absent(monkeypatch, scenario):
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
        return SimpleNamespace(
            request_context=SimpleNamespace(request=None), session=object()
        )

    _install_fake_fastmcp(
        monkeypatch,
        registered_tools=registered_tools,
        low_server=FakeLowServer(),
        get_context=context_with_no_request,
    )

    async def boom(_request):
        raise AssertionError("unused")

    monkeypatch.delenv(mcp_server.ADMIN_TOKEN_ENV, raising=False)
    create_bunnyland_mcp_app(
        actor=scenario.actor,
        meta=WorldMeta(seed="moss"),
        loop=None,
        admin_token="secret",
        patch_world=boom,
        generate_world=boom,
        generation_status=boom,
        generate_room=boom,
        generate_character=boom,
        generate_item=boom,
        generate_event=boom,
    )

    # supplied=None forces the header fallback, whose request is None (line 600 return None);
    # with no header the configured token still rejects the call.
    with pytest.raises(RuntimeError, match="invalid MCP admin token"):
        await registered_tools["patch_world_admin"](operations=[])


async def test_mcp_streamable_client_claims_plays_receives_events_and_releases(scenario):
    import uvicorn
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client
    from mcp.types import ResourceUpdatedNotification, ServerNotification

    plugins = select(bunnyland_plugins(), [MCP, WORLDGEN])
    app = create_app(scenario.actor, plugins=plugins, admin_token="secret")
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


def _capture_mcp_tools(
    monkeypatch, actor, *, admin_token: str = "secret", loop=None, request_headers=None
) -> dict:
    """Build the MCP app with a fake FastMCP and return its registered tool closures.

    ``request_headers`` simulates the headers an authenticating proxy attaches to the
    streamable-HTTP request the tools run under (e.g. the injected admin token); when None,
    ``get_context()`` exposes no request, matching a direct/argument-only caller."""

    registered_tools: dict = {}

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
            return lambda func: func

        def get_context(self):
            if request_headers is None:
                return SimpleNamespace(session=object())
            return SimpleNamespace(
                session=object(),
                request_context=SimpleNamespace(
                    request=SimpleNamespace(headers=request_headers)
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
        admin_token=admin_token,
        loop=loop,
    )
    return registered_tools


def test_runtime_status_reports_tick_cadence(monkeypatch, scenario):
    loop = SimpleNamespace(
        running=True, paused=False, tick_seconds=2.0, time_scale=1800.0
    )
    tools = _capture_mcp_tools(monkeypatch, scenario.actor, loop=loop)

    status = tools["runtime_status"]()
    assert status["running"] is True
    assert status["tick_seconds"] == 2.0
    assert status["time_scale"] == 1800.0
    assert status["game_seconds_per_tick"] == 3600.0

    # No loop -> cadence fields are null rather than missing.
    no_loop = _capture_mcp_tools(monkeypatch, scenario.actor)["runtime_status"]()
    assert no_loop["tick_seconds"] is None
    assert no_loop["game_seconds_per_tick"] is None


def test_send_command_and_queue_report_resolves_at_epoch(monkeypatch, scenario):
    loop = SimpleNamespace(
        running=True, paused=False, tick_seconds=2.0, time_scale=1800.0
    )
    tools = _capture_mcp_tools(monkeypatch, scenario.actor, loop=loop)
    assign_mcp_controller(scenario.actor, agent_id="a", character_name="Juniper")

    expected = scenario.actor.epoch + 3600  # tick_seconds * time_scale
    queued = asyncio.run(
        tools["send_command"](
            agent_id="a", command_type="move", payload={"direction": "north"}
        )
    )
    assert queued["resolves_at_epoch"] == expected

    pending = tools["character_commands"](agent_id="a")
    assert pending["commands"][0]["resolves_at_epoch"] == expected

    # With no loop attached, the estimate is null rather than wrong.
    no_loop = _capture_mcp_tools(monkeypatch, scenario.actor, loop=None)
    queued_no_loop = asyncio.run(
        no_loop["send_command"](
            agent_id="a", command_type="move", payload={"direction": "north"}
        )
    )
    assert queued_no_loop["resolves_at_epoch"] is None


def test_character_view_exposes_actions_and_resolved_target_ids(monkeypatch, scenario):
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
    assign_mcp_controller(scenario.actor, agent_id="a", character_name="Juniper")

    view = tools["character_view"](agent_id="a")
    assert view["character_name"] == "Juniper"
    # Progressive disclosure: the full action catalogue is omitted here.
    assert "actions" not in view
    assert view["action_count"] >= 1
    assert "search_actions" in view["actions_hint"]
    # The portable item still resolves to a concrete entity id the agent can target.
    reachable_ids = {target["id"] for target in view["target_groups"]["reachableItems"]}
    assert str(bun.id) in reachable_ids
    exit_ids = {target["id"] for target in view["target_groups"]["exits"]}
    assert str(scenario.room_b) in exit_ids

    with pytest.raises(RuntimeError, match="not controlling"):
        tools["character_view"](agent_id="missing")


def test_examine_inspects_perceivable_entity_and_self(monkeypatch, scenario):
    from bunnyland.core import ContainmentMode, Contains
    from bunnyland.core.components import PortableComponent
    from bunnyland.mechanics.consumables import FoodComponent

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
    assign_mcp_controller(scenario.actor, agent_id="a", character_name="Juniper")

    # Examining a perceivable item exposes its component values.
    item = tools["examine"](agent_id="a", entity_id=str(bun.id))
    assert item["is_self"] is False
    assert item["name"] == "steamed bun"
    assert item["details"]["food"]["satiety"] == 10.0
    assert "portable" in item["details"]
    assert item["points"] is None

    # Examining yourself (default target) adds points + the is_self flag.
    me = tools["examine"](agent_id="a")
    assert me["is_self"] is True
    assert me["name"] == "Juniper"
    assert me["points"]["action"] == 5.0

    # An entity the character cannot perceive (an adjacent room) is rejected.
    with pytest.raises(RuntimeError, match="not perceivable"):
        tools["examine"](agent_id="a", entity_id=str(scenario.room_b))


def test_serialize_examine_self_needs_and_targets(scenario):
    from bunnyland.core import (
        ActionPointsComponent,
        CharacterComponent,
        ContainmentMode,
        Contains,
        FocusPointsComponent,
    )
    from bunnyland.core.components import AffectComponent, DoorComponent, SleepingComponent
    from bunnyland.mechanics.needs import HungerComponent
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
    sleeper_view = serialize_examine(scenario.actor, str(me.id), str(sleeper.id))
    assert sleeper_view.is_self is False
    assert "asleep" in sleeper_view.details["condition"]
    assert "hunger" not in sleeper_view.details  # private state stays hidden

    door = spawn_entity(world, [IdentityComponent(name="hatch", kind="door"), DoorComponent()])
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), door.id)
    door_view = serialize_examine(scenario.actor, str(me.id), str(door.id))
    assert door_view.is_self is False
    assert "door" in door_view.details

    with pytest.raises(ValueError, match="does not exist"):
        serialize_examine(scenario.actor, str(me.id), "entity_999")


def test_search_and_list_actions_tools(monkeypatch, scenario):
    tools = _capture_mcp_tools(monkeypatch, scenario.actor)

    found = tools["search_actions"](query="move")
    assert found["query"] == "move"
    assert "move" in {action["command_type"] for action in found["actions"]}
    assert found["returned"] == len(found["actions"])

    empty = tools["search_actions"](query="zzznotaverb")
    assert empty["actions"] == []
    assert empty["total_available"] == 0

    # limit caps the returned page while total_available reflects the full match count.
    capped = tools["search_actions"](query="", limit=1)
    assert capped["returned"] == 1
    assert capped["total_available"] >= 1

    # list_actions returns the whole available catalogue (>= a narrow search).
    full = tools["list_actions"]()
    assert "move" in {action["command_type"] for action in full["actions"]}
    assert full["returned"] >= found["returned"]
    assert full["returned"] == full["total_available"]


def test_search_actions_substring_vs_word_mode(monkeypatch, scenario):
    tools = _capture_mcp_tools(monkeypatch, scenario.actor)

    # "ove" is inside "move" -> substring matches, word (boundary) does not.
    substring = tools["search_actions"](query="ove", mode="substring")
    assert substring["mode"] == "substring"
    assert "move" in {action["command_type"] for action in substring["actions"]}

    word = tools["search_actions"](query="ove", mode="word")
    assert word["mode"] == "word"
    assert "move" not in {action["command_type"] for action in word["actions"]}

    # A word-start query still finds it under word mode.
    word_hit = tools["search_actions"](query="mov", mode="word")
    assert "move" in {action["command_type"] for action in word_hit["actions"]}

    with pytest.raises(RuntimeError, match="mode must be"):
        tools["search_actions"](query="move", mode="bogus")


def test_search_actions_smart_mode_uses_chroma(monkeypatch, scenario):
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

            ranked = sorted(
                zip(self.ids, self.documents, strict=False), key=score, reverse=True
            )
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

    result = tools["search_actions"](query="walk north", mode="smart", limit=3)

    assert result["query"] == "walk north"
    assert result["mode"] == "smart"
    assert result["returned"] == 3
    assert result["actions"][0]["command_type"] == "move"
    assert {"inspect", "move", "say", "take"}.issubset(set(fake_client.collection.ids))
    assert len(fake_client.collection.documents) == result["total_available"]
    action_search._SMART_ACTION_INDEX = None


def test_search_actions_smart_mode_reports_missing_chroma(monkeypatch, scenario):
    import bunnyland.server.action_search as action_search

    monkeypatch.setitem(sys.modules, "chromadb", None)
    monkeypatch.setattr(action_search, "_SMART_ACTION_INDEX", None)
    tools = _capture_mcp_tools(monkeypatch, scenario.actor)

    with pytest.raises(RuntimeError, match="smart action search requires"):
        tools["search_actions"](query="walk north", mode="smart")
    action_search._SMART_ACTION_INDEX = None


def test_world_overview_admin_tool_is_gated_and_returns_room_network(monkeypatch, scenario):
    tools = _capture_mcp_tools(monkeypatch, scenario.actor, admin_token="secret")

    with pytest.raises(RuntimeError, match="invalid MCP admin token"):
        tools["world_overview_admin"](admin_token="wrong")

    overview = tools["world_overview_admin"](admin_token="secret")
    assert overview["room_count"] == 2
    assert overview["character_count"] == 1
    titles = {room["title"] for room in overview["rooms"]}
    assert titles == {"Mosslit Burrow", "North Tunnel"}


def test_admin_tool_authorizes_via_injected_header_without_arg(monkeypatch, scenario):
    # The authenticating proxy injects X-Bunnyland-Admin-Token, so a proxied caller does not
    # pass admin_token: the tool authorizes from the header alone.
    tools = _capture_mcp_tools(
        monkeypatch,
        scenario.actor,
        admin_token="secret",
        request_headers={"X-Bunnyland-Admin-Token": "secret"},
    )

    overview = tools["world_overview_admin"]()
    assert overview["room_count"] == 2

    # A wrong injected header is still rejected.
    rejected = _capture_mcp_tools(
        monkeypatch,
        scenario.actor,
        admin_token="secret",
        request_headers={"X-Bunnyland-Admin-Token": "wrong"},
    )
    with pytest.raises(RuntimeError, match="invalid MCP admin token"):
        rejected["world_overview_admin"]()


def test_admin_tool_falls_back_to_argument_without_header(monkeypatch, scenario):
    # With no proxy-injected header, the explicit admin_token argument still authorizes.
    tools = _capture_mcp_tools(monkeypatch, scenario.actor, admin_token="secret")

    overview = tools["world_overview_admin"](admin_token="secret")
    assert overview["room_count"] == 2

    with pytest.raises(RuntimeError, match="invalid MCP admin token"):
        tools["world_overview_admin"]()


def test_room_view_and_component_schema_tools(monkeypatch, scenario):
    tools = _capture_mcp_tools(monkeypatch, scenario.actor)

    room = tools["room_view"](room_id=str(scenario.room_a))
    assert room["room"]["title"] == "Mosslit Burrow"

    with pytest.raises(RuntimeError, match="room does not exist"):
        tools["room_view"](room_id="entity_does_not_exist")

    schema = tools["component_schema"](types=["RoomComponent"])
    assert set(schema["components"]) == {"RoomComponent"}
    assert "title" in schema["components"]["RoomComponent"]["json_schema"]["properties"]
    full = tools["component_schema"]()
    assert "RoomComponent" in full["components"]
    assert len(full["components"]) > 1


def test_character_commands_reflects_queue(monkeypatch, scenario):
    tools = _capture_mcp_tools(monkeypatch, scenario.actor)
    assign_mcp_controller(scenario.actor, agent_id="a", character_name="Juniper")

    asyncio.run(
        tools["send_command"](
            agent_id="a", command_type="move", payload={"direction": "north"}
        )
    )
    pending = tools["character_commands"](agent_id="a")
    assert [command["command_type"] for command in pending["commands"]] == ["move"]


def test_send_command_returns_outcome_hint(monkeypatch, scenario):
    tools = _capture_mcp_tools(monkeypatch, scenario.actor)
    assign_mcp_controller(scenario.actor, agent_id="a", character_name="Juniper")

    queued = asyncio.run(
        tools["send_command"](
            agent_id="a", command_type="move", payload={"direction": "north"}
        )
    )
    assert queued["queued"] is True
    assert "perceived_events" in queued["note"]


def test_send_command_rejects_unknown_command_type(monkeypatch, scenario):
    tools = _capture_mcp_tools(monkeypatch, scenario.actor)
    assign_mcp_controller(scenario.actor, agent_id="a", character_name="Juniper")

    # Fail fast on a typo'd verb instead of queuing it for a tick-later rejection.
    with pytest.raises(RuntimeError, match="unknown command_type"):
        asyncio.run(tools["send_command"](agent_id="a", command_type="flibber"))

    queued = asyncio.run(
        tools["send_command"](
            agent_id="a", command_type="move", payload={"direction": "north"}
        )
    )
    assert queued["queued"] is True


def test_perceived_events_tool_reports_rejection(monkeypatch, scenario):
    tools = _capture_mcp_tools(monkeypatch, scenario.actor)
    assign_mcp_controller(scenario.actor, agent_id="a", character_name="Juniper")

    # A valid verb that the handler rejects on resolution (no exit in that direction).
    asyncio.run(
        tools["send_command"](
            agent_id="a", command_type="move", payload={"direction": "west"}
        )
    )
    asyncio.run(scenario.actor.tick(0.0))

    first = tools["perceived_events"](agent_id="a")
    assert first["ok"] is True
    rejected = [
        message["data"]["event"]
        for message in first["events"]
        if message["data"]["event_type"] == "CommandRejectedEvent"
    ]
    assert rejected and rejected[0]["command_type"] == "move"
    assert first["next_cursor"] > 0
    # The watermark advances: re-polling from it yields nothing new.
    second = tools["perceived_events"](agent_id="a", since=first["next_cursor"])
    assert second["events"] == []
    assert second["next_cursor"] == first["next_cursor"]


async def test_perceived_for_agent_scopes_and_paginates(scenario):
    from bunnyland.core.events import CommandRejectedEvent

    assign_mcp_controller(scenario.actor, agent_id="a", character_name="Juniper")
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

    first = bridge.perceived_for_agent("a", limit=1)
    assert len(first["events"]) == 1  # paginated: more remain
    assert first["next_cursor"] == 1

    rest = bridge.perceived_for_agent("a", since=first["next_cursor"])
    actor_ids = {message["data"]["event"]["actor_id"] for message in rest["events"]}
    assert actor_ids == {"someone-else"}  # only the same-room event, not room_b
    assert rest["next_cursor"] == 3

    assert bridge.perceived_for_agent("missing")["ok"] is False
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
            admin_token="secret",
            patch_world=_unused,
            generate_world=_unused,
            generation_status=_unused,
            generate_room=_unused,
            generate_character=_unused,
            generate_item=_unused,
            generate_event=_unused,
        )
