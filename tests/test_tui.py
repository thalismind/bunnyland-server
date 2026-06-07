"""Tests for the Textual terminal client: world model, backends, and the app itself."""

from __future__ import annotations

import copy
from types import SimpleNamespace

import pytest

from bunnyland.core import (
    CharacterComponent,
    IdentityComponent,
    SuspendedComponent,
    WebControllerComponent,
    parse_entity_id,
    spawn_entity,
)
from bunnyland.core.controllers import ClaimTimeoutComponent
from bunnyland.core.world_actor import WorldActor
from bunnyland.persistence import type_registries
from bunnyland.tui import app as tui_app
from bunnyland.tui.app import BunnylandTUI, TargetPicker, TextPrompt
from bunnyland.tui.backend import Backend, LocalBackend, RemoteBackend, persistent_client_id
from bunnyland.tui.model import World, entity_icon, entity_name, entity_type
from bunnyland.tui.verbs import ACTION_VERBS

PLAYER = "character:1"
MARLOW = "character:2"
APPLE = "item:1"
KEY = "item:2"
PARLOR = "room:1"
HALL = "room:2"


def _snapshot() -> dict:
    """A serialize_world-shaped snapshot: a parlor (player, Marlow, an apple) with a
    held key, a north exit to a hallway, and the player driven by controller gen 2."""
    return {
        "schema_version": 1,
        "world_epoch": 42,
        "entities": [
            {
                "id": PARLOR, "components": {"RoomComponent": {"title": "Parlor"}},
                "relationships": {
                    "Contains": [
                        {"target_id": PLAYER, "edge": {}},
                        {"target_id": MARLOW, "edge": {}},
                        {"target_id": APPLE, "edge": {}},
                    ],
                    "ExitTo": [{"target_id": HALL, "edge": {"direction": "north"}}],
                },
            },
            {"id": HALL, "components": {"RoomComponent": {"title": "Hallway"}},
             "relationships": {}},
            {
                "id": PLAYER,
                "components": {
                    "CharacterComponent": {},
                    "IdentityComponent": {"name": "Pib", "kind": "character"},
                    "ActionPointsComponent": {"current": 5, "maximum": 5},
                    "FocusPointsComponent": {"current": 3, "maximum": 3},
                    "SpriteLayer": {"layer": 30},
                },
                "relationships": {
                    "Holding": [{"target_id": KEY, "edge": {}}],
                    "ControlledBy": [{"target_id": "controller:1", "edge": {"generation": 2}}],
                },
            },
            {
                "id": MARLOW,
                "components": {
                    "CharacterComponent": {},
                    "IdentityComponent": {"name": "Marlow", "kind": "character"},
                },
                "relationships": {},
            },
            {
                "id": APPLE,
                "components": {
                    "PortableComponent": {},
                    "IdentityComponent": {"name": "an apple", "kind": "food"},
                    "SpriteLayer": {"layer": 20},
                },
                "relationships": {},
            },
            {
                "id": KEY,
                "components": {
                    "PortableComponent": {},
                    "IdentityComponent": {"name": "a brass key", "kind": "item"},
                },
                "relationships": {},
            },
        ],
    }


# ── world model ───────────────────────────────────────────────────────────────
def test_parse_normalizes_relationships_and_epoch():
    world = World.parse(_snapshot())
    assert world.epoch == 42
    assert set(world.entities) == {PARLOR, HALL, PLAYER, MARLOW, APPLE, KEY}
    # target_id is normalized to target on every edge.
    assert world.get(PARLOR)["relationships"]["Contains"][0]["target"] == PLAYER


def test_rooms_characters_and_containment():
    world = World.parse(_snapshot())
    assert {r["id"] for r in world.rooms()} == {PARLOR, HALL}
    assert [entity_name(c) for c in world.characters()] == ["Marlow", "Pib"]  # sorted
    assert world.room_of(PLAYER) == PARLOR
    assert {m["id"] for m in world.room_members(PARLOR)} == {PLAYER, MARLOW, APPLE}


def test_doors_and_carried():
    world = World.parse(_snapshot())
    doors = world.doors(PARLOR)
    assert doors == [(HALL, "north", world.get(HALL))]
    assert [e["id"] for e in world.carried(PLAYER)] == [KEY]


def test_control_and_points():
    world = World.parse(_snapshot())
    assert world.control(PLAYER) == ("controller:1", 2)
    pts = world.points(PLAYER)
    assert (pts["ap"], pts["ap_max"], pts["fp"], pts["fp_max"]) == (5, 5, 3, 3)
    assert world.control(MARLOW) is None  # no ControlledBy edge


