"""A Textual terminal client for Bunnyland: the room on the left, the action menu on the
right, click to select, pick a target after the action — the toon client in a terminal.
"""

from __future__ import annotations

import argparse

from rich.text import Text
from textual import on
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.css.query import NoMatches
from textual.screen import ModalScreen
from textual.widgets import Footer, Header, Input, Label, OptionList, Select, Static
from textual.widgets.option_list import Option

from ..core.claim_timeout import normalize_claim_timeout
from ..terminal_generators import available_generators, format_generator_lines
from .backend import Backend, LocalBackend, RemoteBackend
from .events import EventNarrator
from .model import World, entity_icon, entity_name, fmt_points, has
from .verbs import ACTION_VERBS, Verb

REFRESH_SECONDS = 1.0
ACTIVITY_LIMIT = 8


def _queued_command_label(command: dict, actions: list[dict] | None = None) -> str:
    name = _queued_command_name(command, actions)
    lane = command.get("lane") or ""
    cost = _queued_command_cost(command)
    detail = _queued_command_detail(command)
    parts = [part for part in (cost, detail) if part]
    suffix = f" — {' · '.join(parts)}" if parts else ""
    lane_suffix = f" [{lane}]" if lane else ""
    return f"{name}{lane_suffix}{suffix}"


def _queued_command_name(command: dict, actions: list[dict] | None = None) -> str:
    for action in actions or []:
        if action.get("command_type") == command.get("command_type"):
            return _action_title(action)
    verb = next(
        (verb for verb in ACTION_VERBS if verb.cmd == command.get("command_type")),
        None,
    )
    if verb:
        return verb.label
    return str(command.get("command_type") or "command").replace("-", " ")


def _queued_command_cost(command: dict) -> str:
    cost = command.get("cost") or {}
    parts = []
    if cost.get("action"):
        parts.append(f"{cost['action']} AP")
    if cost.get("focus"):
        parts.append(f"{cost['focus']} FP")
    return " + ".join(parts) if parts else "free"


def _queued_command_detail(command: dict) -> str:
    payload = command.get("payload") or {}
    return ", ".join(
        f"{key}: {value}"
        for key, value in payload.items()
        if value is not None and value != ""
    )


def _legacy_action_view(verb: Verb) -> dict:
    arguments = []
    if verb.target_key and verb.target_kind:
        arguments.append({
            "key": verb.target_key,
            "title": verb.target_key.removesuffix("_id").replace("_", " "),
            "kind": "entity",
            "required": True,
            "target_group": verb.target_kind,
        })
    if verb.prompt:
        arguments.append({
            "key": verb.prompt,
            "title": verb.prompt.replace("_", " "),
            "kind": "string",
            "required": True,
            "target_group": None,
        })
    return {
        "command_type": verb.cmd,
        "tool_name": verb.tool,
        "title": verb.label,
        "lane": verb.lane,
        "cost": {"action": verb.ap, "focus": verb.fp},
        "arguments": arguments,
    }


def _action_title(action: dict) -> str:
    return str(
        action.get("title")
        or action.get("tool_name")
        or action.get("command_type")
        or "Action"
    )


def _action_tool(action: dict) -> str:
    return str(action.get("tool_name") or action.get("command_type") or "action")


def _action_command_type(action: dict) -> str:
    return str(action.get("command_type") or _action_tool(action))


def _action_lane(action: dict) -> str:
    lane = action.get("lane") or "world"
    return str(lane)


def _action_cost(action: dict) -> dict:
    cost = action.get("cost") or {}
    return {
        "action": int(cost.get("action") or 0),
        "focus": int(cost.get("focus") or 0),
    }


def _action_arguments(action: dict) -> list[dict]:
    return list(action.get("arguments") or [])


