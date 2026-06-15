"""Tests for the Textual terminal client: world model, backends, and the app itself."""

from __future__ import annotations

import copy
import sys
from types import SimpleNamespace

import pytest

from bunnyland.core import (
    CharacterComponent,
    CommandCost,
    IdentityComponent,
    Lane,
    OnInsufficientPoints,
    SuspendedComponent,
    WebControllerComponent,
    build_submitted_command,
    parse_entity_id,
    spawn_entity,
)
from bunnyland.core.controllers import ClaimTimeoutComponent
from bunnyland.core.world_actor import WorldActor
from bunnyland.persistence import type_registries
from bunnyland.tui import app as tui_app
from bunnyland.tui.app import BunnylandTUI, TargetPicker, TextPrompt
from bunnyland.tui.backend import Backend, LocalBackend, RemoteBackend, persistent_client_id
from bunnyland.tui.events import EventNarrator
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


def _client_view() -> dict:
    return {
        "schema_version": 1,
        "world_epoch": 43,
        "character_id": PLAYER,
        "character_name": "Pib",
        "can_perceive": True,
        "room": {
            "id": PARLOR,
            "title": "Parlor",
            "entities": [
                {
                    "id": MARLOW,
                    "name": "Marlow",
                    "kind": "character",
                    "is_character": True,
                    "contents": [],
                },
                {
                    "id": APPLE,
                    "name": "an apple",
                    "kind": "item",
                    "is_character": False,
                    "contents": [],
                },
            ],
            "exits": [
                {
                    "id": HALL,
                    "direction": "north",
                    "label": "north: Hallway",
                    "locked": False,
                }
            ],
        },
        "inventory": [{"id": KEY, "label": "a brass key", "kind": "item"}],
        "points": {"action": 4, "action_max": 5, "focus": 2, "focus_max": 3},
        "controller": {"controller_id": "controller:1", "generation": 3},
        "target_groups": {
            "exits": [{"id": HALL, "label": "north: Hallway", "kind": "exit"}],
            "roomItems": [{"id": APPLE, "label": "an apple", "kind": "item"}],
            "inventory": [{"id": KEY, "label": "a brass key", "kind": "item"}],
            "characters": [{"id": MARLOW, "label": "Marlow", "kind": "character"}],
            "reachableItems": [
                {"id": APPLE, "label": "an apple", "kind": "item"},
                {"id": KEY, "label": "a brass key", "kind": "item"},
            ],
        },
        "actions": [_projected_action()],
    }


def _projected_action(**overrides) -> dict:
    action = {
        "command_type": "inspect",
        "tool_name": "inspect",
        "title": "Inspect",
        "description": "Inspect something nearby.",
        "lane": "world",
        "cost": {"action": 1, "focus": 0},
        "arguments": [
            {
                "key": "target_id",
                "title": "target",
                "kind": "entity",
                "required": True,
                "target_group": "reachableItems",
            }
        ],
    }
    action.update(overrides)
    return action


def _queued_response(*commands: dict) -> dict:
    return {
        "ok": True,
        "schema_version": 1,
        "world_epoch": 42,
        "character_id": PLAYER,
        "commands": list(commands),
    }


def _queued_command(**overrides) -> dict:
    command = {
        "command_id": "cmd-1",
        "character_id": PLAYER,
        "command_type": "say",
        "payload": {"text": "next"},
        "cost": {"action": 1, "focus": 1},
        "lane": "focus",
        "submitted_at_epoch": 41,
        "expires_at_epoch": None,
    }
    command.update(overrides)
    return command


def _event(event_id: str | None, event_type="CustomEvent", **fields) -> dict:
    return {
        "type": "event",
        "data": {
            "event_type": event_type,
            "event": {
                "event_id": event_id,
                "note": event_id,
                **fields,
            },
        },
    }