@pytest.mark.parametrize(
    "kind, expected",
    [
        ("exits", {HALL}),
        ("roomItems", {APPLE}),
        ("inventory", {KEY}),
        ("characters", {MARLOW}),
        ("reachableItems", {APPLE, KEY}),
    ],
)
def test_target_candidates(kind, expected):
    world = World.parse(_snapshot())
    assert {t.value for t in world.target_candidates(PLAYER, kind)} == expected


def test_entity_presentation():
    world = World.parse(_snapshot())
    assert entity_type(world.get(PARLOR)) == "room"
    assert entity_type(world.get(PLAYER)) == "character"
    assert entity_type(world.get(APPLE)) == "item"
    assert entity_name(world.get(PARLOR)) == "Parlor"
    assert entity_icon(world.get(APPLE)) == "🍎"


# ── verb catalogue ────────────────────────────────────────────────────────────
def test_verb_catalogue_costs():
    by_tool = {v.tool: v for v in ACTION_VERBS}
    assert by_tool["wait"].ap == 0 and by_tool["wait"].fp == 0
    assert by_tool["say"].fp == 1
    assert by_tool["move"].target_kind == "exits" and by_tool["move"].target_key == "exit_id"
    # Every target verb names both the payload key and a candidate kind.
    for verb in ACTION_VERBS:
        assert bool(verb.target_kind) == bool(verb.target_key)


# ── web controller ────────────────────────────────────────────────────────────
def test_web_controller_registered_for_persistence():
    components, _edges = type_registries()
    assert components.get("WebControllerComponent") is WebControllerComponent


def test_assign_web_controller_reports_web_kind():
    actor = WorldActor()
    character = spawn_entity(
        actor.world, [CharacterComponent(), IdentityComponent(name="Pib", kind="character")]
    )
    controller = spawn_entity(actor.world, [WebControllerComponent()])
    generation = actor.assign_controller(character.id, controller.id)
    assert generation == 0
    assert actor._controller_kind(controller.id) == "web"


# ── local backend (host a world in-process) ───────────────────────────────────
async def test_local_backend_hosts_claims_and_submits():
    backend = LocalBackend(
        generator="apartment-demo",
        autorun=False,
        client_id="local-client",
        fallback_controller="llm",
        timeout_seconds=900,
    )
    await backend.start()
    try:
        world = World.parse(await backend.fetch_snapshot())
        assert world.rooms() and world.characters()

        player = world.characters()[0]["id"]
        control = await backend.claim(player, world)
        assert control is not None
        controller_id, _generation = control
        # The claim attaches our reusable web controller.
        assert backend.actor._controller_kind(backend._controller.id) == "web"
        assert (
            backend._controller.get_component(WebControllerComponent).client_id
            == "local-client"
        )
        claim = backend._controller.get_component(ClaimTimeoutComponent)
        assert claim.fallback_controller == "llm"
        assert claim.timeout_seconds == 900

        epoch_before = backend.actor.epoch
        ok = await backend.submit({
            "character_id": player,
            "controller_id": controller_id,
            "controller_generation": control[1],
            "command_type": "wait",
            "payload": {},
            "cost": {"action": 0, "focus": 0},
            "lane": "world",
            "on_insufficient_points": "queue",
        })
        assert ok
        await backend.actor.tick(60.0)  # process the queued command
        assert backend.actor.epoch > epoch_before  # the world advanced
        # The claimed controller is what the fresh snapshot reports.
        refreshed = World.parse(await backend.fetch_snapshot())
        assert refreshed.control(player) == (controller_id, control[1])
    finally:
        await backend.close()


async def test_local_backend_claim_unsuspends_player():
    backend = LocalBackend(generator="apartment-demo", autorun=False, client_id="local-client")
    await backend.start()
    try:
        world = World.parse(await backend.fetch_snapshot())
        player = world.characters()[0]["id"]
        character = backend.actor.world.get_entity(parse_entity_id(player))
        assert character.has_component(SuspendedComponent)

        control = await backend.claim(player, world)

        assert control is not None
        assert not character.has_component(SuspendedComponent)
    finally:
        await backend.close()


def test_persistent_client_id_reuses_config_file(tmp_path):
    path = tmp_path / "bunnyland" / "client-id"

    first = persistent_client_id(path)
    second = persistent_client_id(path)

    assert first == second
    assert path.read_text(encoding="utf-8").strip() == first