class TargetPicker(ModalScreen[str]):
    """Modal list of candidate targets for a verb; dismisses with the chosen id or None."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, verb: Verb | str, candidates) -> None:
        super().__init__()
        self.title_text = verb.label if isinstance(verb, Verb) else verb
        self.candidates = candidates

    def compose(self) -> ComposeResult:
        with Vertical(id="picker"):
            yield Label(f"{self.title_text} — choose a target", id="picker-title")
            if self.candidates:
                yield OptionList(
                    *[Option(f"{c.icon} {c.label}", id=c.value) for c in self.candidates],
                    id="picker-list",
                )
            else:
                yield Label("No valid targets nearby.", id="picker-empty")

    def on_mount(self) -> None:
        if self.candidates:
            self.query_one("#picker-list", OptionList).focus()

    @on(OptionList.OptionSelected, "#picker-list")
    def _chosen(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(event.option.id)

    def action_cancel(self) -> None:
        self.dismiss(None)


class TextPrompt(ModalScreen[str]):
    """Modal single-line input; dismisses with the text or None."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, title: str) -> None:
        super().__init__()
        self.title_text = title

    def compose(self) -> ComposeResult:
        with Vertical(id="prompt"):
            yield Label(self.title_text, id="prompt-title")
            yield Input(id="prompt-input")

    def on_mount(self) -> None:
        self.query_one("#prompt-input", Input).focus()

    @on(Input.Submitted, "#prompt-input")
    def _submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value or None)

    def action_cancel(self) -> None:
        self.dismiss(None)


