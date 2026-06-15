"""Tests for the REPL client: parsing, name resolution, completion, command rendering, and
the Textual app (RichLog scrollback, clickable target links, Tab completion, history)."""

from __future__ import annotations

import pytest
from rich.style import Style

from bunnyland.core.actions import ActionArgument, ActionDefinition, definitions_by_tool_name
from bunnyland.repl import app as repl_app
from bunnyland.repl.app import BunnylandReplApp, ReplInput
from bunnyland.repl.client import (
    BunnylandRepl,
    ParsedCommand,
    _humanize_event_type,
    available_generators,
    format_generator_lines,
    link,
    parse_line,
    resolve_name,
)
from bunnyland.repl.completion import complete_line, reference_candidates, value_candidates
from bunnyland.tui.backend import Backend
from bunnyland.tui.model import World

PLAYER = "character:1"
MARLOW = "character:2"
APPLE = "item:1"
KEY = "item:2"
PARLOR = "room:1"
HALL = "room:2"

DEFS = definitions_by_tool_name()


@pytest.fixture(autouse=True)
def _isolate_history(monkeypatch, tmp_path):
    """Sandbox the REPL history file so app tests never read or clobber the real one."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))


def _snapshot() -> dict:
    """A parlor with the player, Marlow and an apple; the player holds a brass key and
    there is a north exit to a hallway. The player is driven by controller gen 2."""
    return {
        "world_epoch": 42,
        "entities": [
            {
                "id": PARLOR,
                "components": {"RoomComponent": {"title": "Parlor"}},
                "relationships": {
                    "Contains": [
                        {"target_id": PLAYER, "edge": {}},
                        {"target_id": MARLOW, "edge": {}},
                        {"target_id": APPLE, "edge": {}},
                    ],
                    "ExitTo": [{"target_id": HALL, "edge": {"direction": "north"}}],
                },
            },
            {
                "id": HALL,
                "components": {"RoomComponent": {"title": "Hallway"}},
                "relationships": {},
            },
            {
                "id": PLAYER,
                "components": {
                    "CharacterComponent": {},
                    "IdentityComponent": {"name": "Pib", "kind": "character"},
                    "ActionPointsComponent": {"current": 5, "maximum": 5},
                    "FocusPointsComponent": {"current": 3, "maximum": 3},
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


class RecordingBackend(Backend):
    """Static-snapshot backend recording submitted commands, like the TUI test double."""

    def __init__(self, snapshot: dict | None = None) -> None:
        self.snapshot = snapshot or _snapshot()
        self.commands: list[dict] = []
        self.label = "test"
        self.started = False
        self.closed = False

    async def start(self) -> None:
        self.started = True

    async def close(self) -> None:
        self.closed = True

    async def fetch_snapshot(self) -> dict:
        return self.snapshot

    async def submit(self, command: dict) -> bool:
        self.commands.append(command)
        return True

    async def claim(self, player_id, world):
        return world.control(player_id) or ("controller:new", 0)


def _repl(snapshot: dict | None = None, *, player: bool = True) -> BunnylandRepl:
    repl = BunnylandRepl(RecordingBackend(snapshot))
    repl.world = World.parse(snapshot or _snapshot())
    if player:
        repl.player_id = PLAYER
        repl.control = ("controller:1", 2)
    return repl


# ── parsing ─────────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "line, tool, arguments",
    [
        ("wait", "wait", {}),
        ("move direction=north", "move", {"direction": "north"}),
        ("take item_id=a brass key", "take", {"item_id": "a brass key"}),
        ("go north", "move", {"direction": "north"}),
        ("take brass key", "take", {"item_id": "brass key"}),
        ("say hello there", "say", {"text": "hello there"}),
    ],
)
def test_parse_line_named_and_natural(line, tool, arguments):
    assert parse_line(line, DEFS) == ParsedCommand(tool, arguments)


def test_parse_line_unknown_or_empty_returns_none():
    assert parse_line("", DEFS) is None
    assert parse_line("xyzzy zork", DEFS) is None


# ── name resolution ───────────────────────────────────────────────────────────
def test_resolve_name_passthrough_exact_and_prefix():
    world = World.parse(_snapshot())
    candidates = reference_candidates(world, PLAYER)
    assert resolve_name(KEY, world, candidates) == KEY  # already a valid id
    assert resolve_name("a brass key", world, candidates) == KEY  # exact name
    assert resolve_name("an ap", world, candidates) == APPLE  # shortest prefix
    assert resolve_name("", world, candidates) == ""  # empty query
    assert resolve_name("dragon", world, candidates) == "dragon"  # unresolvable


# ── completion ────────────────────────────────────────────────────────────────
def test_complete_command_names():
    matches = complete_line("mo", definitions=DEFS, commands=(*DEFS, "help", "quit"))
    assert "move" in matches


def test_complete_parameter_names():
    assert set(complete_line("move ", definitions=DEFS, commands=tuple(DEFS))) == {
        "move direction=",
        "move exit_id=",
    }


def test_complete_direction_values():
    matches = complete_line("move direction=", definitions=DEFS, commands=tuple(DEFS))
    assert "move direction=north" in matches and "move direction=south" in matches


def test_complete_entity_values_handle_spaces_and_prefix():
    names = ["a brass key", "an apple"]
    assert complete_line(
        "take item_id=", definitions=DEFS, commands=tuple(DEFS), entity_names=names
    ) == ["take item_id=a brass key", "take item_id=an apple"]
    assert complete_line(
        "take item_id=a b", definitions=DEFS, commands=tuple(DEFS), entity_names=names
    ) == ["take item_id=a brass key"]


def test_complete_second_parameter_name_after_a_value():
    matches = complete_line(
        "use target_id=an apple tool_", definitions=DEFS, commands=tuple(DEFS),
        entity_names=["an apple", "a brass key"],
    )
    assert matches == ["use target_id=an apple tool_id="]


def test_complete_help_and_play_and_unknown():
    assert "help move" in complete_line("help mo", definitions=DEFS, commands=tuple(DEFS))
    assert complete_line(
        "play P", definitions=DEFS, commands=tuple(DEFS), players=["Pib", "Marlow"]
    ) == ["play Pib"]
    assert complete_line("bogus key=", definitions=DEFS, commands=tuple(DEFS)) == []


def test_value_candidates_kinds():
    boolean = ActionDefinition(
        command_type="toggle", arguments={"flag": ActionArgument(kind="boolean")}
    )
    assert value_candidates(boolean, "flag", ()) == ["false", "true"]
    assert value_candidates(boolean, "missing", ()) == []
    assert value_candidates(DEFS["move"], "exit_id", ["Hallway"]) == ["Hallway"]


def test_reference_candidates_empty_and_dangling_exit():
    assert reference_candidates(World.parse(_snapshot()), "") == []

    snapshot = _snapshot()
    parlor = snapshot["entities"][0]
    parlor["relationships"]["ExitTo"].append(
        {"target_id": "room:void", "edge": {"direction": "down"}}
    )
    parlor["relationships"]["ExitTo"].append({"target_id": HALL, "edge": {"direction": "north"}})
    player = next(e for e in snapshot["entities"] if e["id"] == PLAYER)
    player["relationships"]["Holding"].append({"target_id": APPLE, "edge": {}})

    pairs = reference_candidates(World.parse(snapshot), PLAYER)
    candidates = dict(pairs)
    assert candidates["room:void"] == "room:void"
    assert "a brass key" in candidates
    assert [cid for _name, cid in pairs].count(APPLE) == 1  # de-duplicated
    assert [cid for _name, cid in pairs].count(HALL) == 1  # de-duplicated


# ── dispatch (returns Rich Text) ──────────────────────────────────────────────
def _click_metas(text) -> list[str]:
    return [
        span.style.meta["@click"]
        for span in text.spans
        if isinstance(span.style, Style) and "@click" in span.style.meta
    ]


async def test_dispatch_meta_commands_render_text():
    repl = _repl()
    assert (await repl.dispatch("")).plain == ""
    assert "Parlor" in (await repl.dispatch("look")).plain
    assert "Marlow" in (await repl.dispatch("who")).plain
    assert "AP 5/5" in (await repl.dispatch("points")).plain
    assert (await repl.dispatch("refresh")).plain == "Refreshed."
    assert "parameters" in (await repl.dispatch("help move")).plain
    assert "Commands" in (await repl.dispatch("help")).plain
    assert "Usage" in (await repl.dispatch("play")).plain
    assert "You are now Pib" in (await repl.dispatch("play Pib")).plain


async def test_look_and_who_render_clickable_target_links():
    repl = _repl()
    room = await repl.dispatch("look")
    # The room, its occupants, and the exit are all clickable, keyed by entity id.
    assert {PARLOR, MARLOW, APPLE, HALL} <= {m.split("(")[1].rstrip(")").strip("'") for m in
                                             _click_metas(room)}
    who = await repl.dispatch("who")
    assert any(MARLOW in meta for meta in _click_metas(who))


async def test_dispatch_action_resolves_reference_and_submits():
    repl = _repl()
    message = await repl.dispatch("take item_id=a brass key")
    assert message.plain.startswith("» take")
    command = repl.backend.commands[-1]
    assert command["command_type"] == "take"
    assert command["payload"] == {"item_id": KEY}
    assert command["controller_generation"] == 2
    assert command["cost"] == {"action": 1, "focus": 0}
    assert command["lane"] == "world"


async def test_dispatch_action_with_string_argument_passes_through():
    repl = _repl()
    await repl.dispatch("say text=hello there")
    assert repl.backend.commands[-1]["payload"] == {"text": "hello there"}


async def test_dispatch_unresolved_reference_does_not_submit():
    repl = _repl()
    message = await repl.dispatch("take item_id=dragon")
    assert "don't see 'dragon'" in message.plain and "Did you mean" not in message.plain
    assert repl.backend.commands == []


async def test_dispatch_unresolved_reference_suggests_names():
    repl = _repl()
    message = await repl.dispatch("take item_id=appl")
    assert "Did you mean" in message.plain and "an apple" in message.plain
    assert repl.backend.commands == []


async def test_dispatch_action_requires_player_and_known_command():
    repl = _repl(player=False)
    assert "Pick a player first" in (await repl.dispatch("wait")).plain
    assert "don't understand" in (await repl.dispatch("flibber")).plain


# ── rendering fallbacks ───────────────────────────────────────────────────────
def test_render_fallbacks_without_player_or_room():
    repl = BunnylandRepl(RecordingBackend())  # empty world, no player
    assert repl.render_room().plain == "No room."
    assert repl.render_players().plain == "No players."
    assert "Pick a player first" in repl.render_points()


async def test_inventory_command_groups_and_tags_items():
    snapshot = _snapshot()
    player = next(e for e in snapshot["entities"] if e["id"] == PLAYER)
    player["relationships"]["Wearing"] = [{"target_id": APPLE, "edge": {}}]  # held KEY + worn APPLE
    player["relationships"]["Contains"] = [{"target_id": "item:3", "edge": {}}]  # kind-less item
    snapshot["entities"].append(
        {"id": "item:3", "components": {"IdentityComponent": {"name": "a plain rock"}},
         "relationships": {}}
    )
    repl = BunnylandRepl(RecordingBackend(snapshot))
    repl.world = World.parse(snapshot)
    repl.player_id = PLAYER

    for line in ("inventory", "inv"):  # both the full name and the alias work
        text = await repl.dispatch(line)
        assert "worn:" in text.plain and "held:" in text.plain and "carrying:" in text.plain
        assert "a brass key (item)" in text.plain and "an apple (food)" in text.plain
        assert "a plain rock" in text.plain and "a plain rock (" not in text.plain  # no kind tag
        assert {KEY, APPLE} <= {m.split("(")[1].rstrip(")").strip("'") for m in _click_metas(text)}


async def test_inventory_command_empty_and_without_player():
    repl = _repl()
    repl.player_id = MARLOW  # Marlow carries nothing
    assert (await repl.dispatch("inventory")).plain == "You aren't carrying anything."

    idle = BunnylandRepl(RecordingBackend())
    assert "Pick a player first" in (await idle.dispatch("inventory")).plain


def test_inventory_is_completable():
    assert "inventory" in _repl().complete("inv")


def _event(event_id, *, event_type="PingEvent", **fields):
    return {
        "type": "event",
        "data": {"event_type": event_type, "event": {"event_id": event_id, "note": event_id,
                                                      **fields}},
    }


def test_drain_events_filters_by_perception():
    repl = _repl()  # the player is in the Parlor
    messages = [
        _event("a", visibility="room", room_id=PARLOR, actor_id=MARLOW),
        _event("b", visibility="room", room_id=HALL, actor_id=MARLOW),
        _event("c", visibility="public"),
        _event("d", visibility="directed", actor_id=MARLOW, target_ids=[PLAYER]),
        _event("e", visibility="directed", actor_id=MARLOW, target_ids=[MARLOW]),
        _event("f", visibility="private", actor_id=PLAYER),
        _event("g", visibility="private", actor_id=MARLOW),
        _event("h", visibility="system"),
        _event("u", visibility="mystery", actor_id=MARLOW),  # unknown visibility: not perceived
        _event(None, visibility="public"),  # no id: skipped, not repeated
    ]
    shown = " | ".join(text.plain for text in repl.drain_events(messages))
    assert "note a" in shown and "note c" in shown and "note d" in shown and "note f" in shown
    for hidden in ("note b", "note e", "note g", "note h", "note u"):
        assert hidden not in shown


def test_drain_events_skips_telemetry_noise():
    repl = _repl()
    messages = [
        _event("p", event_type="ActionPointsChangedEvent", visibility="private", actor_id=PLAYER),
        _event("s", event_type="EntitySeenEvent", visibility="private", actor_id=PLAYER),
        _event("k", event_type="SpokeEvent", visibility="room", room_id=PARLOR, actor_id=MARLOW),
    ]
    shown = " | ".join(text.plain for text in repl.drain_events(messages))
    assert "note k" in shown  # real activity is narrated
    assert "note p" not in shown and "note s" not in shown  # telemetry is suppressed


def test_drain_events_narrates_own_system_actions_uniformly():
    repl = _repl()  # player is in the Parlor
    messages = [
        _event("m1", event_type="ActorMovedEvent", visibility="system", actor_id=PLAYER,
               from_room_id=PARLOR, to_room_id=HALL),
        _event("t1", event_type="ItemTakenEvent", visibility="system", actor_id=PLAYER,
               item_id=APPLE),
        _event("x1", event_type="CommandExecutedEvent", visibility="system", actor_id=PLAYER),
        _event("m2", event_type="ActorMovedEvent", visibility="system", actor_id=MARLOW,
               from_room_id=PARLOR, to_room_id=HALL),
    ]
    shown = " | ".join(text.plain for text in repl.drain_events(messages))
    assert "Pib: Actor moved" in shown  # your own move (system) is surfaced
    assert "Pib: Item taken" in shown and "an apple" in shown  # ...and so is your own take
    assert "Command executed" not in shown  # command lifecycle stays suppressed
    assert "Marlow" not in shown  # someone else's system-only action is not perceived


def test_drain_events_surfaces_own_command_rejections():
    repl = _repl()
    messages = [
        _event("r1", event_type="CommandRejectedEvent", visibility="system", actor_id=PLAYER,
               command_type="take", reason="that item is not portable"),
        _event("r2", event_type="CommandRejectedEvent", visibility="system", actor_id=MARLOW,
               command_type="take", reason="secret"),
    ]
    rendered = repl.drain_events(messages)
    shown = " | ".join(text.plain for text in rendered)
    assert "Command rejected" in shown and "not portable" in shown  # your failure explains itself
    assert "secret" not in shown  # another character's rejection is private to them
    assert str(rendered[0].style) == "dark_orange"  # rejections stand out in orange


def test_drain_events_dedupes_already_seen():
    repl = _repl()
    first = repl.drain_events([_event("x", visibility="public")])
    assert len(first) == 1
    assert repl.drain_events([_event("x", visibility="public")]) == []  # same event, not repeated
    again = repl.drain_events([_event("x", visibility="public"), _event("y", visibility="public")])
    assert len(again) == 1 and "note y" in again[0].plain


def test_humanize_event_type_splits_camelcase_and_handles_bare():
    assert _humanize_event_type("ResourceGatheredEvent") == "Resource gathered"
    assert _humanize_event_type("Event") == ""


def test_render_event_humanizes_and_resolves_names():
    repl = _repl()
    [text] = repl.drain_events([
        _event("g1", event_type="GaveEvent", visibility="room", room_id=PARLOR,
               actor_id=MARLOW, item_id=APPLE, tool_id="ghost", recipient_ids=[PLAYER],
               witness_ids=["nobody1", "nobody2"]),
    ])
    assert text.plain.startswith("Marlow: Gave")
    assert "an apple" in text.plain and "Pib" in text.plain  # item_id and _ids resolved to names
    assert "ghost" not in text.plain  # unresolvable id dropped
    assert "nobody" not in text.plain  # an _ids field with no resolvable names is dropped


def test_render_event_without_details_is_just_a_label():
    repl = _repl()
    bare = {"type": "event", "data": {"event_type": "WaitedEvent",
                                      "event": {"event_id": "w1", "visibility": "public"}}}
    [text] = repl.drain_events([bare])
    assert text.plain == "Waited"


def test_status_text_with_and_without_player():
    repl = _repl()
    status = repl.status_text()
    assert "Pib" in status and "test" in status and "AP 5/5" in status and "epoch 42s" in status

    idle = BunnylandRepl(RecordingBackend())
    assert idle.status_text().startswith("no player")


def test_render_room_includes_clickable_inventory():
    snapshot = _snapshot()
    player = next(e for e in snapshot["entities"] if e["id"] == PLAYER)
    player["relationships"]["Holding"].append({"target_id": APPLE, "edge": {}})  # a second item
    repl = BunnylandRepl(RecordingBackend(snapshot))
    repl.world = World.parse(snapshot)
    repl.player_id = PLAYER
    room = repl.render_room()
    assert "carrying: a brass key, an apple" in room.plain
    clicked = {meta.split("(")[1].rstrip(")").strip("'") for meta in _click_metas(room)}
    assert {KEY, APPLE} <= clicked


def test_render_room_skips_doors_and_omits_empty_exits():
    snapshot = _snapshot()
    parlor = snapshot["entities"][0]
    parlor["relationships"]["Contains"].append({"target_id": "door:1", "edge": {}})
    snapshot["entities"].append(
        {"id": "door:1", "components": {"DoorComponent": {}}, "relationships": {}}
    )
    parlor["relationships"]["ExitTo"] = []
    repl = BunnylandRepl(RecordingBackend(snapshot))
    repl.world = World.parse(snapshot)
    repl.player_id = PLAYER
    room = repl.render_room().plain
    assert "Pib (you)" in room
    assert "door" not in room.lower()
    assert "exits" not in room


def test_link_carries_clickable_meta_keyed_by_id():
    text = link("a brass key", KEY)
    assert text.plain == "a brass key"
    assert _click_metas(text) == [f"app.insert({KEY!r})"]


def test_render_room_multiple_exits_with_and_without_direction():
    snapshot = _snapshot()
    snapshot["entities"][0]["relationships"]["ExitTo"] = [
        {"target_id": HALL, "edge": {}},  # no direction -> bare name
        {"target_id": PARLOR, "edge": {"direction": "south"}},  # second exit -> comma joined
    ]
    repl = BunnylandRepl(RecordingBackend(snapshot))
    repl.world = World.parse(snapshot)
    repl.player_id = PLAYER
    room = repl.render_room().plain
    assert "exits: Hallway, south → Parlor" in room


def test_replinput_remember_dedupes_consecutive_and_ignores_blank():
    command = ReplInput()
    command.remember("look")
    command.remember("look")  # consecutive duplicate is not stored twice
    command.remember("")  # blank is ignored
    assert command.history == ["look"]


# ── select player ─────────────────────────────────────────────────────────────
async def test_select_player_claims_and_sets_control():
    repl = _repl(player=False)
    assert "You are now Pib" in await repl.select_player("Pib")
    assert repl.player_id == PLAYER and repl.control == ("controller:1", 2)


async def test_select_player_rejects_unknown_and_failed_claim():
    repl = _repl(player=False)
    assert "No such player" in await repl.select_player("Nobody")

    class NoClaimBackend(RecordingBackend):
        async def claim(self, player_id, world):
            return None

    repl = BunnylandRepl(NoClaimBackend())
    repl.world = World.parse(_snapshot())
    assert "Could not claim" in await repl.select_player("Pib")


def test_name_for_resolves_and_misses():
    repl = _repl()
    assert repl.name_for(APPLE) == "an apple"
    assert repl.name_for("missing") is None


async def test_refresh_drops_missing_player():
    snapshot = _snapshot()
    snapshot["entities"] = [e for e in snapshot["entities"] if e["id"] != PLAYER]
    repl = BunnylandRepl(RecordingBackend(snapshot))
    repl.player_id = PLAYER
    repl.control = ("controller:1", 2)
    await repl.refresh()
    assert repl.player_id == "" and repl.control is None


# ── the Textual app ───────────────────────────────────────────────────────────
def _log_text(app: BunnylandReplApp) -> str:
    from textual.widgets import RichLog

    log = app.query_one(RichLog)
    return "\n".join("".join(seg.text for seg in strip._segments) for strip in log.lines)


async def _submit(app, pilot, text: str) -> None:
    command = app.query_one(ReplInput)
    command.value = text
    command.cursor_position = len(text)
    await pilot.press("enter")
    await pilot.pause()


async def test_app_runs_meta_and_action_commands():
    app = BunnylandReplApp(RecordingBackend())
    async with app.run_test() as pilot:
        assert app.repl.backend.started
        await _submit(app, pilot, "")  # blank line is ignored
        await _submit(app, pilot, "play Pib")
        await _submit(app, pilot, "look")
        await _submit(app, pilot, "take item_id=a brass key")
        text = _log_text(app)
        assert "You are now Pib" in text
        assert "Parlor" in text
        assert app.repl.backend.commands[-1]["command_type"] == "take"


async def test_app_status_line_tracks_player():
    app = BunnylandReplApp(RecordingBackend())
    async with app.run_test() as pilot:
        assert app.sub_title.startswith("no player")
        await _submit(app, pilot, "play Pib")
        assert "Pib" in app.sub_title and "AP 5/5" in app.sub_title


async def test_app_status_line_updates_as_the_world_advances():
    import re

    class TickingBackend(RecordingBackend):
        """Each snapshot reports a later epoch and more action points."""

        def __init__(self) -> None:
            super().__init__()
            self.tick = 0

        async def fetch_snapshot(self) -> dict:
            self.tick += 1
            snapshot = _snapshot()
            snapshot["world_epoch"] = 100 * self.tick
            for entity in snapshot["entities"]:
                if entity["id"] == PLAYER:
                    entity["components"]["ActionPointsComponent"]["current"] = self.tick
            return snapshot

    def epoch(status: str) -> int:
        return int(re.search(r"epoch (\d+)s", status).group(1))

    def ap(status: str) -> int:
        return int(re.search(r"AP (\d+)/", status).group(1))

    app = BunnylandReplApp(TickingBackend())
    async with app.run_test():
        app.repl.player_id = PLAYER
        app.repl.control = ("controller:1", 2)
        await app._safe_refresh()
        before = app.sub_title
        await app._safe_refresh()
        after = app.sub_title
        assert epoch(after) > epoch(before)  # the clock advances in the status line
        assert ap(after) > ap(before)  # AP/FP track the latest snapshot


class NarratingBackend(RecordingBackend):
    """A backend whose event feed the test controls."""

    def __init__(self) -> None:
        super().__init__()
        self.events: list[dict] = []

    async def recent_events(self) -> list[dict]:
        return self.events


async def test_app_narrates_new_perceived_events():
    app = BunnylandReplApp(NarratingBackend())
    async with app.run_test():
        app.repl.player_id = PLAYER  # in the Parlor
        app.repl.backend.events = [_event("e1", visibility="room", room_id=PARLOR,
                                          actor_id=MARLOW)]
        await app._safe_refresh()
        assert "note e1" in _log_text(app)


async def test_app_primes_event_history_without_dumping_backlog():
    backend = NarratingBackend()
    backend.events = [_event("old", visibility="public")]  # already in the feed at startup
    app = BunnylandReplApp(backend)
    async with app.run_test():
        assert "note old" not in _log_text(app)  # the backlog is seeded, not printed


async def test_app_throttles_repeated_refresh_errors_then_reports_recovery():
    class FlakyBackend(RecordingBackend):
        def __init__(self) -> None:
            super().__init__()
            self.fail = True

        async def fetch_snapshot(self) -> dict:
            if self.fail:
                raise RuntimeError("down")
            return self.snapshot

    app = BunnylandReplApp(FlakyBackend())
    async with app.run_test():
        await app._safe_refresh()
        await app._safe_refresh()
        assert _log_text(app).count("down") == 1  # reported once, not every tick
        app.repl.backend.fail = False
        await app._safe_refresh()
        assert "reconnected" in _log_text(app)


async def test_app_quit_exits():
    app = BunnylandReplApp(RecordingBackend())
    exits: list[bool] = []
    async with app.run_test() as pilot:
        app.exit = lambda *a, **k: exits.append(True)  # type: ignore[method-assign]
        await _submit(app, pilot, "quit")
    assert exits == [True]


async def test_app_dispatch_errors_are_caught():
    app = BunnylandReplApp(RecordingBackend())
    async with app.run_test() as pilot:
        async def boom(_line):
            raise RuntimeError("kaboom")

        app.repl.dispatch = boom  # type: ignore[method-assign]
        await _submit(app, pilot, "anything")
        assert "kaboom" in _log_text(app)


async def test_app_refresh_errors_are_reported():
    class FailingBackend(RecordingBackend):
        async def fetch_snapshot(self) -> dict:
            raise RuntimeError("snapshot failed")

    app = BunnylandReplApp(FailingBackend())
    async with app.run_test():
        assert "snapshot failed" in _log_text(app)


async def test_app_click_inserts_target_name():
    app = BunnylandReplApp(RecordingBackend())
    async with app.run_test():
        app.action_insert(APPLE)
        assert app.query_one(ReplInput).value == "an apple"
        app.action_insert("missing")  # unknown id falls back to the raw reference
        assert "missing" in app.query_one(ReplInput).value


async def test_app_tab_completion_single_multi_and_none():
    app = BunnylandReplApp(RecordingBackend())
    async with app.run_test() as pilot:
        await _submit(app, pilot, "play Pib")
        command = app.query_one(ReplInput)

        command.value = "wai"
        command.cursor_position = 3
        await pilot.press("tab")
        assert command.value == "wait"  # single match completes fully

        command.value = "invent"
        command.cursor_position = 6
        await pilot.press("tab")
        assert command.value == "inventory"  # meta command completes from an unambiguous prefix

        command.value = "move "
        command.cursor_position = 5
        await pilot.press("tab")
        assert command.value.startswith("move ")  # common prefix; options listed in the log

        command.value = "zzz"
        command.cursor_position = 3
        await pilot.press("tab")
        assert command.value == "zzz"  # no match: unchanged

        # Several matches sharing a longer prefix complete up to that common prefix.
        app.repl.complete = lambda line: ["movement", "mover"]  # type: ignore[method-assign]
        command.value = "mo"
        command.cursor_position = 2
        await pilot.press("tab")
        assert command.value == "move"


async def test_app_history_navigation():
    app = BunnylandReplApp(RecordingBackend())
    async with app.run_test() as pilot:
        await _submit(app, pilot, "who")
        await _submit(app, pilot, "look")
        command = app.query_one(ReplInput)
        command.value = "dr"
        command.cursor_position = 2
        await pilot.press("up")
        assert command.value == "look"
        await pilot.press("up")
        assert command.value == "who"
        await pilot.press("down")
        assert command.value == "look"
        await pilot.press("down")
        assert command.value == "dr"  # back to the in-progress draft


async def test_app_history_navigation_noop_without_history():
    app = BunnylandReplApp(RecordingBackend())
    async with app.run_test() as pilot:
        command = app.query_one(ReplInput)
        await pilot.press("up")
        assert command.value == ""


async def test_app_history_file_round_trip(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    history = tmp_path / "bunnyland" / "repl-history"
    history.parent.mkdir(parents=True)
    history.write_text("who\nlook\n", encoding="utf-8")

    app = BunnylandReplApp(RecordingBackend())
    async with app.run_test() as pilot:
        assert app.query_one(ReplInput).history == ["who", "look"]
        await _submit(app, pilot, "points")
    assert history.read_text(encoding="utf-8").splitlines() == ["who", "look", "points"]


async def test_app_history_file_missing_and_unwritable(monkeypatch, tmp_path):
    # A missing history file is fine on load; an unwritable path is swallowed on save.
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "nope"))
    app = BunnylandReplApp(RecordingBackend())
    async with app.run_test():
        assert app.query_one(ReplInput).history == []

    monkeypatch.setattr(repl_app, "history_path", lambda: tmp_path)  # a directory: write fails
    app = BunnylandReplApp(RecordingBackend())
    async with app.run_test():
        pass


# ── lazy package exports + CLI wiring ─────────────────────────────────────────
def test_repl_package_lazily_exports_app_symbols():
    import bunnyland.repl as repl

    assert repl.main is repl_app.main
    assert repl.BunnylandReplApp is BunnylandReplApp
    unknown = "does_not_exist"
    with pytest.raises(AttributeError):
        getattr(repl, unknown)


def test_repl_module_entry_point_is_importable():
    import bunnyland.repl.__main__ as entry

    assert entry.main is repl_app.main


def test_available_generators_includes_the_demo_default():
    names = [generator.name for generator in available_generators()]
    assert "apartment-demo" in names and names == sorted(names)


def test_format_generator_lines_flags_seed_and_description():
    from types import SimpleNamespace

    generators = [
        SimpleNamespace(name="apartment-demo", uses_seed=False, description="a demo"),
        SimpleNamespace(name="recursive", uses_seed=True, description=""),
    ]
    assert format_generator_lines(generators) == [
        "apartment-demo *",
        "    a demo",
        "recursive",
        "",
        "* ignores --seed",
    ]


def test_main_lists_generators_and_exits(monkeypatch, capsys):
    from types import SimpleNamespace

    launched: list[bool] = []
    monkeypatch.setattr(
        repl_app, "available_generators",
        lambda: [SimpleNamespace(name="apartment-demo", uses_seed=False, description="a demo")],
    )
    monkeypatch.setattr(
        repl_app, "BunnylandReplApp",
        lambda backend: launched.append(True),  # must not be constructed
    )

    assert repl_app.main(["--list-generators"]) == 0
    assert launched == []
    assert "apartment-demo" in capsys.readouterr().out


def test_main_runs_remote_backend(monkeypatch):
    backends, runs = [], []

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

    monkeypatch.setattr(repl_app, "RemoteBackend", BackendStub)
    monkeypatch.setattr(repl_app, "BunnylandReplApp", AppStub)

    assert repl_app.main([
        "--server", "http://example.test",
        "--claim-fallback", "llm",
        "--claim-timeout-minutes", "10",
    ]) == 0
    assert runs == backends
    assert backends[0].server == "http://example.test"
    assert backends[0].timeout_seconds == 600


def test_main_runs_local_backend(monkeypatch):
    backends = []

    class BackendStub:
        def __init__(self, *, seed=None, generator=None, fallback_controller=None,
                     timeout_seconds=None):
            self.seed = seed
            self.generator = generator
            backends.append(self)

    class AppStub:
        def __init__(self, backend):
            self.backend = backend

        def run(self): ...

    monkeypatch.setattr(repl_app, "LocalBackend", BackendStub)
    monkeypatch.setattr(repl_app, "BunnylandReplApp", AppStub)

    assert repl_app.main(["--seed", "test seed", "--generator", "empty"]) == 0
    assert backends[0].seed == "test seed"
    assert backends[0].generator == "empty"
