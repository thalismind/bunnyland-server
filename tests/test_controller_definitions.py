"""Tests for runtime-loadable controller definitions: specs, store, REST, and MCP."""

from __future__ import annotations

import json
import sys
from types import ModuleType, SimpleNamespace

import httpx
import pytest
from conftest import build_scenario

from bunnyland.core import spawn_entity
from bunnyland.core.controllers import ScriptedControllerComponent
from bunnyland.foundation.core_verbs.actions import ACTION_DEFINITIONS
from bunnyland.llm_agents import (
    BehaviorNodeSpec,
    BehaviorTreeSpec,
    ControllerDefinitionStore,
    ScriptSpec,
    ToolCallSpec,
    action_library_names,
    compile_behavior_tree,
    compile_script,
    condition_library_names,
    register_script_spec,
    resolve_behavior_tree,
    resolve_script,
)


def _forager_spec(name: str = "data-forager") -> BehaviorTreeSpec:
    return BehaviorTreeSpec(
        name=name,
        root=BehaviorNodeSpec(
            kind="selector",
            children=(
                BehaviorNodeSpec(
                    kind="sequence",
                    children=(
                        BehaviorNodeSpec(kind="condition", ref="has_visible_objects"),
                        BehaviorNodeSpec(kind="action", ref="take_first_item"),
                    ),
                ),
                BehaviorNodeSpec(kind="action", ref="move_first_exit"),
            ),
        ),
    )


# -- specs and compilers ------------------------------------------------------------------


def test_compile_and_register_script_spec():
    spec = ScriptSpec(
        name="spec-north",
        calls=(ToolCallSpec(name="move", arguments={"direction": "north"}),),
    )
    compiled = compile_script(spec, ACTION_DEFINITIONS)
    assert compiled == (ToolCallSpec(name="move", arguments={"direction": "north"}).to_tool_call(),)
    register_script_spec(spec, ACTION_DEFINITIONS)
    assert resolve_script("spec-north")[0].name == "move"


def test_compile_behavior_tree_happy_path_drives_decision():
    tree = compile_behavior_tree(_forager_spec("compiled-forager"))
    scenario = build_scenario()
    from bunnyland.llm_agents.behavior_tree import BehaviorTreeAgent
    from bunnyland.prompts.builder import PromptBuilder

    context = PromptBuilder(scenario.actor.world).build(scenario.character)
    # No items in the room -> falls through to move.
    assert (
        BehaviorTreeAgent(tree).decide("", context, character_id=str(scenario.character)).name
        == "move"
    )


@pytest.mark.parametrize(
    "spec, message",
    [
        (
            BehaviorTreeSpec(name="t", root=BehaviorNodeSpec(kind="condition", ref="nope")),
            "unknown condition",
        ),
        (
            BehaviorTreeSpec(name="t", root=BehaviorNodeSpec(kind="action", ref="nope")),
            "unknown action",
        ),
        (
            BehaviorTreeSpec(
                name="t",
                root=BehaviorNodeSpec(
                    kind="selector",
                    ref="oops",
                    children=(BehaviorNodeSpec(kind="action", ref="move_first_exit"),),
                ),
            ),
            "must not set 'ref'",
        ),
        (
            BehaviorTreeSpec(
                name="t",
                root=BehaviorNodeSpec(
                    kind="action",
                    ref="move_first_exit",
                    children=(BehaviorNodeSpec(kind="action", ref="move_first_exit"),),
                ),
            ),
            "must not have children",
        ),
        (
            BehaviorTreeSpec(name="t", root=BehaviorNodeSpec(kind="action")),
            "requires a 'ref'",
        ),
        (
            BehaviorTreeSpec(
                name="t",
                root=BehaviorNodeSpec(kind="action", ref="say", params={"intent": "praise"}),
            ),
            "requires a non-empty 'text'",
        ),
    ],
)
def test_compile_behavior_tree_rejects_invalid_specs(spec, message):
    with pytest.raises(ValueError, match=message):
        compile_behavior_tree(spec)


def test_say_action_compiles_with_text():
    tree = compile_behavior_tree(
        BehaviorTreeSpec(
            name="speaker",
            root=BehaviorNodeSpec(kind="action", ref="say", params={"text": "hi there"}),
        )
    )
    from bunnyland.llm_agents.behavior_tree import BehaviorTreeAgent

    # Without the say command available the action waits (returns None) rather than erroring.
    scenario = build_scenario()
    from bunnyland.prompts.builder import PromptBuilder

    context = PromptBuilder(scenario.actor.world).build(scenario.character)
    assert BehaviorTreeAgent(tree).decide("", context, character_id=str(scenario.character)) is None