async def test_remote_backend_claims_web_controller():
    class Response:
        is_success = True
        status_code = 200
        text = ""

        def json(self):
            return {"controller_id": "controller:web", "controller_generation": 4}

    class Client:
        def __init__(self) -> None:
            self.requests: list[tuple[str, dict]] = []

        async def post(self, url: str, json: dict):
            self.requests.append((url, json))
            return Response()

    backend = RemoteBackend(
        "http://server.example",
        client_id="remote-client",
        fallback_controller="llm",
        timeout_seconds=1200,
    )
    backend._client = Client()

    control = await backend.claim(PLAYER, World.parse(_snapshot()))

    assert control == ("controller:web", 4)
    assert backend._client.requests == [
        (
            "http://server.example/world/controllers/web/claim",
            {
                "character_id": PLAYER,
                "client_id": "remote-client",
                "label": "tui",
                "fallback_controller": "llm",
                "timeout_seconds": 1200,
            },
        )
    ]


# ── the app (Textual pilot) ───────────────────────────────────────────────────
class RecordingBackend(Backend):
    """A static-snapshot backend that records submitted commands, for app tests."""

    def __init__(self, snapshot: dict) -> None:
        self.snapshot = snapshot
        self.commands: list[dict] = []
        self.label = "test"

    async def start(self) -> None: ...
    async def close(self) -> None: ...
    async def fetch_snapshot(self) -> dict:
        return copy.deepcopy(self.snapshot)

    async def submit(self, command: dict) -> bool:
        self.commands.append(command)
        return True

    async def claim(self, player_id, world):
        return world.control(player_id)


class FailingBackend(RecordingBackend):
    async def fetch_snapshot(self) -> dict:
        raise RuntimeError("snapshot failed")


async def _select_player(app, pilot):
    from textual.widgets import Select

    app.query_one("#player", Select).value = PLAYER
    await pilot.pause()


async def test_target_picker_selects_and_cancels():
    from textual.widgets import OptionList

    move = next(v for v in ACTION_VERBS if v.tool == "move")
    candidates = World.parse(_snapshot()).target_candidates(PLAYER, "exits")
    app = BunnylandTUI(RecordingBackend(_snapshot()))
    results = []

    async with app.run_test() as pilot:
        screen = TargetPicker(move, candidates)
        app.push_screen(screen, callback=results.append)
        await pilot.pause()
        screen.query_one("#picker-list", OptionList).highlighted = 0
        await pilot.press("enter")
        await pilot.pause()
        assert results[-1] == HALL

        empty_screen = TargetPicker(move, [])
        app.push_screen(empty_screen, callback=results.append)
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        assert results[-1] is None


async def test_text_prompt_submits_text_and_cancel():
    from textual.widgets import Input

    app = BunnylandTUI(RecordingBackend(_snapshot()))
    results = []

    async with app.run_test() as pilot:
        prompt = TextPrompt("Say — text")
        app.push_screen(prompt, callback=results.append)
        await pilot.pause()
        prompt.query_one("#prompt-input", Input).value = "hello"
        await pilot.press("enter")
        await pilot.pause()
        assert results[-1] == "hello"

        blank_prompt = TextPrompt("Say — text")
        app.push_screen(blank_prompt, callback=results.append)
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert results[-1] is None

        cancelled = TextPrompt("Say — text")
        app.push_screen(cancelled, callback=results.append)
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        assert results[-1] is None


async def test_app_reports_refresh_errors():
    from textual.widgets import Static

    app = BunnylandTUI(FailingBackend(_snapshot()))
    async with app.run_test():
        assert "snapshot failed" in str(app.query_one("#status", Static).render())


async def test_app_renders_room_and_actions():
    from textual.widgets import OptionList, Static

    text = lambda wid: str(app.query_one(wid, Static).render())  # noqa: E731
    app = BunnylandTUI(RecordingBackend(_snapshot()))
    async with app.run_test() as pilot:
        await _select_player(app, pilot)
        assert "Parlor" in text("#room-title")
        members = app.query_one("#members", OptionList)
        # The held key is inventory, not a room member, so only the room's contents show.
        assert {o.id for o in members.options} == {PLAYER, MARLOW, APPLE}
        doors = app.query_one("#doors", OptionList)
        assert [o.id for o in doors.options] == [f"door:{HALL}"]
        assert "5/5 AP" in text("#points")