def test_event_narrator_renders_arrival_room_for_own_move():
    world = World.parse(_snapshot())
    narrator = EventNarrator()
    shown = narrator.drain_events(
        [
            _event(
                "m1",
                event_type="ActorMovedEvent",
                visibility="system",
                actor_id=PLAYER,
                from_room_id=PARLOR,
                to_room_id=HALL,
                arrival_summary="Hallway\nHere: Pib.\nExits: south.",
            ),
            _event(
                "m2",
                event_type="ActorMovedEvent",
                visibility="system",
                actor_id=MARLOW,
                from_room_id=PARLOR,
                to_room_id=HALL,
                arrival_summary="Hallway\nHere: Marlow.\nExits: south.",
            ),
        ],
        player_id=PLAYER,
        room_of=world.room_of,
        name_for=lambda entity_id: entity_name(world.get(entity_id)),
    )

    assert [item.plain for item in shown] == ["Hallway\nHere: Pib.\nExits: south."]


# ── lazy package exports ──────────────────────────────────────────────────────
def test_tui_package_lazily_exports_app_symbols():
    import bunnyland.tui as tui

    # The Textual app is imported lazily; the package exposes it on access so the REPL can
    # reuse the textual-free backend/model without importing Textual.
    assert tui.main is tui_app.main
    assert tui.BunnylandTUI is BunnylandTUI
    unknown = "does_not_exist"
    with pytest.raises(AttributeError):
        getattr(tui, unknown)


# ── world model ───────────────────────────────────────────────────────────────
def test_parse_normalizes_relationships_and_epoch():
    snapshot = _snapshot()
    snapshot["queued_commands"] = [
        _queued_command(),
        _queued_command(command_id="cmd-2", character_id=MARLOW),
    ]
    world = World.parse(snapshot)
    assert world.epoch == 42
    assert set(world.entities) == {PARLOR, HALL, PLAYER, MARLOW, APPLE, KEY}
    # target_id is normalized to target on every edge.
    assert world.get(PARLOR)["relationships"]["Contains"][0]["target"] == PLAYER
    assert [command["command_id"] for command in world.queued_for(PLAYER)] == ["cmd-1"]
    assert world.queued_for("") == []


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


def test_parse_client_view_supports_filtered_structured_surface():
    world = World.parse(_client_view())

    assert world.epoch == 43
    assert world.room_of(PLAYER) == PARLOR
    assert entity_name(world.get(PARLOR)) == "Parlor"
    assert world.control(PLAYER) == ("controller:1", 3)
    assert world.points(PLAYER) == {
        "has": True,
        "ap": 4,
        "ap_max": 5,
        "fp": 2,
        "fp_max": 3,
    }
    assert {target.value for target in world.target_candidates(PLAYER, "exits")} == {HALL}
    assert {target.value for target in world.target_candidates(PLAYER, "roomItems")} == {APPLE}
    assert {target.value for target in world.target_candidates(PLAYER, "inventory")} == {KEY}
    assert [action["command_type"] for action in world.actions] == ["inspect"]


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


def test_world_model_empty_and_missing_lookup_fallbacks():
    world = World.parse(None)

    assert world.epoch == 0
    assert world.first_room_id() is None
    assert world.room_of(None) is None
    assert world.room_members("missing") == []
    assert world.doors("missing") == []
    assert world.carried("missing") == []
    assert world.target_candidates("missing", "unknown") == []


def test_entity_presentation_fallbacks():
    room = {"id": "room:missing-title", "components": {"RoomComponent": {}}, "relationships": {}}
    door = {"id": "door:1", "components": {"DoorComponent": {}}, "relationships": {}}
    container = {
        "id": "container:1",
        "components": {"ContainerComponent": {}},
        "relationships": {},
    }
    custom = {
        "id": "custom:1",
        "components": {
            "IdentityComponent": {"name": "", "kind": "mystery"},
            "EditorDisplayComponent": {"emoji": "?" },
        },
        "relationships": {},
    }
    nameless = {"id": "nameless-entity-123456789", "components": {}, "relationships": {}}

    assert entity_type(door) == "door"
    assert entity_type(container) == "container"
    assert entity_type(nameless) == "other"
    assert entity_icon(custom) == "?"
    assert entity_icon(nameless) == "⬡"
    assert entity_name(None) == "?"
    assert entity_name(room) == "room:missing-title"
    assert entity_name(nameless) == "nameless-entity-"