def test_address_library_actions_compile_and_speak():
    from bunnyland.core import (
        CharacterComponent,
        ContainmentMode,
        Contains,
        IdentityComponent,
    )
    from bunnyland.llm_agents.behavior_tree import BehaviorTreeAgent
    from bunnyland.prompts.builder import PromptBuilder

    scenario = build_scenario()
    hazel = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="Hazel", kind="character"), CharacterComponent()],
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), hazel.id
    )
    context = PromptBuilder(scenario.actor.world).build(scenario.character)

    greeter = compile_behavior_tree(
        BehaviorTreeSpec(
            name="lib-greeter",
            root=BehaviorNodeSpec(kind="action", ref="greet_first_character"),
        )
    )
    warner = compile_behavior_tree(
        BehaviorTreeSpec(
            name="lib-warner",
            root=BehaviorNodeSpec(
                kind="action", ref="warn_first_character", params={"text": "leave now."}
            ),
        )
    )
    greet = BehaviorTreeAgent(greeter).decide("", context, character_id=str(scenario.character))
    warn = BehaviorTreeAgent(warner).decide("", context, character_id=str(scenario.character))
    assert greet.arguments["text"] == "Hazel, good to see you."
    assert warn.arguments["text"] == "Hazel, leave now."


def test_say_action_rejects_non_string_param():
    with pytest.raises(ValueError, match="must be a string"):
        compile_behavior_tree(
            BehaviorTreeSpec(
                name="bad-say",
                root=BehaviorNodeSpec(kind="action", ref="say", params={"text": "hi", "intent": 7}),
            )
        )


def test_library_names_include_builtins():
    conditions = condition_library_names()
    assert {"has_visible_objects", "has_visible_characters", "has_open_exit"} <= conditions
    assert {"take_first_item", "move_first_exit", "say"} <= action_library_names()


# -- definition store ---------------------------------------------------------------------


def test_store_persists_and_reloads(tmp_path):
    path = tmp_path / "defs.json"
    store = ControllerDefinitionStore(path, action_definitions=ACTION_DEFINITIONS)
    store.add_script(ScriptSpec(name="stored-script", calls=(ToolCallSpec(name="move"),)))
    store.add_behavior(_forager_spec("stored-forager"))
    assert store.snapshot() == {
        "scripts": ["stored-script"],
        "behaviors": ["stored-forager"],
    }
    assert path.exists()

    reloaded = ControllerDefinitionStore(path, action_definitions=ACTION_DEFINITIONS)
    assert reloaded.load() == (1, 1)
    assert resolve_script("stored-script")[0].name == "move"
    assert resolve_behavior_tree("stored-forager").name == "stored-forager"


def test_store_skips_invalid_entries_on_load(tmp_path, caplog):
    path = tmp_path / "defs.json"
    path.write_text(
        json.dumps(
            {
                "scripts": [
                    {"name": "ok", "calls": [{"name": "move"}]},
                    {"calls": "not-a-list"},  # invalid: missing name / bad calls
                ],
                "behaviors": [
                    {"name": "bad", "root": {"kind": "action", "ref": "nope"}},
                    _forager_spec("good").model_dump(mode="json"),
                ],
            }
        )
    )
    store = ControllerDefinitionStore(path, action_definitions=ACTION_DEFINITIONS)
    # one bad script and one bad behavior are skipped; the good ones register.
    assert store.load() == (1, 1)


def test_store_without_path_is_ephemeral():
    store = ControllerDefinitionStore(None, action_definitions=ACTION_DEFINITIONS)
    assert not store.persistent
    assert store.load() == (0, 0)
    store.add_script(ScriptSpec(name="ephemeral", calls=()))
    store.save()  # no-op, no path
    assert store.snapshot()["scripts"] == ["ephemeral"]


def test_store_add_behavior_rejects_invalid_spec(tmp_path):
    store = ControllerDefinitionStore(tmp_path / "defs.json", action_definitions=ACTION_DEFINITIONS)
    bad = BehaviorTreeSpec(name="x", root=BehaviorNodeSpec(kind="action", ref="nope"))
    with pytest.raises(ValueError, match="unknown action"):
        store.add_behavior(bad)
    assert store.snapshot()["behaviors"] == []