async def test_app_rendering_restores_highlight_and_handles_missing_room():
    from textual.widgets import OptionList, Static

    app = BunnylandTUI(RecordingBackend(_snapshot()))
    async with app.run_test() as pilot:
        await _select_player(app, pilot)
        app.selected_id = MARLOW
        app._render_room()
        members = app.query_one("#members", OptionList)
        assert members.get_option_at_index(members.highlighted).id == MARLOW

        app.selected_id = "missing"
        app._render_room()
        assert members.option_count == 3

        app.view_room_id = "room:missing"
        app.follow = False
        app.player_id = ""
        app._render_room()
        assert str(app.query_one("#room-title", Static).render()) == "No room"


async def test_app_door_selection_spectating_and_follow():
    from textual.widgets import Static

    app = BunnylandTUI(RecordingBackend(_snapshot()))
    async with app.run_test() as pilot:
        await _select_player(app, pilot)
        app._door_selected(SimpleNamespace(option=SimpleNamespace(id=f"door:{HALL}")))
        assert app.view_room_id == HALL
        assert not app.follow
        assert "spectating" in str(app.query_one("#room-title", Static).render())

        app.action_follow()
        assert app.follow
        assert app.view_room_id == PARLOR
        assert "spectating" not in str(app.query_one("#room-title", Static).render())


async def test_app_member_and_verb_selection_handlers():
    app = BunnylandTUI(RecordingBackend(_snapshot()))
    async with app.run_test() as pilot:
        await _select_player(app, pilot)

        app._member_selected(SimpleNamespace(option=SimpleNamespace(id=APPLE)))
        assert app.selected_id == APPLE

        await app._verb_selected(SimpleNamespace(option=SimpleNamespace(id="wait")))
        assert app.backend.commands[-1]["command_type"] == "wait"

        await app._verb_selected(SimpleNamespace(option=SimpleNamespace(id="missing")))
        assert app.backend.commands[-1]["command_type"] == "wait"


async def test_app_wait_submits_a_command():
    app = BunnylandTUI(RecordingBackend(_snapshot()))
    async with app.run_test() as pilot:
        await _select_player(app, pilot)
        wait = next(v for v in ACTION_VERBS if v.tool == "wait")
        await app._do_verb(wait)
        assert app.backend.commands[-1]["command_type"] == "wait"
        assert app.backend.commands[-1]["controller_generation"] == 2


async def test_app_refresh_action_resyncs_existing_player():
    from textual.widgets import Select

    app = BunnylandTUI(RecordingBackend(_snapshot()))
    async with app.run_test() as pilot:
        await _select_player(app, pilot)
        await app.action_refresh()
        assert app.query_one("#player", Select).value == PLAYER


async def test_app_refresh_preserves_valid_room_view_and_noops_same_player():
    from textual.widgets import Select

    app = BunnylandTUI(RecordingBackend(_snapshot()))
    async with app.run_test():
        app.world = World.parse(_snapshot())
        app.player_id = PLAYER
        app._player_choice_ids = [MARLOW]
        app._sync_players()
        assert app.query_one("#player", Select).value == PLAYER

        app.view_room_id = HALL
        app.follow = False
        await app.refresh_world()
        assert app.view_room_id == HALL

        app.selected_id = APPLE
        await app._player_changed(SimpleNamespace(value=PLAYER))
        assert app.selected_id == APPLE


async def test_app_move_uses_target_picker(monkeypatch):
    app = BunnylandTUI(RecordingBackend(_snapshot()))
    async with app.run_test() as pilot:
        await _select_player(app, pilot)

        async def fake_pick(screen):
            assert isinstance(screen, TargetPicker)
            return HALL  # choose the north exit

        monkeypatch.setattr(app, "push_screen_wait", fake_pick)
        move = next(v for v in ACTION_VERBS if v.tool == "move")
        await app._do_verb(move)
        cmd = app.backend.commands[-1]
        assert cmd["command_type"] == "move"
        assert cmd["payload"] == {"exit_id": HALL}


async def test_app_target_and_prompt_cancellations_submit_nothing(monkeypatch):
    app = BunnylandTUI(RecordingBackend(_snapshot()))
    async with app.run_test() as pilot:
        await _select_player(app, pilot)
        choices = iter([MARLOW, None])

        async def fake_pick(screen):
            return next(choices)

        monkeypatch.setattr(app, "push_screen_wait", fake_pick)
        tell = next(v for v in ACTION_VERBS if v.tool == "tell")
        await app._do_verb(tell)
        assert app.backend.commands == []