# ── verb catalogue ────────────────────────────────────────────────────────────
def test_verb_catalogue_costs():
    by_tool = {v.tool: v for v in ACTION_VERBS}
    assert by_tool["wait"].ap == 0 and by_tool["wait"].fp == 0
    assert by_tool["say"].fp == 1
    assert by_tool["move"].target_kind == "exits" and by_tool["move"].target_key == "exit_id"
    # Every target verb names both the payload key and a candidate kind.
    for verb in ACTION_VERBS:
        assert bool(verb.target_kind) == bool(verb.target_key)


def test_queued_command_label_formats_unknown_free_command():
    label = tui_app._queued_command_label(
        {
            "command_type": "custom-command",
            "payload": {"empty": "", "target_id": APPLE},
            "cost": {},
        }
    )

    assert label == "custom command — free · target_id: item:1"


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

        await backend.actor.submit(
            build_submitted_command(
                character_id=player,
                controller_id=controller_id,
                controller_generation=control[1],
                command_type="say",
                payload={"text": "later"},
                cost=CommandCost(action=1, focus=1),
                lane=Lane.FOCUS,
                on_insufficient_points=OnInsufficientPoints.QUEUE,
                submitted_at_epoch=backend.actor.epoch,
            )
        )
        queued = await backend.fetch_queued_commands(player)
        assert queued["character_id"] == player
        assert queued["commands"][-1]["command_type"] == "say"

        character_projection = await backend.fetch_character_projection(player)
        assert character_projection["character_id"] == player
        assert character_projection["actions"]
        room_projection = await backend.fetch_room_projection(refreshed.room_of(player))
        assert room_projection["room"]["id"] == refreshed.room_of(player)
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


def test_persistent_client_id_recovers_from_invalid_or_unreadable_config(tmp_path):
    invalid = tmp_path / "invalid-client-id"
    invalid.write_text("not-a-uuid\n", encoding="utf-8")
    recovered = persistent_client_id(invalid)
    assert recovered != "not-a-uuid"

    class UnreadablePath:
        parent = tmp_path

        def exists(self):
            return True

        def read_text(self, *, encoding):
            raise OSError("cannot read")

        def write_text(self, text, *, encoding):
            self.text = text

    assert persistent_client_id(UnreadablePath())


def test_persistent_client_id_tolerates_unwritable_config(tmp_path):
    class UnwritablePath:
        parent = tmp_path

        def exists(self):
            return False

        def write_text(self, text, *, encoding):
            raise OSError("cannot write")

    assert persistent_client_id(UnwritablePath())


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


async def test_remote_backend_failed_claim_returns_none():
    class Response:
        is_success = False
        status_code = 503
        text = "nope"

    class Client:
        async def post(self, url: str, json: dict):
            return Response()

    backend = RemoteBackend("http://server.example", client_id="remote-client")
    backend._client = Client()

    assert await backend.claim(PLAYER, World.parse(_snapshot())) is None


async def test_remote_backend_recent_events_reads_endpoint():
    class Response:
        def raise_for_status(self) -> None: ...

        def json(self) -> dict:
            return {"events": [{"type": "event", "data": {"event_type": "PingEvent"}}]}

    class Client:
        def __init__(self) -> None:
            self.urls: list[str] = []

        async def get(self, url: str):
            self.urls.append(url)
            return Response()

    backend = RemoteBackend("http://server.example")
    backend._client = Client()

    events = await backend.recent_events()

    assert events == [{"type": "event", "data": {"event_type": "PingEvent"}}]
    assert backend._client.urls == ["http://server.example/world/events/recent"]


async def test_backend_recent_events_defaults_to_empty():
    assert await RecordingBackend(_snapshot()).recent_events() == []


async def test_local_backend_records_recent_events():
    backend = LocalBackend(generator="apartment-demo", autorun=False, client_id="local-client")
    await backend.start()
    try:
        events = await backend.recent_events()
        assert isinstance(events, list)  # world generation may have recorded events
    finally:
        await backend.close()


async def test_local_backend_rejects_unknown_generator():
    backend = LocalBackend(generator="missing-generator", autorun=False)

    with pytest.raises(SystemExit, match="unknown generator 'missing-generator'"):
        await backend.start()