class BunnylandTUI(App[None]):
    TITLE = "Bunnyland TUI"

    CSS = """
    #body { height: 1fr; }
    #world { width: 3fr; border-right: solid $panel; }
    #actions { width: 2fr; padding: 0 1; }
    #status { padding: 0 1; color: $text-muted; height: 1; }
    .col-title { padding: 0 1; color: $accent; text-style: bold; }
    #members, #doors, #activity, #verbs { height: auto; max-height: 1fr; }
    #doors { border-top: solid $panel; }
    #activity { border-top: solid $panel; }
    #queued { height: auto; max-height: 1fr; border-top: solid $panel; }
    #points { padding: 0 1; height: 1; }
    #picker, #prompt {
        width: 60; height: auto; max-height: 80%;
        border: thick $accent; background: $surface; padding: 1 2;
    }
    TargetPicker, TextPrompt { align: center middle; }
    #picker-title, #prompt-title { text-style: bold; padding-bottom: 1; }
    #picker-empty { color: $text-muted; }
    """

    BINDINGS = [
        ("r", "refresh", "Refresh"),
        ("f", "follow", "Follow player"),
        ("q", "quit", "Quit"),
    ]

    def __init__(self, backend: Backend) -> None:
        super().__init__()
        self.backend = backend
        self.world = World()
        self.player_id = ""
        self.control: tuple[str, int] | None = None
        self.view_room_id: str | None = None
        self.follow = True
        self.selected_id: str | None = None
        self._player_choice_ids: list[str] = []
        self.queued_commands: list[dict] = []
        self.action_views: list[dict] = []
        self._action_options: dict[str, dict] = {}
        self.activity_lines: list[Text] = []
        self._events = EventNarrator()
        self._events_primed = False
        self._refresh_error: str | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("Starting…", id="status")
        with Horizontal(id="body"):
            with Vertical(id="world"):
                yield Static("Room", id="room-title", classes="col-title")
                yield OptionList(id="members")
                yield Static("Doors", classes="col-title")
                yield OptionList(id="doors")
                yield Static("Activity", classes="col-title")
                yield OptionList(id="activity")
            with Vertical(id="actions"):
                yield Select([], prompt="— pick a player —", allow_blank=True, id="player")
                yield Static("", id="points")
                yield OptionList(id="verbs")
                yield Static("Queued actions", classes="col-title")
                yield OptionList(id="queued")
        yield Footer()

    async def on_mount(self) -> None:
        await self.backend.start()
        await self.refresh_world()
        self.set_interval(REFRESH_SECONDS, self.refresh_world)

    async def on_unmount(self) -> None:
        await self.backend.close()

    # ── data ────────────────────────────────────────────────────────────────
    async def refresh_world(self) -> None:
        try:
            self.world = World.parse(await self.backend.fetch_snapshot())
            events = await self.backend.recent_events()
            status = self.backend.label
        except Exception as exc:  # network hiccup, server restart, …
            message = f"⚠ {self.backend.label} — {exc}"
            if message != self._refresh_error:
                self._append_activity(Text(message, style="red"))
                self._refresh_error = message
            try:
                self.query_one("#status", Static).update(message)
            except NoMatches:
                return
            return
        if self._refresh_error is not None:
            self._append_activity(Text(f"✓ {self.backend.label} — reconnected", style="green"))
            self._refresh_error = None

        self._sync_players()
        if self.player_id and self.player_id not in self.world.entities:
            self.player_id = ""
            self.control = None
            self.action_views = []
        if self.player_id:
            await self._refresh_character_projection()
        else:
            self.action_views = []
        self.queued_commands = await self._fetch_queued_commands()
        if self.follow or not self.world.get(self.view_room_id):
            self.view_room_id = self.world.room_of(self.player_id) or self.world.first_room_id()

        epoch = self.world.epoch
        who = entity_name(self.world.get(self.player_id)) if self.player_id else "no player"
        try:
            self.query_one("#status", Static).update(f"{status} · epoch {epoch}s · {who}")
        except NoMatches:
            return
        self._render_room()
        self._render_actions()
        self._drain_activity(events, prime=not self._events_primed)
        self._events_primed = True

    async def _fetch_queued_commands(self) -> list[dict]:
        if not self.player_id:
            return []
        try:
            data = await self.backend.fetch_queued_commands(self.player_id)
        except Exception:
            return self.world.queued_for(self.player_id)
        if data.get("character_id") != self.player_id:
            return []
        return list(data.get("commands") or [])

    async def _refresh_character_projection(self) -> None:
        try:
            projection = await self.backend.fetch_character_projection(self.player_id)
        except Exception:
            self.action_views = []
            return
        if not projection or projection.get("character_id") != self.player_id:
            self.action_views = []
            return
        projected = World.parse(projection)
        self.world.target_groups = projected.target_groups
        self.action_views = list(projection.get("actions") or [])
        controller = projection.get("controller")
        if controller:
            self.control = (controller["controller_id"], int(controller.get("generation", 0)))

    def _sync_players(self) -> None:
        ids = [c["id"] for c in self.world.characters()]
        if ids == self._player_choice_ids:
            return
        self._player_choice_ids = ids
        select = self.query_one("#player", Select)
        select.set_options(
            [(entity_name(self.world.get(i)), i) for i in ids]
        )
        if self.player_id in ids:
            select.value = self.player_id

    # ── rendering ─────────────────────────────────────────────────────────────
    def _render_room(self) -> None:
        room = self.world.get(self.view_room_id)
        player_room = self.world.room_of(self.player_id)
        spectating = bool(self.player_id) and self.view_room_id != player_room
        title = entity_name(room) if room else "No room"
        if spectating:
            title += "  · spectating (f to follow)"
        self.query_one("#room-title", Static).update(title)

        members = self.query_one("#members", OptionList)
        members.clear_options()
        if room:
            shown = [
                m for m in self.world.room_members(self.view_room_id)
                if not has(m, "DoorComponent") and not has(m, "RoomComponent")
            ]
            shown.sort(key=lambda m: (m["components"].get("SpriteLayer", {}).get("layer", 20),
                                      entity_name(m).lower()))
            for m in shown:
                me = "  ← you" if m["id"] == self.player_id else ""
                members.add_option(Option(f"{entity_icon(m)} {entity_name(m)}{me}", id=m["id"]))
            self._restore_highlight(members)

        doors = self.query_one("#doors", OptionList)
        doors.clear_options()
        for target_id, direction, dest in self.world.doors(self.view_room_id):
            tag = f"[{direction}] " if direction else ""
            doors.add_option(Option(f"🚪 {tag}{entity_name(dest)}", id=f"door:{target_id}"))

    def _restore_highlight(self, members: OptionList) -> None:
        if not self.selected_id:
            return
        try:
            members.highlighted = members.get_option_index(self.selected_id)
        except Exception:
            pass

    def _render_actions(self) -> None:
        pts = self.world.points(self.player_id) if self.player_id else {"has": False}
        if pts.get("has"):
            line = (f"⚡ {fmt_points(pts['ap'])}/{fmt_points(pts['ap_max'])} AP   "
                    f"🔹 {fmt_points(pts['fp'])}/{fmt_points(pts['fp_max'])} FP")
        else:
            line = "Pick a player to see their actions."
        self.query_one("#points", Static).update(line)

        verbs = self.query_one("#verbs", OptionList)
        verbs.clear_options()
        self._action_options = {}
        for index, action in enumerate(self._available_actions()):
            cost_view = _action_cost(action)
            affordable = (
                pts.get("has")
                and pts["ap"] >= cost_view["action"]
                and pts["fp"] >= cost_view["focus"]
            )
            cost = (" · ".join(
                [f"{cost_view['action']} AP"] * bool(cost_view["action"])
                + [f"{cost_view['focus']} FP"] * bool(cost_view["focus"])
            ) or "free")
            tgt = " ⌖" if any(arg.get("target_group") for arg in _action_arguments(action)) else ""
            option_id = _action_tool(action)
            if option_id in self._action_options:
                option_id = f"{option_id}:{index}"
            self._action_options[option_id] = action
            verbs.add_option(
                Option(f"{_action_title(action)}{tgt}  ({cost})", id=option_id,
                       disabled=not affordable)
            )

        queued = self.query_one("#queued", OptionList)
        queued.clear_options()
        if not self.queued_commands:
            queued.add_option(Option("No queued actions.", id="queued-empty", disabled=True))
            return
        for index, command in enumerate(self.queued_commands):
            queued.add_option(
                Option(
                    _queued_command_label(command, self._available_actions()),
                    id=f"queued:{index}",
                    disabled=True,
                )
            )

    def _available_actions(self) -> list[dict]:
        return self.action_views or [_legacy_action_view(verb) for verb in ACTION_VERBS]

    def _drain_activity(self, events: list[dict], *, prime: bool = False) -> None:
        lines = self._events.drain_events(
            events,
            player_id=self.player_id,
            room_of=self.world.room_of,
            name_for=self._name_for,
        )
        if prime:
            self._render_activity()
            return
        for line in lines:
            self._append_activity(line)

    def _append_activity(self, line: Text) -> None:
        self.activity_lines.append(line)
        self.activity_lines = self.activity_lines[-ACTIVITY_LIMIT:]
        self._render_activity()

    def _render_activity(self) -> None:
        try:
            activity = self.query_one("#activity", OptionList)
        except NoMatches:
            return
        activity.clear_options()
        if not self.activity_lines:
            activity.add_option(Option("No recent activity.", id="activity-empty", disabled=True))
            return
        for index, line in enumerate(self.activity_lines):
            activity.add_option(Option(line, id=f"activity:{index}", disabled=True))

    def _name_for(self, entity_id: str) -> str | None:
        entity = self.world.get(entity_id)
        return entity_name(entity) if entity else None

    # ── events ──────────────────────────────────────────────────────────────────
    @on(Select.Changed, "#player")
    async def _player_changed(self, event: Select.Changed) -> None:
        new_id = "" if event.value is Select.BLANK else str(event.value)
        if new_id == self.player_id:
            return
        self.player_id = new_id
        self.selected_id = None
        self.follow = True
        self.control = await self.backend.claim(new_id, self.world) if new_id else None
        await self.refresh_world()

    @on(OptionList.OptionSelected, "#members")
    def _member_selected(self, event: OptionList.OptionSelected) -> None:
        self.selected_id = event.option.id

    @on(OptionList.OptionSelected, "#doors")
    def _door_selected(self, event: OptionList.OptionSelected) -> None:
        self.view_room_id = event.option.id.removeprefix("door:")
        self.follow = False
        self._render_room()

    @on(OptionList.OptionSelected, "#verbs")
    def _verb_selected(self, event: OptionList.OptionSelected) -> None:
        action = self._action_options.get(str(event.option.id))
        if action is None:
            legacy = next((verb for verb in ACTION_VERBS if verb.tool == event.option.id), None)
            action = _legacy_action_view(legacy) if legacy else None
        if action:
            self.run_worker(self._do_action(action), exclusive=True)

    # ── actions ─────────────────────────────────────────────────────────────────
    async def _do_verb(self, verb: Verb) -> None:
        await self._do_action(_legacy_action_view(verb))

    async def _do_action(self, action: dict) -> None:
        if not self.player_id or not self.control:
            return
        payload: dict = {}
        for argument in _action_arguments(action):
            key = argument.get("key")
            if not key:
                continue
            target_group = argument.get("target_group")
            if target_group:
                candidates = self.world.target_candidates(self.player_id, target_group)
                choice = await self.push_screen_wait(
                    TargetPicker(_action_title(action), candidates)
                )
                if not choice:
                    return
                payload[key] = choice
                continue
            if argument.get("required"):
                label = argument.get("title") or key
                value = await self.push_screen_wait(
                    TextPrompt(f"{_action_title(action)} — {label}")
                )
                if not value:
                    return
                payload[key] = value

        cost = _action_cost(action)
        await self.backend.submit({
            "character_id": self.player_id,
            "controller_id": self.control[0],
            "controller_generation": self.control[1],
            "command_type": _action_command_type(action),
            "payload": payload,
            "cost": cost,
            "lane": _action_lane(action),
            "on_insufficient_points": "queue",
        })
        await self.refresh_world()

    async def action_refresh(self) -> None:
        await self.refresh_world()

    def action_follow(self) -> None:
        self.follow = True
        self.view_room_id = self.world.room_of(self.player_id)
        self._render_room()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="bunnyland-tui", description=__doc__)
    parser.add_argument(
        "--server", help="connect to a running server (e.g. http://localhost:8765)"
    )
    parser.add_argument("--seed", default="a quiet marsh", help="seed for a locally hosted world")
    parser.add_argument(
        "--generator", default="apartment-demo", help="generator for a locally hosted world"
    )
    parser.add_argument(
        "--list-generators",
        action="store_true",
        help="list the available world generators (demo worlds) for local play and exit",
    )
    parser.add_argument(
        "--claim-fallback",
        choices=("suspend", "llm"),
        default=None,
        help="controller fallback when this TUI claim times out",
    )
    parser.add_argument(
        "--claim-timeout-minutes",
        type=int,
        default=None,
        help="claim timeout override in minutes, between 5 and 60",
    )
    args = parser.parse_args(argv)
    if args.list_generators:
        for line in format_generator_lines(available_generators()):
            print(line)
        return 0

    timeout_seconds = (
        normalize_claim_timeout(args.claim_timeout_minutes * 60)
        if args.claim_timeout_minutes is not None
        else None
    )

    backend: Backend = (
        RemoteBackend(
            args.server,
            fallback_controller=args.claim_fallback,
            timeout_seconds=timeout_seconds,
        ) if args.server
        else LocalBackend(
            seed=args.seed,
            generator=args.generator,
            fallback_controller=args.claim_fallback,
            timeout_seconds=timeout_seconds,
        )
    )
    BunnylandTUI(backend).run()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