async def test_app_verb_without_player_or_control_submits_nothing():
    app = BunnylandTUI(RecordingBackend(_snapshot()))
    async with app.run_test():
        wait = next(v for v in ACTION_VERBS if v.tool == "wait")
        await app._do_verb(wait)
        assert app.backend.commands == []

        app.player_id = MARLOW
        app.control = None
        await app._do_verb(wait)
        assert app.backend.commands == []


async def test_app_say_collects_text(monkeypatch):
    app = BunnylandTUI(RecordingBackend(_snapshot()))
    async with app.run_test() as pilot:
        await _select_player(app, pilot)

        async def fake_prompt(screen):
            assert isinstance(screen, TextPrompt)
            return "hello terminal"

        monkeypatch.setattr(app, "push_screen_wait", fake_prompt)
        say = next(v for v in ACTION_VERBS if v.tool == "say")
        await app._do_verb(say)
        assert app.backend.commands[-1]["payload"] == {"text": "hello terminal"}


async def test_app_cancelled_target_submits_nothing(monkeypatch):
    app = BunnylandTUI(RecordingBackend(_snapshot()))
    async with app.run_test() as pilot:
        await _select_player(app, pilot)

        async def fake_pick(screen):
            return None  # user pressed escape

        monkeypatch.setattr(app, "push_screen_wait", fake_pick)
        await app._do_verb(next(v for v in ACTION_VERBS if v.tool == "move"))
        assert app.backend.commands == []


async def test_app_disables_unaffordable_verbs():
    from textual.widgets import OptionList

    snapshot = _snapshot()
    # Drain the player's points so nothing is affordable except free verbs.
    for entity in snapshot["entities"]:
        if entity["id"] == PLAYER:
            entity["components"]["ActionPointsComponent"]["current"] = 0
            entity["components"]["FocusPointsComponent"]["current"] = 0

    app = BunnylandTUI(RecordingBackend(snapshot))
    async with app.run_test() as pilot:
        await _select_player(app, pilot)
        verbs = {o.id: o for o in app.query_one("#verbs", OptionList).options}
        assert verbs["move"].disabled  # costs 1 AP
        assert verbs["say"].disabled   # costs 1 AP + 1 FP
        assert not verbs["wait"].disabled  # free


async def test_app_clears_missing_player_after_refresh():
    snapshot = _snapshot()
    snapshot["entities"] = [entity for entity in snapshot["entities"] if entity["id"] != PLAYER]
    app = BunnylandTUI(RecordingBackend(snapshot))

    async with app.run_test():
        app.player_id = PLAYER
        app.control = ("controller:1", 2)
        await app.refresh_world()
        assert app.player_id == ""
        assert app.control is None


# ── TUI CLI wiring ────────────────────────────────────────────────────────────
def test_main_runs_remote_backend(monkeypatch):
    backends = []
    runs = []

    class BackendStub:
        def __init__(self, server, *, fallback_controller=None, timeout_seconds=None):
            self.server = server
            self.fallback_controller = fallback_controller
            self.timeout_seconds = timeout_seconds
            backends.append(self)

    class AppStub:
        def __init__(self, backend):
            self.backend = backend

        def run(self):
            runs.append(self.backend)

    monkeypatch.setattr(tui_app, "RemoteBackend", BackendStub)
    monkeypatch.setattr(tui_app, "BunnylandTUI", AppStub)

    assert tui_app.main([
        "--server", "http://example.test",
        "--claim-fallback", "llm",
        "--claim-timeout-minutes", "10",
    ]) == 0
    assert runs == backends
    assert backends[0].server == "http://example.test"
    assert backends[0].fallback_controller == "llm"
    assert backends[0].timeout_seconds == 600


def test_main_runs_local_backend(monkeypatch):
    backends = []

    class BackendStub:
        def __init__(
            self, *, seed=None, generator=None, fallback_controller=None, timeout_seconds=None
        ):
            self.seed = seed
            self.generator = generator
            self.fallback_controller = fallback_controller
            self.timeout_seconds = timeout_seconds
            backends.append(self)

    class AppStub:
        def __init__(self, backend):
            self.backend = backend

        def run(self): ...

    monkeypatch.setattr(tui_app, "LocalBackend", BackendStub)
    monkeypatch.setattr(tui_app, "BunnylandTUI", AppStub)

    assert tui_app.main([
        "--seed", "test seed",
        "--generator", "empty",
        "--claim-fallback", "suspend",
    ]) == 0
    assert backends[0].seed == "test seed"
    assert backends[0].generator == "empty"
    assert backends[0].fallback_controller == "suspend"
    assert backends[0].timeout_seconds is None