async def test_remote_backend_http_methods_use_async_client(monkeypatch):
    class Response:
        def __init__(self, *, is_success=True, payload=None):
            self.is_success = is_success
            self.payload = payload or {}
            self.raised = False

        def raise_for_status(self):
            self.raised = True

        def json(self):
            return self.payload

    class Client:
        def __init__(self, *, timeout):
            self.timeout = timeout
            self.closed = False
            self.requests: list[tuple[str, str, dict | None]] = []

        async def get(self, url: str):
            self.requests.append(("GET", url, None))
            return Response(payload={"world_epoch": 7})

        async def post(self, url: str, json: dict):
            self.requests.append(("POST", url, json))
            return Response(is_success=False)

        async def aclose(self):
            self.closed = True

    clients = []

    def async_client(*, timeout):
        client = Client(timeout=timeout)
        clients.append(client)
        return client

    monkeypatch.setitem(sys.modules, "httpx", SimpleNamespace(AsyncClient=async_client))
    backend = RemoteBackend("http://server.example/")

    await backend.start()
    snapshot = await backend.fetch_snapshot()
    character = await backend.fetch_character_projection(PLAYER)
    room = await backend.fetch_room_projection(PARLOR)
    queued = await backend.fetch_queued_commands(PLAYER)
    submitted = await backend.submit({"command_type": "wait"})
    await backend.close()

    assert snapshot == {"world_epoch": 7}
    assert character == {"world_epoch": 7}
    assert room == {"world_epoch": 7}
    assert queued == {"world_epoch": 7}
    assert submitted is False
    assert clients[0].closed is True
    assert clients[0].requests == [
        ("GET", "http://server.example/world/snapshot", None),
        ("GET", f"http://server.example/world/character/{PLAYER}", None),
        ("GET", f"http://server.example/world/room/{PARLOR}", None),
        ("GET", f"http://server.example/world/character/{PLAYER}/commands", None),
        ("POST", "http://server.example/world/commands", {"command_type": "wait"}),
    ]


async def test_remote_backend_close_without_client_is_noop():
    backend = RemoteBackend("http://server.example")

    await backend.close()

    assert backend._client is None


async def test_backend_default_queued_commands_response():
    class MinimalBackend(Backend):
        label = "minimal"

        async def start(self) -> None: ...
        async def close(self) -> None: ...
        async def fetch_snapshot(self) -> dict:
            return {}

        async def submit(self, command: dict) -> bool:
            return True

        async def claim(self, player_id: str, world: World):
            return None

    assert await MinimalBackend().fetch_queued_commands(PLAYER) == {
        "ok": True,
        "schema_version": 1,
        "world_epoch": 0,
        "character_id": PLAYER,
        "commands": [],
    }


# ── the app (Textual pilot) ───────────────────────────────────────────────────
class RecordingBackend(Backend):
    """A static-snapshot backend that records submitted commands, for app tests."""

    def __init__(
        self,
        snapshot: dict,
        queued_response: dict | None = None,
        events: list[dict] | None = None,
        character_projection: dict | None = None,
    ) -> None:
        self.snapshot = snapshot
        self.queued_response = queued_response or _queued_response()
        self.events = events or []
        self.character_projection = character_projection
        self.queued_requests: list[str] = []
        self.commands: list[dict] = []
        self.label = "test"

    async def start(self) -> None: ...
    async def close(self) -> None: ...
    async def fetch_snapshot(self) -> dict:
        return copy.deepcopy(self.snapshot)

    async def fetch_queued_commands(self, character_id: str) -> dict:
        self.queued_requests.append(character_id)
        return copy.deepcopy(self.queued_response)

    async def fetch_character_projection(self, character_id: str) -> dict | None:
        if self.character_projection is None:
            return None
        return copy.deepcopy(self.character_projection)

    async def submit(self, command: dict) -> bool:
        self.commands.append(command)
        return True

    async def recent_events(self) -> list[dict]:
        return copy.deepcopy(self.events)

    async def claim(self, player_id, world):
        return world.control(player_id)


class FailingQueueBackend(RecordingBackend):
    async def fetch_queued_commands(self, character_id: str) -> dict:
        self.queued_requests.append(character_id)
        raise RuntimeError("queue failed")