# -- dispatch end to end with a loaded scripted controller --------------------------------


async def test_dispatch_drives_a_stored_scripted_controller(tmp_path):
    from bunnyland.llm_agents import ControllerDispatch, ScriptedAgent
    from bunnyland.prompts.builder import PromptBuilder

    scenario = build_scenario()
    store = ControllerDefinitionStore(tmp_path / "defs.json", action_definitions=ACTION_DEFINITIONS)
    store.add_script(
        ScriptSpec(
            name="loaded-move",
            calls=(ToolCallSpec(name="move", arguments={"direction": "north"}),),
        )
    )
    controller = spawn_entity(
        scenario.actor.world, [ScriptedControllerComponent(script_name="loaded-move")]
    )
    scenario.actor.assign_controller(scenario.character, controller.id)

    dispatch = ControllerDispatch(
        scenario.actor, PromptBuilder(scenario.actor.world), ScriptedAgent([])
    )
    decisions = await dispatch.run_once()
    assert [d.tool for d in decisions] == ["move"]


# -- REST endpoints -----------------------------------------------------------------------


def _client(scenario, tmp_path):
    from bunnyland.server.app import create_app

    app = create_app(
        scenario.actor,
        definitions_path=str(tmp_path / "defs.json"),
        admin_token="secret",
    )
    # The /admin/* surface is gated server-side; send the injected admin secret like nginx.
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
        headers={"X-Bunnyland-Admin-Secret": "secret"},
    )


async def test_rest_lists_and_registers_definitions(tmp_path):
    scenario = build_scenario()
    async with _client(scenario, tmp_path) as client:
        listing = await client.get("/admin/controllers/definitions")
        assert listing.status_code == 200
        body = listing.json()
        assert "idle" in body["behaviors"]
        assert "wait" in body["scripts"]
        assert "take_first_item" in body["action_library"]
        assert "has_visible_objects" in body["condition_library"]

        created = await client.post(
            "/admin/controllers/scripts",
            json={
                "name": "rest-script",
                "calls": [{"name": "move", "arguments": {"direction": "north"}}],
            },
        )
        assert created.status_code == 200
        assert "rest-script" in created.json()["scripts"]
        assert created.json()["stored"]["scripts"] == ["rest-script"]

        behavior = await client.post(
            "/admin/controllers/behaviors",
            json=_forager_spec("rest-forager").model_dump(mode="json"),
        )
        assert behavior.status_code == 200
        assert "rest-forager" in behavior.json()["behaviors"]


async def test_rest_rejects_invalid_behavior(tmp_path):
    scenario = build_scenario()
    async with _client(scenario, tmp_path) as client:
        response = await client.post(
            "/admin/controllers/behaviors",
            json={"name": "broken", "root": {"kind": "action", "ref": "nope"}},
        )
    assert response.status_code == 400
    assert "unknown action" in response.json()["detail"]


async def test_rest_persists_definitions_across_app_restart(tmp_path):
    scenario = build_scenario()
    async with _client(scenario, tmp_path) as client:
        await client.post(
            "/admin/controllers/behaviors",
            json=_forager_spec("persisted-forager").model_dump(mode="json"),
        )

    # A fresh app over the same store file re-registers the saved behavior on boot.
    async with _client(build_scenario(), tmp_path) as second:
        listing = (await second.get("/admin/controllers/definitions")).json()
    assert "persisted-forager" in listing["behaviors"]
    assert listing["stored"]["behaviors"] == ["persisted-forager"]


# -- MCP tools ----------------------------------------------------------------------------


def _install_fake_mcp(monkeypatch) -> dict:
    registered: dict = {}

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
        def __init__(self, *_a, **_k):
            self._mcp_server = FakeLowServer()

        def tool(self):
            def decorate(func):
                registered[func.__name__] = func
                return func

            return decorate

        def resource(self, *_a, **_k):
            def decorate(func):
                return func

            return decorate

        def streamable_http_app(self):
            return SimpleNamespace()

    fastmcp_module = ModuleType("mcp.server.fastmcp")
    exceptions_module = ModuleType("mcp.server.fastmcp.exceptions")
    fastmcp_module.FastMCP = FakeFastMCP
    exceptions_module.ToolError = RuntimeError
    monkeypatch.setitem(sys.modules, "mcp", ModuleType("mcp"))
    monkeypatch.setitem(sys.modules, "mcp.server", ModuleType("mcp.server"))
    monkeypatch.setitem(sys.modules, "mcp.server.fastmcp", fastmcp_module)
    monkeypatch.setitem(sys.modules, "mcp.server.fastmcp.exceptions", exceptions_module)
    return registered


