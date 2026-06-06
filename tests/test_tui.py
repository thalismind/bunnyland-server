"""Tests for the Textual terminal client: world model, backends, and the app itself."""

from __future__ import annotations

import copy

import pytest

from bunnyland.core import (
    CharacterComponent,
    IdentityComponent,
    WebControllerComponent,
    spawn_entity,
)
from bunnyland.core.world_actor import WorldActor
from bunnyland.persistence import type_registries
from bunnyland.tui.app import BunnylandTUI, TargetPicker, TextPrompt
from bunnyland.tui.backend import Backend, LocalBackend
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
    backend = LocalBackend(generator="apartment-demo", autorun=False)
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


async def _select_player(app, pilot):
    from textual.widgets import Select

    app.query_one("#player", Select).value = PLAYER
    await pilot.pause()


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


async def test_app_wait_submits_a_command():
    app = BunnylandTUI(RecordingBackend(_snapshot()))
    async with app.run_test() as pilot:
        await _select_player(app, pilot)
        wait = next(v for v in ACTION_VERBS if v.tool == "wait")
        await app._do_verb(wait)
        assert app.backend.commands[-1]["command_type"] == "wait"
        assert app.backend.commands[-1]["controller_generation"] == 2


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
