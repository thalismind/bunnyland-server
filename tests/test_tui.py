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
from bunnyland.tui.app import ActionForm, BunnylandTUI, FormField
from bunnyland.tui.backend import (
    Backend,
    LocalBackend,
    RemoteBackend,
    SubmitResult,
    persistent_client_id,
)
from bunnyland.tui.events import EventNarrator
from bunnyland.tui.model import Target, World, entity_icon, entity_name, entity_type
from bunnyland.tui.splash import IntroSplash
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
        "available": True,
        "enough_action_points": True,
        "enough_focus_points": True,
        "has_required_target": True,
        "meets_requirements": True,
        "unavailable_reason": "",
    }
    action.update(overrides)
    return action


def _queued_response(*commands: dict) -> dict:
    return {
        "ok": True,
        "schema_version": 1,
        "world_epoch": 42,
        "character_id": PLAYER,
        "generated_at_unix": 100.0,
        "next_tick_at_unix": 101.0,
        "tick_seconds": 1.0,
        "time_scale": 3600.0,
        "game_seconds_per_tick": 3600.0,
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


def test_event_narrator_uses_normal_style_for_activity_and_dim_for_system():
    world = World.parse(_snapshot())
    narrator = EventNarrator()
    shown = narrator.drain_events(
        [
            _event(
                "claim",
                event_type="CharacterClaimedEvent",
                visibility="public",
                actor_id=PLAYER,
                note="",
                character_id=PLAYER,
                controller_id="controller:1",
                generation=3,
            ),
            _event(
                "look",
                event_type="RoomLookedEvent",
                visibility="private",
                actor_id=PLAYER,
                note="",
                room_id=PARLOR,
                room_title="Parlor",
                summary="Parlor: Marlow, an apple",
            ),
            _event(
                "controller",
                event_type="ControllerChangedEvent",
                visibility="public",
                actor_id=PLAYER,
                note="",
                generation=4,
                controller_kind="web",
            ),
        ],
        player_id=PLAYER,
        room_of=world.room_of,
        name_for=lambda entity_id: entity_name(world.get(entity_id))
        if world.get(entity_id)
        else None,
    )

    assert [item.plain for item in shown] == [
        "Pib: Character claimed — Pib; generation 3",
        "Parlor: Marlow, an apple",
        "Pib: Controller changed — generation 4; controller kind web",
    ]
    assert shown[0].style == ""
    assert shown[1].style == ""
    assert shown[2].style == "dim"


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


def test_action_list_height_leaves_queue_visible():
    assert "#members, #doors, #activity {" in BunnylandTUI.CSS
    assert "#verbs { height: auto; max-height: 12; }" in BunnylandTUI.CSS
    assert "#queued { height: 1fr; min-height: 4;" in BunnylandTUI.CSS
    assert "#action-filter-row { height: 3; }" in BunnylandTUI.CSS
    assert "#action-filter-clear { width: 9; min-width: 9; }" in BunnylandTUI.CSS
    assert "#doors-title, #activity-title, #queued-title { border-top:" in BunnylandTUI.CSS
    assert "#doors { border-top:" not in BunnylandTUI.CSS


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

        async def delete(self, url: str, params: dict):
            self.requests.append(("DELETE", url, params))
            return Response(payload={"cancelled": True})

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
    character_list = await backend.fetch_character_list()
    character = await backend.fetch_character_projection(PLAYER)
    room = await backend.fetch_room_projection(PARLOR)
    queued = await backend.fetch_queued_commands(PLAYER)
    submitted = await backend.submit({"command_type": "wait"})
    cancelled = await backend.cancel_command(PLAYER, "cmd-1", "controller:1", 3)
    await backend.close()

    assert snapshot == {"world_epoch": 7}
    assert character_list == []  # validated CharacterListResponse with no characters
    assert character == {"world_epoch": 7}
    assert room == {"world_epoch": 7}
    assert queued == {"world_epoch": 7}
    assert submitted.accepted is False
    assert cancelled is True
    assert clients[0].closed is True
    assert clients[0].requests == [
        ("GET", "http://server.example/world/snapshot", None),
        ("GET", "http://server.example/world/characters", None),
        ("GET", f"http://server.example/world/character/{PLAYER}", None),
        ("GET", f"http://server.example/world/room/{PARLOR}", None),
        ("GET", f"http://server.example/world/character/{PLAYER}/commands", None),
        ("POST", "http://server.example/world/commands", {"command_type": "wait"}),
        (
            "DELETE",
            f"http://server.example/world/character/{PLAYER}/commands/cmd-1",
            {"controller_id": "controller:1", "controller_generation": 3},
        ),
    ]


async def test_remote_backend_close_without_client_is_noop():
    backend = RemoteBackend("http://server.example")

    await backend.close()

    assert backend._client is None


async def test_remote_backend_submit_reports_rejection_reason():
    class Response:
        def __init__(self, *, is_success=True, payload=None, raises=False):
            self.is_success = is_success
            self.status_code = 200 if is_success else 422
            self._payload = payload or {}
            self._raises = raises

        def json(self):
            if self._raises:
                raise ValueError("no body")
            return self._payload

    class Client:
        def __init__(self, response):
            self.response = response

        async def post(self, url, json):
            return self.response

    accepted = RemoteBackend("http://server.example")
    accepted._client = Client(Response(payload={"queued": True, "reason": ""}))
    result = await accepted.submit({"command_type": "wait"})
    assert result.accepted is True and result.reason == ""

    rejected = RemoteBackend("http://server.example")
    rejected._client = Client(
        Response(payload={"queued": False, "reason": "missing required argument: text"})
    )
    result = await rejected.submit({"command_type": "say"})
    assert result.accepted is False
    assert result.reason == "missing required argument: text"

    # A non-2xx response with an unparseable body still yields a usable reason.
    errored = RemoteBackend("http://server.example")
    errored._client = Client(Response(is_success=False, raises=True))
    result = await errored.submit({"command_type": "say"})
    assert result.accepted is False
    assert "422" in result.reason


async def test_backend_default_queued_commands_response():
    class MinimalBackend(Backend):
        label = "minimal"

        async def start(self) -> None: ...
        async def close(self) -> None: ...
        async def fetch_snapshot(self) -> dict:
            return {}

        async def submit(self, command: dict) -> SubmitResult:
            return SubmitResult(accepted=True)

        async def claim(self, player_id: str, world: World):
            return None

    queued = await MinimalBackend().fetch_queued_commands(PLAYER)
    assert queued == {
        "ok": True,
        "schema_version": 1,
        "world_epoch": 0,
        "character_id": PLAYER,
        "generated_at_unix": queued["generated_at_unix"],
        "next_tick_at_unix": None,
        "tick_seconds": None,
        "time_scale": None,
        "game_seconds_per_tick": None,
        "commands": [],
    }
    assert isinstance(queued["generated_at_unix"], float)


# ── the app (Textual pilot) ───────────────────────────────────────────────────
def _character_list_from_snapshot(snapshot: dict) -> list:
    """The claim-lobby records the app's picker needs, derived from a snapshot fixture."""
    from bunnyland.server.models import CharacterSummaryView

    world = World.parse(snapshot)
    return [
        CharacterSummaryView(
            character_id=character["id"],
            name=entity_name(character),
            kind=character["components"].get("IdentityComponent", {}).get("kind", "character"),
            suspended="SuspendedComponent" in character["components"],
        )
        for character in world.characters()
    ]


class RecordingBackend(Backend):
    """A static projection backend that records submitted commands, for app tests.

    The app now reads the claim lobby (``fetch_character_list``) for the picker and the
    player's own room (``fetch_character_projection``) for the world, never the full
    snapshot, so this backend defaults the projection to the parlor client-view and derives
    the lobby from the snapshot fixture."""

    def __init__(
        self,
        snapshot: dict,
        queued_response: dict | None = None,
        events: list[dict] | None = None,
        character_projection: dict | None = None,
        character_list: list | None = None,
    ) -> None:
        self.snapshot = snapshot
        self.queued_response = queued_response or _queued_response()
        self.events = events or []
        self.character_projection = (
            character_projection if character_projection is not None else _client_view()
        )
        self.character_list = (
            character_list
            if character_list is not None
            else _character_list_from_snapshot(snapshot)
        )
        self.queued_requests: list[str] = []
        self.commands: list[dict] = []
        self.cancelled_commands: list[tuple[str, str, str, int]] = []
        self.label = "test"

    async def start(self) -> None: ...
    async def close(self) -> None: ...
    async def fetch_snapshot(self) -> dict:
        return copy.deepcopy(self.snapshot)

    async def fetch_character_list(self) -> list:
        return list(self.character_list)

    async def fetch_queued_commands(self, character_id: str) -> dict:
        self.queued_requests.append(character_id)
        return copy.deepcopy(self.queued_response)

    async def fetch_character_projection(self, character_id: str) -> dict | None:
        if self.character_projection is None:
            return None
        return copy.deepcopy(self.character_projection)

    async def submit(self, command: dict) -> SubmitResult:
        self.commands.append(command)
        return SubmitResult(accepted=True)

    async def cancel_command(
        self,
        character_id: str,
        command_id: str,
        controller_id: str,
        controller_generation: int,
    ) -> bool:
        self.cancelled_commands.append(
            (character_id, command_id, controller_id, controller_generation)
        )
        return True

    async def recent_events(self) -> list[dict]:
        return copy.deepcopy(self.events)

    async def claim(self, player_id, world):
        return World.parse(self.snapshot).control(player_id)


class FailingQueueBackend(RecordingBackend):
    async def fetch_queued_commands(self, character_id: str) -> dict:
        self.queued_requests.append(character_id)
        raise RuntimeError("queue failed")


class FlakyBackend(RecordingBackend):
    def __init__(self, snapshot: dict) -> None:
        super().__init__(snapshot)
        self.fail = True

    async def fetch_character_list(self) -> list:
        if self.fail:
            raise RuntimeError("lobby failed")
        return await super().fetch_character_list()


async def _select_player(app, pilot):
    from textual.widgets import Select

    select = await _wait_for_widget(app, pilot, "#player", Select)
    select.value = PLAYER
    await pilot.pause()


async def _wait_for_widget(root, pilot, selector: str, expect_type=None):
    from textual.css.query import NoMatches

    last_error = None
    for _ in range(20):
        try:
            return root.query_one(selector, expect_type)
        except NoMatches as exc:
            last_error = exc
            await pilot.pause(0.05)
    raise last_error


async def _wait_for_tui_ready(app, pilot) -> None:
    await _wait_for_widget(app, pilot, "#player")
    await _wait_for_widget(app, pilot, "#character-release")
    await _wait_for_widget(app, pilot, "#activity")


async def _push_action_form(app, pilot, screen: ActionForm, *, callback=None) -> ActionForm:
    await _wait_for_tui_ready(app, pilot)
    await app.push_screen(screen, callback=callback)
    await _wait_for_widget(screen, pilot, "#form-submit")
    return screen


async def test_action_form_dropdown_selects_and_cancels():
    from textual.widgets import Select

    candidates = World.parse(_snapshot()).target_candidates(PLAYER, "exits")
    field = FormField(
        key="exit_id", label="exit", kind="entity", required=True,
        candidates=tuple(candidates),
    )
    app = BunnylandTUI(RecordingBackend(_snapshot()))
    results = []

    async with app.run_test() as pilot:
        screen = ActionForm("Move", [field])
        await _push_action_form(app, pilot, screen, callback=results.append)
        screen.query_one("#field-exit_id", Select).value = HALL
        screen.query_one("#form-submit").press()
        await pilot.pause()
        assert results[-1] == {"exit_id": HALL}

        cancelled = ActionForm("Move", [field])
        await _push_action_form(app, pilot, cancelled, callback=results.append)
        await pilot.press("escape")
        await pilot.pause()
        assert results[-1] is None


async def test_action_form_dropdown_uses_initial_value():
    from textual.widgets import Select

    field = FormField(
        key="target_id",
        label="target",
        kind="entity",
        required=True,
        candidates=(Target(APPLE, "an apple", "✦"),),
        initial_value=APPLE,
    )
    app = BunnylandTUI(RecordingBackend(_snapshot()))

    async with app.run_test() as pilot:
        screen = ActionForm("Inspect", [field])
        await _push_action_form(app, pilot, screen)
        assert screen.query_one("#field-target_id", Select).value == APPLE


async def test_action_form_text_field_submits_and_blocks_when_required():
    from textual.widgets import Input, Label

    field = FormField(key="text", label="text", kind="string", required=True)
    app = BunnylandTUI(RecordingBackend(_snapshot()))
    results = []

    async with app.run_test() as pilot:
        screen = ActionForm("Say", [field])
        await _push_action_form(app, pilot, screen, callback=results.append)
        screen.query_one("#field-text", Input).value = "hello"
        await pilot.press("enter")
        await pilot.pause()
        assert results[-1] == {"text": "hello"}

        # A blank required field reports an error and does not submit (no new result).
        blocked = ActionForm("Say", [field])
        await _push_action_form(app, pilot, blocked, callback=results.append)
        blocked.query_one("#form-submit").press()
        await pilot.pause()
        assert "required" in str(blocked.query_one("#form-error", Label).render())
        assert len(results) == 1

        await pilot.press("escape")
        await pilot.pause()
        assert results[-1] is None


async def test_action_form_renders_numeric_input_for_number_fields():
    from textual.widgets import Input

    field = FormField(key="amount", label="amount", kind="number", required=True)
    app = BunnylandTUI(RecordingBackend(_snapshot()))

    async with app.run_test() as pilot:
        screen = ActionForm("Trade", [field])
        await _push_action_form(app, pilot, screen)
        assert screen.query_one("#field-amount", Input).type == "number"


async def test_intro_splash_fades_and_dismisses():
    app = BunnylandTUI(RecordingBackend(_snapshot()), show_intro=True)
    async with app.run_test() as pilot:
        await pilot.pause(0.1)
        assert any(isinstance(screen, IntroSplash) for screen in app.screen_stack)

        await pilot.pause(1.1)
        splash = next(screen for screen in app.screen_stack if isinstance(screen, IntroSplash))
        panel = splash.query_one("#splash")
        assert 0 < panel.styles.opacity <= 1

        await pilot.pause(1.0)
        assert not any(isinstance(screen, IntroSplash) for screen in app.screen_stack)


async def test_intro_splash_does_not_use_widget_animation_api(monkeypatch):
    def fail_if_animated(*_args, **_kwargs) -> None:
        raise AssertionError("IntroSplash should not call animate() on this Textual version")

    monkeypatch.setattr(IntroSplash, "animate", fail_if_animated)
    app = BunnylandTUI(RecordingBackend(_snapshot()), show_intro=True)
    async with app.run_test() as _pilot:
        # If the old animate-based implementation is used, this would raise before splash
        # dismissal or app startup completes.
        pass


async def test_app_reports_refresh_errors():
    from textual.widgets import OptionList, Static

    backend = FlakyBackend(_snapshot())
    app = BunnylandTUI(backend)
    async with app.run_test():
        assert "lobby failed" in str(app.query_one("#status", Static).render())
        activity = app.query_one("#activity", OptionList)
        assert activity.option_count == 1
        assert "lobby failed" in str(activity.get_option_at_index(0).prompt)

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
        assert "4/5 AP" in text("#points")
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

        async def fake_form(screen):
            assert isinstance(screen, ActionForm)
            assert [field.key for field in screen.fields] == ["target_id"]
            return {"target_id": APPLE}

        monkeypatch.setattr(app, "push_screen_wait", fake_form)
        app._verb_selected(SimpleNamespace(option=SimpleNamespace(id=verbs.get_option_at_index(0).id)))
        await pilot.pause()

        command = app.backend.commands[-1]
        assert command["command_type"] == "custom-inspect"
        assert command["payload"] == {"target_id": APPLE}
        assert command["cost"] == {"action": 0, "focus": 1}
        assert command["lane"] == "focus"


async def test_app_preselects_selected_entity_in_action_form(monkeypatch):
    from textual.widgets import OptionList

    app = BunnylandTUI(RecordingBackend(_snapshot()))
    async with app.run_test() as pilot:
        await _select_player(app, pilot)
        app.selected_id = APPLE

        async def fake_form(screen):
            assert isinstance(screen, ActionForm)
            (target_field,) = screen.fields
            assert target_field.key == "target_id"
            assert target_field.initial_value == APPLE
            return {"target_id": APPLE}

        monkeypatch.setattr(app, "push_screen_wait", fake_form)
        verbs = app.query_one("#verbs", OptionList)
        app._verb_selected(SimpleNamespace(option=SimpleNamespace(id=verbs.get_option_at_index(0).id)))
        await pilot.pause()
        assert app.backend.commands[-1]["payload"] == {"target_id": APPLE}


async def test_app_ignores_second_action_form_while_one_is_open():
    app = BunnylandTUI(RecordingBackend(_snapshot()))
    async with app.run_test() as pilot:
        await _select_player(app, pilot)
        field = FormField(key="text", label="text", kind="string", required=True)
        await _push_action_form(app, pilot, ActionForm("Say", [field]))
        assert sum(isinstance(s, ActionForm) for s in app.screen_stack) == 1

        # Selecting another action while a form is open is a no-op: no second form, no submit.
        say = next(v for v in ACTION_VERBS if v.tool == "say")
        await app._do_verb(say)
        await pilot.pause()
        assert sum(isinstance(s, ActionForm) for s in app.screen_stack) == 1
        assert app.backend.commands == []


async def test_app_refreshes_main_ui_while_action_form_is_open():
    from textual.widgets import Static

    app = BunnylandTUI(RecordingBackend(_snapshot()))
    async with app.run_test() as pilot:
        await _select_player(app, pilot)
        field = FormField(key="text", label="text", kind="string", required=True)
        await _push_action_form(app, pilot, ActionForm("Say", [field]))

        await app.refresh_world()

        assert sum(isinstance(s, ActionForm) for s in app.screen_stack) == 1
        assert "Parlor" in str(app._main_query_one("#room-title", Static).render())


async def test_app_main_query_falls_back_to_mounted_screen_stack(monkeypatch):
    from textual.css.query import NoMatches
    from textual.widgets import Static

    app = BunnylandTUI(RecordingBackend(_snapshot()))
    async with app.run_test() as pilot:
        await _wait_for_tui_ready(app, pilot)
        original_query_one = app.query_one

        def miss_app_query(selector, expect_type=None):
            if selector == "#room-title":
                raise NoMatches("forced app-level miss")
            return original_query_one(selector, expect_type)

        monkeypatch.setattr(app, "query_one", miss_app_query)

        assert app._main_query_one("#room-title", Static).id == "room-title"
        with pytest.raises(NoMatches):
            app._main_query_one("#not-mounted")


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
        updated_projection = copy.deepcopy(projection)
        updated_projection["actions"][0] = {
            **updated_projection["actions"][0],
            "title": "Renamed action",
        }
        app.backend.character_projection = updated_projection

        await app.refresh_world()

        assert verbs.option_count == 18
        assert verbs.highlighted == 17
        assert "Custom 17" in str(verbs.get_option_at_index(17).prompt)


async def test_app_filters_and_clears_action_list():
    from textual.widgets import Button, Input, OptionList

    projection = _client_view()
    projection["actions"] = [
        _projected_action(
            command_type="inspect",
            tool_name="inspect",
            title="Inspect",
        ),
        _projected_action(
            command_type="negotiate",
            tool_name="negotiate",
            title="Negotiate",
        ),
        _projected_action(
            command_type="bribe",
            tool_name="bribe",
            title="Bribe",
        ),
    ]
    app = BunnylandTUI(
        RecordingBackend(
            _snapshot(),
            _queued_response(_queued_command(command_type="say")),
            character_projection=projection,
        )
    )

    async with app.run_test() as pilot:
        await _select_player(app, pilot)
        verbs = app.query_one("#verbs", OptionList)
        queued = app.query_one("#queued", OptionList)
        assert verbs.option_count == 3
        assert queued.option_count == 1

        filter_input = app.query_one("#action-filter", Input)
        filter_input.value = "neg"
        await pilot.pause()

        assert verbs.option_count == 1
        assert "Negotiate" in str(verbs.get_option_at_index(0).prompt)
        assert queued.option_count == 1

        app._action_filter_clear_pressed(
            SimpleNamespace(button=app.query_one("#action-filter-clear", Button))
        )
        await pilot.pause()

        assert filter_input.value == ""
        assert verbs.option_count == 3


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


async def test_app_points_line_colors_values_and_dims_zero_pips():
    from textual.widgets import Static

    projection = _client_view()
    projection["points"] = {
        "action": 0,
        "action_max": 5,
        "focus": 2,
        "focus_max": 3,
    }
    app = BunnylandTUI(RecordingBackend(_snapshot(), character_projection=projection))
    async with app.run_test() as pilot:
        await _select_player(app, pilot)
        line = app.query_one("#points", Static).render()

    assert line.plain == "⚡ 0/5 AP   🔹 2/3 FP"
    spans = {line.plain[span.start:span.end]: str(span.style) for span in line.spans}
    assert "dim" in spans["⚡"]
    assert "255,135,0" in spans[" 0/5 AP"]
    assert "cyan" in spans["🔹"]
    assert "cyan" in spans[" 2/3 FP"]


async def test_app_covers_defensive_selection_and_action_branches(monkeypatch):
    from textual.widgets import OptionList

    projection = _client_view()
    projection["actions"] = [
        _projected_action(command_type="wait", tool_name="wait", title="Wait"),
        _projected_action(command_type="rest", tool_name="wait", title="Rest"),
    ]
    app = BunnylandTUI(RecordingBackend(_snapshot(), character_projection=projection))
    async with app.run_test() as pilot:
        await _select_player(app, pilot)
        verbs = app.query_one("#verbs", OptionList)
        assert {option.id for option in verbs.options} == {"wait", "wait:1"}

        run_calls = []
        monkeypatch.setattr(app, "run_worker", lambda *args, **kwargs: run_calls.append(args))
        app._door_selected(SimpleNamespace(option=SimpleNamespace(id="not-a-door")))
        app._queued_selected(SimpleNamespace(option=SimpleNamespace(id="not-queued")))
        app._queued_selected(SimpleNamespace(option=SimpleNamespace(id="queued:99")))
        assert run_calls == []

        fields = app._action_fields({
            "arguments": [
                {"title": "missing key", "required": True},
                {"key": "optional", "required": False},
                {"key": "target_id", "required": False, "target_group": "characters"},
            ],
        })
        assert [field.key for field in fields] == ["target_id"]

        app.action_views = []
        await app._move_through_exit("missing-exit")

        app.action_views = [{
            "command_type": "move",
            "tool_name": "move",
            "arguments": [{"key": "exit_id", "target_group": "elsewhere", "required": True}],
        }]
        await app._move_through_exit("missing-exit")

        app.player_id = ""
        app.control = None
        await app._do_action({"command_type": "wait", "tool_name": "wait", "arguments": []})
        await app._submit_action({"command_type": "wait", "tool_name": "wait"}, {})
        await app._cancel_queued_command({"command_id": "cmd-1"})


async def test_app_failed_queue_cancel_reports_activity():
    class CancelFailBackend(RecordingBackend):
        async def cancel_command(
            self,
            character_id: str,
            command_id: str,
            controller_id: str,
            controller_generation: int,
        ) -> bool:
            await super().cancel_command(
                character_id, command_id, controller_id, controller_generation
            )
            return False

    app = BunnylandTUI(CancelFailBackend(_snapshot()))
    async with app.run_test() as pilot:
        await _select_player(app, pilot)
        await app._cancel_queued_command({"command_id": "cmd-1"})

    assert any("Could not cancel queued command" in line.plain for line in app.activity_lines)


async def test_app_renders_empty_and_keeps_last_queue_on_fetch_failure():
    from textual.widgets import OptionList

    app = BunnylandTUI(RecordingBackend(_snapshot()))
    async with app.run_test() as pilot:
        await _select_player(app, pilot)
        queued = app.query_one("#queued", OptionList)
        assert queued.option_count == 1
        assert "No queued actions." in str(queued.get_option_at_index(0).prompt)

    # A transient queue-fetch failure keeps the last-known queue rather than blanking it.
    fallback_app = BunnylandTUI(FailingQueueBackend(_snapshot()))
    fallback_app.player_id = PLAYER
    fallback_app.queued_commands = [_queued_command(command_id="cmd-last")]
    async with fallback_app.run_test():
        assert await fallback_app._fetch_queued_commands() == [
            _queued_command(command_id="cmd-last")
        ]


async def test_app_selecting_queued_command_cancels_it():
    from textual.widgets import OptionList

    backend = RecordingBackend(_snapshot(), _queued_response(_queued_command()))
    app = BunnylandTUI(backend)
    async with app.run_test() as pilot:
        await _select_player(app, pilot)
        queued = app.query_one("#queued", OptionList)

        app._queued_selected(SimpleNamespace(option=SimpleNamespace(id=queued.get_option_at_index(0).id)))
        await pilot.pause()

        assert backend.cancelled_commands == [(PLAYER, "cmd-1", "controller:1", 3)]


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
        app.player_id = ""
        app._render_room()
        assert str(app.query_one("#room-title", Static).render()) == "No room"


async def test_app_renders_only_the_players_own_room():
    from textual.widgets import OptionList, Static

    app = BunnylandTUI(RecordingBackend(_snapshot()))
    async with app.run_test() as pilot:
        await _select_player(app, pilot)
        # The view is always the player's own perceived room; there is no door-spectating.
        assert app.view_room_id == PARLOR
        assert "Parlor" in str(app.query_one("#room-title", Static).render())
        assert "spectating" not in str(app.query_one("#room-title", Static).render())
        # Exits are labelled by direction, not the neighbouring room's name (no map leak).
        doors = app.query_one("#doors", OptionList)
        assert [o.id for o in doors.options] == [f"door:{HALL}"]
        assert "north" in str(doors.get_option_at_index(0).prompt)
        assert "Hallway" not in str(doors.get_option_at_index(0).prompt)


async def test_app_selecting_door_queues_move():
    from textual.widgets import OptionList

    projection = _client_view()
    projection["actions"] = [
        _projected_action(
            command_type="move",
            tool_name="move",
            title="Move",
            cost={"action": 1, "focus": 0},
            arguments=[
                {
                    "key": "exit_id",
                    "title": "exit",
                    "kind": "entity",
                    "required": True,
                    "target_group": "exits",
                }
            ],
        )
    ]
    app = BunnylandTUI(RecordingBackend(_snapshot(), character_projection=projection))
    async with app.run_test() as pilot:
        await _select_player(app, pilot)
        doors = app.query_one("#doors", OptionList)

        app._door_selected(SimpleNamespace(option=SimpleNamespace(id=doors.get_option_at_index(0).id)))
        await pilot.pause()

        assert app.backend.commands[-1]["command_type"] == "move"
        assert app.backend.commands[-1]["payload"] == {"exit_id": HALL}


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


async def test_app_action_form_selection_runs_in_worker(monkeypatch):
    from textual.worker import get_current_worker

    app = BunnylandTUI(RecordingBackend(_snapshot()))
    async with app.run_test() as pilot:
        await _select_player(app, pilot)

        async def fake_form(screen):
            assert isinstance(screen, ActionForm)
            get_current_worker()
            return {"exit_id": HALL}

        monkeypatch.setattr(app, "push_screen_wait", fake_form)

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
        # Generation comes from the character projection's controller (gen 3 in _client_view).
        assert app.backend.commands[-1]["controller_generation"] == 3


async def test_app_refresh_action_resyncs_existing_player():
    from textual.widgets import Select

    app = BunnylandTUI(RecordingBackend(_snapshot()))
    async with app.run_test() as pilot:
        await _select_player(app, pilot)
        await app.action_refresh()
        assert app.query_one("#player", Select).value == PLAYER


async def test_app_syncs_picker_and_noops_reselecting_same_player():
    from textual.widgets import Select

    app = BunnylandTUI(RecordingBackend(_snapshot()))
    async with app.run_test():
        app.character_list = _character_list_from_snapshot(_snapshot())
        app.player_id = PLAYER
        app._player_choice_ids = [MARLOW]
        app._sync_players()
        assert app.query_one("#player", Select).value == PLAYER

        # The view always tracks the player's own room after a refresh.
        await app.refresh_world()
        assert app.view_room_id == PARLOR

        # Re-selecting the player you already control is a no-op (selection preserved).
        app.selected_id = APPLE
        await app._player_changed(SimpleNamespace(value=PLAYER))
        assert app.selected_id == APPLE


async def test_app_move_uses_action_form_dropdown(monkeypatch):
    app = BunnylandTUI(RecordingBackend(_snapshot()))
    async with app.run_test() as pilot:
        await _select_player(app, pilot)

        async def fake_form(screen):
            assert isinstance(screen, ActionForm)
            # the exit argument is offered as a dropdown of nearby candidates
            (exit_field,) = screen.fields
            assert exit_field.candidates is not None
            return {"exit_id": HALL}  # choose the north exit

        monkeypatch.setattr(app, "push_screen_wait", fake_form)
        move = next(v for v in ACTION_VERBS if v.tool == "move")
        await app._do_verb(move)
        cmd = app.backend.commands[-1]
        assert cmd["command_type"] == "move"
        assert cmd["payload"] == {"exit_id": HALL}


async def test_app_action_form_cancellation_submits_nothing(monkeypatch):
    app = BunnylandTUI(RecordingBackend(_snapshot()))
    async with app.run_test() as pilot:
        await _select_player(app, pilot)

        async def fake_form(screen):
            # tell collects both its target dropdown and message in one form
            assert {field.key for field in screen.fields} == {"target_id", "text"}
            return None  # user cancelled the form

        monkeypatch.setattr(app, "push_screen_wait", fake_form)
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

        async def fake_form(screen):
            assert isinstance(screen, ActionForm)
            assert [field.key for field in screen.fields] == ["text"]
            return {"text": "hello terminal"}

        monkeypatch.setattr(app, "push_screen_wait", fake_form)
        say = next(v for v in ACTION_VERBS if v.tool == "say")
        await app._do_verb(say)
        assert app.backend.commands[-1]["payload"] == {"text": "hello terminal"}


async def test_app_cancelled_form_submits_nothing(monkeypatch):
    app = BunnylandTUI(RecordingBackend(_snapshot()))
    async with app.run_test() as pilot:
        await _select_player(app, pilot)

        async def fake_form(screen):
            return None  # user pressed escape

        monkeypatch.setattr(app, "push_screen_wait", fake_form)
        await app._do_verb(next(v for v in ACTION_VERBS if v.tool == "move"))
        assert app.backend.commands == []


async def test_app_deemphasizes_unavailable_verbs_but_keeps_them_selectable():
    from textual.widgets import OptionList

    # An available "wait", and two unavailable actions the projection flagged. They are not
    # removed or disabled -- only de-emphasized and sorted after the available ones.
    projection = _client_view()
    projection["actions"] = [
        _projected_action(
            command_type="move", tool_name="move", title="Move",
            cost={"action": 1, "focus": 0}, arguments=[],
            available=False, enough_action_points=False,
            unavailable_reason="not enough action points",
        ),
        _projected_action(
            command_type="wait", tool_name="wait", title="Wait",
            cost={"action": 0, "focus": 0}, arguments=[],
        ),
        _projected_action(
            command_type="pick-lock", tool_name="pick_lock", title="Pick Lock",
            cost={"action": 1, "focus": 0}, arguments=[],
            available=False, meets_requirements=False,
            unavailable_reason="missing a required skill or item",
        ),
    ]

    app = BunnylandTUI(RecordingBackend(_snapshot(), character_projection=projection))
    async with app.run_test() as pilot:
        await _select_player(app, pilot)
        options = list(app.query_one("#verbs", OptionList).options)
        by_id = {option.id: option for option in options}

        # Nothing is disabled: an unavailable action can still be selected/queued.
        assert all(not option.disabled for option in options)

        # The available action sorts first; unavailable ones follow.
        assert options[0].id == "wait"
        assert {options[1].id, options[2].id} == {"move", "pick_lock"}

        # Unavailable actions are dimmed and show their reason; available ones are not.
        move_label = by_id["move"].prompt
        assert move_label.style == "dim"
        assert "not enough action points" in move_label.plain
        assert "missing a required skill or item" in by_id["pick_lock"].prompt.plain
        assert by_id["wait"].prompt.style != "dim"


async def test_app_surfaces_submit_rejection_reason():

    projection = _client_view()
    projection["actions"] = [
        _projected_action(
            command_type="wait", tool_name="wait", title="Wait",
            cost={"action": 0, "focus": 0}, arguments=[],
        ),
    ]

    class RejectingBackend(RecordingBackend):
        async def submit(self, command: dict) -> SubmitResult:
            self.commands.append(command)
            return SubmitResult(accepted=False, reason="character is asleep")

    app = BunnylandTUI(RejectingBackend(_snapshot(), character_projection=projection))
    async with app.run_test() as pilot:
        await _select_player(app, pilot)
        await app._do_action(
            next(a for a in app.action_views if a["command_type"] == "wait")
        )
        assert any(
            "character is asleep" in line.plain for line in app.activity_lines
        )


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


async def test_app_release_clears_character_selection():
    from textual.widgets import Button, Select

    app = BunnylandTUI(RecordingBackend(_snapshot()))
    async with app.run_test() as pilot:
        await app._character_release_pressed(SimpleNamespace())
        assert app.player_id == ""
        assert app.control is None

        await _select_player(app, pilot)
        assert app.player_id == PLAYER
        assert not app.query_one("#character-release", Button).disabled

        await app._character_release_pressed(SimpleNamespace())
        await pilot.pause()

        assert app.player_id == ""
        assert app.control is None
        assert app.query_one("#player", Select).value == Select.NULL
        assert app.query_one("#character-release", Button).disabled


async def test_app_empty_character_roster_prompts_for_playable_character():
    from textual.widgets import Button, Static

    app = BunnylandTUI(
        RecordingBackend(_snapshot(), character_projection=None, character_list=[])
    )
    async with app.run_test():
        assert app.query_one("#character-release", Button).disabled
        hint = str(app.query_one("#play-hint", Static).render())
        assert "playable characters" in hint


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