class FlakyBackend(RecordingBackend):
    def __init__(self, snapshot: dict) -> None:
        super().__init__(snapshot)
        self.fail = True

    async def fetch_snapshot(self) -> dict:
        if self.fail:
            raise RuntimeError("snapshot failed")
        return await super().fetch_snapshot()


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
    from textual.widgets import OptionList, Static

    backend = FlakyBackend(_snapshot())
    app = BunnylandTUI(backend)
    async with app.run_test():
        assert "snapshot failed" in str(app.query_one("#status", Static).render())
        activity = app.query_one("#activity", OptionList)
        assert activity.option_count == 1
        assert "snapshot failed" in str(activity.get_option_at_index(0).prompt)

        await app.refresh_world()
        assert activity.option_count == 1

        backend.fail = False
        await app.refresh_world()
        assert activity.option_count == 2
        assert "reconnected" in str(activity.get_option_at_index(1).prompt)


async def test_app_renders_room_and_actions():
    from textual.widgets import OptionList, Static

    text = lambda wid: str(app.query_one(wid, Static).render())  # noqa: E731
    backend = RecordingBackend(_snapshot(), _queued_response(_queued_command()))
    app = BunnylandTUI(backend)
    async with app.run_test() as pilot:
        await _select_player(app, pilot)
        assert "Parlor" in text("#room-title")
        members = app.query_one("#members", OptionList)
        # The held key is inventory, not a room member, so only the room's contents show.
        assert {o.id for o in members.options} == {PLAYER, MARLOW, APPLE}
        doors = app.query_one("#doors", OptionList)
        assert [o.id for o in doors.options] == [f"door:{HALL}"]
        assert "5/5 AP" in text("#points")
        queued = app.query_one("#queued", OptionList)
        assert backend.queued_requests[-1] == PLAYER
        assert queued.option_count == 1
        assert "Say [focus]" in str(queued.get_option_at_index(0).prompt)
        assert "1 AP + 1 FP" in str(queued.get_option_at_index(0).prompt)
        assert "text: next" in str(queued.get_option_at_index(0).prompt)


async def test_app_uses_projected_actions_and_target_groups(monkeypatch):
    from textual.widgets import OptionList

    projection = _client_view()
    projection["actions"] = [
        _projected_action(
            command_type="custom-inspect",
            tool_name="custom_inspect",
            title="Custom Inspect",
            lane="focus",
            cost={"action": 0, "focus": 1},
        )
    ]
    app = BunnylandTUI(RecordingBackend(_snapshot(), character_projection=projection))
    async with app.run_test() as pilot:
        await _select_player(app, pilot)
        verbs = app.query_one("#verbs", OptionList)
        assert verbs.option_count == 1
        assert "Custom Inspect" in str(verbs.get_option_at_index(0).prompt)
        assert "1 FP" in str(verbs.get_option_at_index(0).prompt)

        async def fake_pick(screen):
            assert isinstance(screen, TargetPicker)
            return APPLE

        monkeypatch.setattr(app, "push_screen_wait", fake_pick)
        app._verb_selected(SimpleNamespace(option=SimpleNamespace(id=verbs.get_option_at_index(0).id)))
        await pilot.pause()

        command = app.backend.commands[-1]
        assert command["command_type"] == "custom-inspect"
        assert command["payload"] == {"target_id": APPLE}
        assert command["cost"] == {"action": 0, "focus": 1}
        assert command["lane"] == "focus"


async def test_app_refresh_preserves_stable_action_list_position():
    from textual.widgets import OptionList

    projection = _client_view()
    projection["actions"] = [
        _projected_action(
            command_type=f"custom-{index}",
            tool_name=f"custom_{index}",
            title=f"Custom {index}",
        )
        for index in range(18)
    ]
    app = BunnylandTUI(RecordingBackend(_snapshot(), character_projection=projection))

    async with app.run_test() as pilot:
        await _select_player(app, pilot)
        verbs = app.query_one("#verbs", OptionList)
        verbs.highlighted = 17

        await app.refresh_world()

        assert verbs.option_count == 18
        assert verbs.highlighted == 17
        assert "Custom 17" in str(verbs.get_option_at_index(17).prompt)