def _make_mcp(monkeypatch, scenario, *, with_definitions=True):
    from bunnyland.llm_agents import behavior_tree_names, script_names
    from bunnyland.mcp.server import create_bunnyland_mcp_app
    from bunnyland.persistence import WorldMeta
    from bunnyland.server.models import (
        ControllerDefinitionListResponse,
        StoredControllerDefinitions,
    )

    registered = _install_fake_mcp(monkeypatch)
    # Back the MCP tools with the same store + listing the real REST handlers use.
    store = ControllerDefinitionStore(None, action_definitions=ACTION_DEFINITIONS)

    def listing() -> ControllerDefinitionListResponse:
        return ControllerDefinitionListResponse(
            scripts=sorted(script_names()),
            behaviors=sorted(behavior_tree_names()),
            condition_library=sorted(condition_library_names()),
            action_library=sorted(action_library_names()),
            stored=StoredControllerDefinitions(**store.snapshot()),
        )

    async def register_script_cb(spec):
        store.add_script(spec)
        return listing()

    async def register_behavior_cb(spec):
        store.add_behavior(spec)
        return listing()

    kwargs = dict(
        actor=scenario.actor,
        meta=WorldMeta(seed="moss"),
        loop=SimpleNamespace(running=True, paused=False),
        admin_token="secret",
        patch_world=_noop_async,
        generate_world=_noop_async,
        generation_status=_noop_async,
        generate_room=_noop,
        generate_character=_noop,
        generate_item=_noop,
        generate_event=_noop,
    )
    if with_definitions:
        kwargs.update(
            register_script=register_script_cb,
            register_behavior=register_behavior_cb,
            list_controller_definitions=listing,
        )
    create_bunnyland_mcp_app(**kwargs)
    return registered


async def _noop_async(*_a, **_k):
    return None


def _noop(*_a, **_k):
    return None


async def test_mcp_register_and_list_definitions(monkeypatch):
    scenario = build_scenario()
    tools = _make_mcp(monkeypatch, scenario)

    listing = tools["list_controller_definitions_admin"](admin_token="secret")
    assert "idle" in listing["behaviors"]

    script = await tools["register_script_admin"](
        admin_token="secret",
        name="mcp-script",
        calls=[{"name": "move", "arguments": {"direction": "north"}}],
    )
    assert "mcp-script" in script["scripts"]
    assert script["stored"]["scripts"] == ["mcp-script"]

    behavior = await tools["register_behavior_admin"](
        admin_token="secret",
        name="mcp-forager",
        root=_forager_spec("mcp-forager").root.model_dump(mode="json"),
    )
    assert "mcp-forager" in behavior["behaviors"]


async def test_mcp_register_requires_admin_token(monkeypatch):
    scenario = build_scenario()
    tools = _make_mcp(monkeypatch, scenario)
    with pytest.raises(RuntimeError):  # ToolError patched to RuntimeError
        await tools["register_script_admin"](admin_token="wrong", name="x", calls=[])


async def test_mcp_register_reports_invalid_behavior(monkeypatch):
    scenario = build_scenario()
    tools = _make_mcp(monkeypatch, scenario)
    with pytest.raises(RuntimeError, match="unknown action"):
        await tools["register_behavior_admin"](
            admin_token="secret",
            name="broken",
            root={"kind": "action", "ref": "nope"},
        )


async def test_mcp_tools_guard_when_not_configured(monkeypatch):
    scenario = build_scenario()
    tools = _make_mcp(monkeypatch, scenario, with_definitions=False)
    with pytest.raises(RuntimeError, match="not configured"):
        tools["list_controller_definitions_admin"](admin_token="secret")
    with pytest.raises(RuntimeError, match="not configured"):
        await tools["register_script_admin"](admin_token="secret", name="x", calls=[])
    with pytest.raises(RuntimeError, match="not configured"):
        await tools["register_behavior_admin"](
            admin_token="secret", name="x", root={"kind": "selector"}
        )