async def test_app_renders_perceived_activity_after_initial_prime():
    from textual.widgets import OptionList

    backend = RecordingBackend(_snapshot())
    app = BunnylandTUI(backend)
    async with app.run_test() as pilot:
        await _select_player(app, pilot)
        activity = app.query_one("#activity", OptionList)
        assert "No recent activity." in str(activity.get_option_at_index(0).prompt)

        backend.events = [
            _event(
                "r1",
                event_type="CommandRejectedEvent",
                visibility="system",
                actor_id=PLAYER,
                command_type="take",
                reason="that item is not portable",
            ),
            _event(
                "r2",
                event_type="CommandRejectedEvent",
                visibility="system",
                actor_id=MARLOW,
                command_type="take",
                reason="secret",
            ),
        ]
        await app.refresh_world()

        assert activity.option_count == 1
        shown = str(activity.get_option_at_index(0).prompt)
        assert "Command rejected" in shown and "not portable" in shown
        assert "secret" not in shown


async def test_app_renders_empty_and_snapshot_fallback_queued_actions():
    from textual.widgets import OptionList

    app = BunnylandTUI(RecordingBackend(_snapshot()))
    async with app.run_test() as pilot:
        await _select_player(app, pilot)
        queued = app.query_one("#queued", OptionList)
        assert queued.option_count == 1
        assert "No queued actions." in str(queued.get_option_at_index(0).prompt)

    snapshot = _snapshot()
    snapshot["queued_commands"] = [_queued_command(command_id="cmd-fallback")]
    fallback_app = BunnylandTUI(FailingQueueBackend(snapshot))
    async with fallback_app.run_test() as pilot:
        await _select_player(fallback_app, pilot)
        queued = fallback_app.query_one("#queued", OptionList)
        assert queued.option_count == 1
        assert "text: next" in str(queued.get_option_at_index(0).prompt)


async def test_app_discards_mismatched_queued_command_response():
    app = BunnylandTUI(
        RecordingBackend(
            _snapshot(),
            {
                **_queued_response(_queued_command()),
                "character_id": MARLOW,
            },
        )
    )
    async with app.run_test() as pilot:
        await _select_player(app, pilot)
        assert app.queued_commands == []


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

        app._verb_selected(SimpleNamespace(option=SimpleNamespace(id="wait")))
        await pilot.pause()
        assert app.backend.commands[-1]["command_type"] == "wait"

        app._verb_selected(SimpleNamespace(option=SimpleNamespace(id="missing")))
        await pilot.pause()
        assert app.backend.commands[-1]["command_type"] == "wait"


async def test_app_target_picker_action_selection_runs_in_worker(monkeypatch):
    from textual.worker import get_current_worker

    app = BunnylandTUI(RecordingBackend(_snapshot()))
    async with app.run_test() as pilot:
        await _select_player(app, pilot)

        async def fake_pick(screen):
            assert isinstance(screen, TargetPicker)
            get_current_worker()
            return HALL

        monkeypatch.setattr(app, "push_screen_wait", fake_pick)

        app._verb_selected(SimpleNamespace(option=SimpleNamespace(id="move")))
        await pilot.pause()

        assert app.backend.commands[-1]["command_type"] == "move"
        assert app.backend.commands[-1]["payload"] == {"exit_id": HALL}


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


def test_main_lists_generators_and_exits(monkeypatch, capsys):
    from types import SimpleNamespace

    launched: list[bool] = []
    monkeypatch.setattr(
        tui_app,
        "available_generators",
        lambda: [
            SimpleNamespace(
                name="apartment-demo",
                uses_seed=False,
                description="a demo",
                group="pop culture",
            ),
            SimpleNamespace(
                name="recursive",
                uses_seed=True,
                description="",
                group="algorithmic",
            ),
        ],
    )
    monkeypatch.setattr(tui_app, "BunnylandTUI", lambda backend: launched.append(True))

    assert tui_app.main(["--list-generators"]) == 0
    assert launched == []
    output = capsys.readouterr().out
    assert "Algorithmic:" in output
    assert "  recursive" in output
    assert "Pop Culture:" in output
    assert "  apartment-demo *" in output
    assert "* ignores --seed" in output
