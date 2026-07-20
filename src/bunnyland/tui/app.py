"""A Textual terminal client for Bunnyland: the room on the left, the action menu on the
right, click to select, pick a target after the action — the toon client in a terminal.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from dataclasses import dataclass

from rich.text import Text
from textual import on
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.css.query import NoMatches
from textual.screen import ModalScreen
from textual.widgets import Button, Footer, Header, Input, Label, OptionList, Select, Static
from textual.widgets.option_list import Option

from ..core.actions import action_icon_for
from ..core.claim_timeout import normalize_claim_timeout
from ..imagegen.affordance import DELIVER_EMOJI, FAIL_EMOJI, REQUEST_EMOJI
from ..imagegen.feed import latest_image_completion, latest_image_failure
from ..server.models import CharacterSummaryView
from ..terminal_config import (
    TerminalConfigError,
    load_terminal_config,
    resolve_terminal_chat_config,
    save_terminal_config,
)
from ..terminal_generators import available_generators, format_generator_lines
from .backend import Backend, ControlClaim, LocalBackend, RemoteBackend
from .events import EventNarrator
from .generator_selector import DEFAULT_LOCAL_GENERATOR, DEFAULT_LOCAL_SEED, WorldGeneratorSelector
from .model import Target, World, entity_icon, entity_name, fmt_points, has
from .screens import (
    CharacterPickerScreen,
    CharacterSheetScreen,
    ConversationScreen,
    TerminalSetupScreen,
)
from .splash import IntroSplash

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


def _action_icon(action: dict) -> str:
    return str(action.get("icon") or action_icon_for(_action_command_type(action)))


def _queued_command_name(command: dict, actions: list[dict] | None = None) -> str:
    for action in actions or []:
        if action.get("command_type") == command.get("command_type"):
            return _action_title(action)
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
        f"{key}: {value}" for key, value in payload.items() if value is not None and value != ""
    )


def _action_title(action: dict) -> str:
    return str(
        action.get("title") or action.get("tool_name") or action.get("command_type") or "Action"
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


def _action_available(action: dict, *, fallback: bool = True) -> bool:
    """Whether the projection marked this action available for the character.

    Legacy/offline action views have no ``available`` field, so callers pass a sensible
    ``fallback`` (e.g. point affordability) for those.
    """
    available = action.get("available")
    return fallback if available is None else bool(available)


def _action_unavailable_reason(action: dict) -> str:
    return str(action.get("unavailable_reason") or "")


@dataclass(frozen=True)
class FormField:
    """One prompted action argument and the widget that should collect it."""

    key: str
    label: str
    kind: str
    required: bool
    candidates: tuple[Target, ...] | None = None
    initial_value: str | None = None


def _control_claim(value) -> ControlClaim | None:
    if value is None:
        return None
    if isinstance(value, ControlClaim):
        return value
    if isinstance(value, (tuple, list)) and len(value) >= 2:
        return ControlClaim(controller_id=str(value[0]), generation=int(value[1]))
    return None


class ActionForm(ModalScreen[dict | None]):
    """Modal form that collects an action's arguments in one screen: a dropdown for
    target and boolean fields, a numeric input for numbers, and a text input otherwise.
    Dismisses with the payload dict, or ``None`` when cancelled.
    """

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, title: str, fields: list[FormField]) -> None:
        super().__init__()
        self.title_text = title
        self.fields = fields

    def compose(self) -> ComposeResult:
        with Vertical(id="form"):
            yield Label(self.title_text, id="form-title")
            for field in self.fields:
                label = f"{field.label} *" if field.required else field.label
                yield Label(label, classes="form-label")
                yield self._field_widget(field)
            yield Label("", id="form-error")
            with Horizontal(id="form-buttons"):
                yield Button("Submit", id="form-submit", variant="primary")
                yield Button("Cancel", id="form-cancel")

    def _field_widget(self, field: FormField):
        widget_id = f"field-{field.key}"
        if field.candidates is not None:
            return Select(
                [(f"{c.icon} {c.label}", c.value) for c in field.candidates],
                id=widget_id,
                prompt=f"— choose {field.label} —",
                allow_blank=True,
            )
        if field.kind == "boolean":
            return Select(
                [("yes", "true"), ("no", "false")],
                id=widget_id,
                prompt="— choose —",
                allow_blank=True,
            )
        return Input(id=widget_id, type="number" if field.kind == "number" else "text")

    def on_mount(self) -> None:
        first_widget = None
        for field in self.fields:
            # Every field yields a widget with this id in compose(), so the lookup always
            # resolves here.
            widget = self.query_one(f"#field-{field.key}")
            if field.initial_value is not None:
                if isinstance(widget, Select):
                    widget.value = field.initial_value
                else:
                    widget.value = field.initial_value
            if first_widget is None:
                first_widget = widget
        if first_widget is not None:
            first_widget.focus()

    @on(Input.Submitted)
    def _input_submitted(self, _event: Input.Submitted) -> None:
        self._try_submit()

    @on(Button.Pressed, "#form-submit")
    def _submit_pressed(self, _event: Button.Pressed) -> None:
        self._try_submit()

    @on(Button.Pressed, "#form-cancel")
    def _cancel_pressed(self, _event: Button.Pressed) -> None:
        self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)

    def _value_for(self, field: FormField) -> str | None:
        widget = self.query_one(f"#field-{field.key}")
        if isinstance(widget, Select):
            return None if widget.value is Select.BLANK else str(widget.value)
        return widget.value.strip() or None

    def _try_submit(self) -> None:
        payload: dict = {}
        for field in self.fields:
            value = self._value_for(field)
            if field.required and value is None:
                self.query_one("#form-error", Label).update(f"{field.label} is required.")
                return
            if value is not None:
                payload[field.key] = value
        self.dismiss(payload)


class HelpScreen(ModalScreen[None]):
    """Modal cheat-sheet of the key bindings and how to play, mirroring the REPL's
    ``help`` command so a TUI player can discover the controls without leaving the app.
    """

    BINDINGS = [("escape", "close", "Close"), ("question_mark", "close", "Close")]

    HELP_BODY = (
        "Bunnyland TUI — controls\n"
        "\n"
        "  r   Refresh the world now\n"
        f"  i   {REQUEST_EMOJI} Request an image of your current scene\n"
        "  s   Open the selected (or your own) character sheet\n"
        "  c   Chat with the selected (or your own) character\n"
        "  x   Clear the selected action target\n"
        "  ?   Show this help\n"
        "  q   Quit\n"
        "\n"
        "Playing:\n"
        "  • Pick a character from the dropdown to claim and play it.\n"
        "  • Click a verb in the action list to act; a form collects any arguments.\n"
        "  • Click a member or inventory item to target it, a door to travel, or a\n"
        "    queued action to cancel it.\n"
        "  • Search the action list with the filter box; unavailable actions stay listed,\n"
        "    de-emphasized, and can still be queued."
    )

    def compose(self) -> ComposeResult:
        with Vertical(id="form"):
            yield Label("Help", id="form-title")
            yield Static(self.HELP_BODY)
            with Horizontal(id="form-buttons"):
                yield Button("Close", id="help-close", variant="primary")

    @on(Button.Pressed, "#help-close")
    def _close_pressed(self, _event: Button.Pressed) -> None:
        self.dismiss(None)

    def action_close(self) -> None:
        self.dismiss(None)


class BunnylandTUI(App[None]):
    TITLE = "Bunnyland TUI"

    CSS = """
    #body { height: 1fr; }
    #world { width: 3fr; border-right: solid $panel; }
    #actions { width: 2fr; height: 1fr; padding: 0 1; }
    #status { padding: 0 1; color: $text-muted; height: 1; }
    .col-title { padding: 0 1; color: $accent; text-style: bold; }
    #doors-title, #activity-title, #queued-title { border-top: solid $panel; }
    #members, #doors, #activity { height: auto; max-height: 1fr; }
    #verbs { height: auto; max-height: 12; }
    #queued { height: 1fr; min-height: 4; }
    #character-control-row { height: 3; }
    #character-label { width: 10; content-align: left middle; }
    #player { width: 1fr; }
    #character-release, #claim-release { width: 8; min-width: 8; }
    #play-hint { padding: 0 1; color: $text-muted; height: 1; }
    #points { padding: 0 1; height: 1; }
    #target-row { height: 3; }
    #target-label { width: 1fr; content-align: left middle; color: $text-muted; }
    #target-clear { width: 14; min-width: 14; }
    #action-filter-row { height: 3; }
    #action-filter { width: 1fr; }
    #action-filter-clear { width: 9; min-width: 9; }
    #form {
        width: 60; height: auto; max-height: 80%;
        border: thick $accent; background: $surface; padding: 1 2;
    }
    ActionForm { align: center middle; }
    #form-title { text-style: bold; padding-bottom: 1; }
    .form-label { color: $text-muted; padding-top: 1; }
    #form-error { color: $error; }
    #form-buttons { height: auto; padding-top: 1; }
    #form-submit { margin-right: 1; }
    """

    BINDINGS = [
        ("r", "refresh", "Refresh"),
        ("i", "request_image", f"{REQUEST_EMOJI} Image"),
        ("s", "open_sheet", "Open Sheet"),
        ("c", "open_chat", "Chat"),
        ("x", "clear_target", "Clear Target"),
        ("question_mark", "help", "Help"),
        ("q", "quit", "Quit"),
    ]

    def __init__(
        self, backend: Backend, *, show_intro: bool = False, show_icons: bool = True
    ) -> None:
        super().__init__()
        self.backend = backend
        self.show_intro = show_intro
        self.show_icons = show_icons
        self.world = World()
        self.player_id = ""
        self.control: ControlClaim | None = None
        self.view_room_id: str | None = None
        self.character_list: list[CharacterSummaryView] = []
        self.selected_id: str | None = None
        self._player_choice_ids: list[str] = []
        self.queued_commands: list[dict] = []
        self.queue_timing: dict = {}
        self.action_views: list[dict] = []
        self._action_options: dict[str, dict] = {}
        self._verbs_signature: tuple[tuple[str, str, bool], ...] = ()
        self._queued_signature: tuple[tuple[str, str], ...] = ()
        self._points_line = ""
        self.action_filter = ""
        self.activity_lines: list[Text] = []
        self._events = EventNarrator()
        self._events_primed = False
        self._event_image_url = ""
        self._event_image_failure_epoch = -1
        self._refresh_error: str | None = None
        self._refresh_task: asyncio.Task[None] | None = None
        self._live_task: asyncio.Task | None = None
        self._live_ready = False
        self.show_generator_selector = False
        self.needs_chat_setup = False

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("Starting…", id="status")
        with Horizontal(id="body"):
            with Vertical(id="world"):
                yield Static("Room", id="room-title", classes="col-title")
                yield OptionList(id="members")
                yield Static("Doors", id="doors-title", classes="col-title")
                yield OptionList(id="doors")
                yield Static("Inventory", id="inventory-title", classes="col-title")
                yield OptionList(id="inventory")
                yield Static("Activity", id="activity-title", classes="col-title")
                yield OptionList(id="activity")
            with Vertical(id="actions"):
                with Horizontal(id="character-control-row"):
                    yield Static("Character", id="character-label")
                    yield Select(
                        [],
                        prompt="— select to play —",
                        allow_blank=True,
                        id="player",
                    )
                    yield Button("Claim", id="character-release", disabled=True)
                    yield Button("Release", id="claim-release", disabled=True)
                    if self.backend.supports_image_requests:
                        yield Button(f"{REQUEST_EMOJI} Image", id="request-image")
                    if self.backend.supports_character_sheets:
                        yield Button("▣ Sheet", id="open-sheet")
                    if self.backend.supports_character_chat or self.needs_chat_setup:
                        yield Button("Chat", id="open-chat")
                yield Static("Select a character to play as.", id="play-hint")
                yield Static("", id="points")
                with Horizontal(id="target-row"):
                    yield Static("Target: none", id="target-label")
                    yield Button("Clear Target", id="target-clear", disabled=True)
                with Horizontal(id="action-filter-row"):
                    yield Input(placeholder="Search actions", id="action-filter")
                    yield Button("Clear", id="action-filter-clear")
                yield OptionList(id="verbs")
                yield Static("Queued actions", id="queued-title", classes="col-title")
                yield OptionList(id="queued")
        yield Footer()

    async def on_mount(self) -> None:
        if self.needs_chat_setup and isinstance(self.backend, LocalBackend):
            if self.show_intro:
                self.push_screen(IntroSplash(), callback=lambda _: self._show_chat_setup())
            else:
                self._show_chat_setup()
            return
        if self.show_generator_selector and isinstance(self.backend, LocalBackend):
            if self.show_intro:
                self.push_screen(IntroSplash(), callback=lambda _: self._show_generator_selector())
            else:
                self._show_generator_selector()
            return
        if self.show_intro:
            self.push_screen(IntroSplash())
        await self._start_backend()

    def _show_chat_setup(self) -> None:
        self.push_screen(TerminalSetupScreen(), callback=self._chat_setup_selected)

    def _chat_setup_selected(self, config) -> None:
        if config is None:
            self.exit()
            return
        try:
            save_terminal_config(config)
            settings = resolve_terminal_chat_config(config)
            settings.validate_credentials()
        except TerminalConfigError as exc:
            self.notify(str(exc), severity="error", timeout=8)
            self._show_chat_setup()
            return
        self.backend.chat_config = settings
        self.needs_chat_setup = False
        if self.show_generator_selector:
            self._show_generator_selector()
        else:
            self.run_worker(self._start_backend(), exclusive=True)

    def _show_generator_selector(self) -> None:
        self.push_screen(
            WorldGeneratorSelector(
                available_generators(),
                initial_generator=self.backend.generator_name,
                initial_seed=self.backend.seed,
            ),
            callback=self._generator_selected,
        )

    def _generator_selected(self, selection) -> None:
        if selection is None:
            self.exit()
            return
        self.backend.configure_world(seed=selection.seed, generator=selection.generator)
        self.run_worker(self._start_backend(), exclusive=True)

    async def _start_backend(self) -> None:
        await self.backend.start()
        await self.refresh_world()
        self.set_interval(REFRESH_SECONDS, self._poll_refresh_world)

    async def on_unmount(self) -> None:
        self._stop_live_updates()
        if self._refresh_task is not None:
            self._refresh_task.cancel()
            await asyncio.gather(self._refresh_task, return_exceptions=True)
        await self.backend.close()

    async def _poll_refresh_world(self) -> None:
        if not self._live_ready:
            await self.refresh_world()

    def _stop_live_updates(self) -> None:
        self._live_ready = False
        if self._live_task is not None:
            self._live_task.cancel()
        self._live_task = None

    def _restart_live_updates(self) -> None:
        self._stop_live_updates()
        if not self.player_id or not self.backend.supports_live_updates():
            return

        async def on_message(frame: dict) -> None:
            if frame.get("type") != "heartbeat":
                await self.refresh_world()

        async def on_state(state: str) -> None:
            self._live_ready = state == "live"
            if state == "fallback":
                await self.refresh_world()

        self._live_task = asyncio.create_task(
            self.backend.watch_updates(
                self.player_id,
                self.control,
                on_message,
                on_state,
            )
        )

    def _main_query_one(self, selector: str, expect_type=None):
        try:
            return self.query_one(selector, expect_type)
        except NoMatches as first_error:
            for screen in self.get_screen_stack():
                try:
                    return screen.query_one(selector, expect_type)
                except NoMatches:
                    continue
            raise first_error

    # ── data ────────────────────────────────────────────────────────────────
    async def refresh_world(self) -> None:
        task = self._refresh_task
        if task is None:
            task = asyncio.create_task(self._refresh_world_once())
            self._refresh_task = task
        try:
            await asyncio.shield(task)
        finally:
            if task.done() and self._refresh_task is task:
                self._refresh_task = None

    async def _refresh_world_once(self) -> None:
        # The picker is sourced from the claim lobby; the world is only ever the player's
        # own perceived room (their character projection), never the full map.
        try:
            self.character_list = await self.backend.fetch_character_list()
            projection = (
                await self.backend.fetch_character_projection(self.player_id)
                if self.player_id
                else None
            )
            events = await self.backend.recent_events(self.player_id)
            status = self.backend.label
        except Exception as exc:  # network hiccup, server restart, …
            message = f"⚠ {self.backend.label} — {exc}"
            if message != self._refresh_error:
                self._append_activity(Text(message, style="red"))
                self._refresh_error = message
            try:
                self._main_query_one("#status", Static).update(message)
            except NoMatches:
                return
            return
        if self._refresh_error is not None:
            self._append_activity(Text(f"✓ {self.backend.label} — reconnected", style="green"))
            self._refresh_error = None

        known_ids = {summary.character_id for summary in self.character_list}
        if self.player_id and self.player_id not in known_ids:
            self.player_id = ""
            self.control = None
            projection = None
        if self.player_id and projection and projection.get("character_id") == self.player_id:
            projected_world = World.parse(projection)
            projected_control = projected_world.control(self.player_id)
            self.control = _control_claim(self.control)
            if self.control:
                current_control = self.control
                if projected_control and projected_control[0] == current_control.controller_id:
                    self.control = ControlClaim(
                        controller_id=projected_control[0],
                        generation=projected_control[1],
                        claim_id=current_control.claim_id,
                        claim_secret=current_control.claim_secret,
                        active=current_control.active,
                    )
                else:
                    self.control = (
                        ControlClaim(
                            controller_id=projected_control[0] if projected_control else "",
                            generation=projected_control[1] if projected_control else 0,
                            claim_id=current_control.claim_id,
                            claim_secret=current_control.claim_secret,
                            active=False,
                        )
                        if current_control.claim_id and current_control.claim_secret
                        else None
                    )
            self.world = projected_world
            self.action_views = list(projection.get("actions") or [])
        else:
            if self.player_id and projection is None and self.control is not None:
                self._stop_live_updates()
                self.control = None
                self._append_activity(
                    Text("Claim expired. Claim this character again.", style="dark_orange")
                )
            self.world = World()
            self.action_views = []
        try:
            self._sync_players()
            self._render_play_state()
        except NoMatches:
            return
        self.queued_commands = await self._fetch_queued_commands(projection)
        self.view_room_id = self.world.room_of(self.player_id)

        epoch = self.world.epoch
        who = entity_name(self.world.get(self.player_id)) if self.player_id else "no character"
        try:
            self._main_query_one("#status", Static).update(f"{status} · epoch {epoch}s · {who}")
        except NoMatches:
            return
        self._render_room()
        self._render_inventory()
        self._render_actions()
        self._drain_activity(events, prime=not self._events_primed)
        self._events_primed = True

    async def _fetch_queued_commands(self, projection: dict | None = None) -> list[dict]:
        if not self.player_id:
            return []
        if projection is not None and "queued_commands" in projection:
            data = {
                "character_id": projection.get("character_id"),
                "world_epoch": projection.get("world_epoch", 0),
                "commands": projection.get("queued_commands") or [],
            }
        else:
            try:
                data = await self.backend.fetch_queued_commands(self.player_id)
            except Exception:
                # Keep the last-known queue on a transient fetch failure rather than
                # blanking it.
                return self.queued_commands
        if data.get("character_id") != self.player_id:
            return []
        self.queue_timing = {
            key: data.get(key)
            for key in (
                "generated_at_unix",
                "next_tick_at_unix",
                "tick_seconds",
                "time_scale",
                "game_seconds_per_tick",
            )
        }
        return list(data.get("commands") or [])

    def _sync_players(self) -> None:
        ids = [summary.character_id for summary in self.character_list]
        select = self._main_query_one("#player", Select)
        if ids != self._player_choice_ids:
            self._player_choice_ids = ids
            select.set_options(
                [(summary.name, summary.character_id) for summary in self.character_list]
            )
        self._player_choice_ids = ids
        if self.player_id in ids:
            select.value = self.player_id
        else:
            select.clear()

    def _render_play_state(self) -> None:
        playing = bool(self.player_id)
        control_button = self._main_query_one("#character-release", Button)
        control_button.disabled = not playing
        if self.control is None:
            control_button.label = "Claim"
        elif self.control.active:
            control_button.label = "Idle"
        else:
            control_button.label = "Resume"
        release = self._main_query_one("#claim-release", Button)
        release.label = "Release"
        release.disabled = not bool(self.control)
        hint = self._main_query_one("#play-hint", Static)
        if playing:
            name = entity_name(self.world.get(self.player_id)) or self.player_id
            hint.update(f"Playing: {name}.")
        elif self.character_list:
            hint.update("Select a character to play as.")
        else:
            hint.update("Connect to a world with playable characters.")
        self._sync_target_controls()

    # ── rendering ─────────────────────────────────────────────────────────────
    def _render_room(self) -> None:
        room = self.world.get(self.view_room_id)
        title = entity_name(room) if room else "No room"
        self._main_query_one("#room-title", Static).update(title)

        members = self._main_query_one("#members", OptionList)
        members.clear_options()
        if room:
            shown = [
                m
                for m in self.world.room_members(self.view_room_id)
                if not has(m, "DoorComponent") and not has(m, "RoomComponent")
            ]
            shown.sort(
                key=lambda m: (
                    m["components"].get("SpriteLayerComponent", {}).get("layer", 20),
                    entity_name(m).lower(),
                )
            )
            for m in shown:
                me = "  ← you" if m["id"] == self.player_id else ""
                members.add_option(Option(f"{entity_icon(m)} {entity_name(m)}{me}", id=m["id"]))
            self._restore_highlight(members)
        else:
            members.add_option(
                Option("Select a character above to play as and see their room.", disabled=True)
            )

        doors = self._main_query_one("#doors", OptionList)
        doors.clear_options()
        for target_id, direction, dest in self.world.doors(self.view_room_id):
            # Own-room view: the projection names the direction, not the room it leads to
            # (you learn that by going there), so label each exit by its direction.
            label = direction or (entity_name(dest) if dest else target_id)
            doors.add_option(Option(f"🚪 {label}", id=f"door:{target_id}"))
        if not room:
            doors.add_option(Option("No room until a character is selected.", disabled=True))

    def _render_inventory(self) -> None:
        inventory = self._main_query_one("#inventory", OptionList)
        inventory.clear_options()
        items = self.world.target_groups.get("inventory", []) if self.player_id else []
        if not items:
            hint = (
                "Nothing carried."
                if self.player_id
                else "Select a character to see what they carry."
            )
            inventory.add_option(Option(hint, disabled=True))
            return
        for item in items:
            inventory.add_option(Option(f"{item.icon} {item.label}", id=f"inv:{item.value}"))
        self._sync_target_controls()

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
            line = Text()
            line.append("⚡", style="dark_orange" if pts["ap"] > 0 else "dim")
            line.append(
                f" {fmt_points(pts['ap'])}/{fmt_points(pts['ap_max'])} AP",
                style="dark_orange",
            )
            line.append("   ")
            line.append("🔹", style="cyan" if pts["fp"] > 0 else "dim")
            line.append(
                f" {fmt_points(pts['fp'])}/{fmt_points(pts['fp_max'])} FP",
                style="cyan",
            )
        else:
            line = "Select a character to play as and see their actions."
        points_line = line.plain if isinstance(line, Text) else line
        if points_line != self._points_line:
            self._main_query_one("#points", Static).update(line)
            self._points_line = points_line

        actions = self._filtered_actions()
        action_options: dict[str, dict] = {}
        verb_entries: list[tuple[str, Text, str]] = []
        for index, action in enumerate(actions):
            cost_view = _action_cost(action)
            affordable = (
                pts.get("has")
                and pts["ap"] >= cost_view["action"]
                and pts["fp"] >= cost_view["focus"]
            )
            available = _action_available(action, fallback=bool(affordable))
            cost = (
                " · ".join(
                    [f"{cost_view['action']} AP"] * bool(cost_view["action"])
                    + [f"{cost_view['focus']} FP"] * bool(cost_view["focus"])
                )
                or "free"
            )
            tgt = " ⌖" if any(arg.get("target_group") for arg in _action_arguments(action)) else ""
            option_id = _action_tool(action)
            if option_id in action_options:
                option_id = f"{option_id}:{index}"
            # Never disable: an unavailable action is only de-emphasized (dimmed, with the
            # reason appended) so the player can still queue it if they want to.
            if available:
                prefix = f"{_action_icon(action)} " if self.show_icons else ""
                label = Text(f"{prefix}{_action_title(action)}{tgt}  ({cost})")
            else:
                reason = _action_unavailable_reason(action)
                suffix = f" — {reason}" if reason else ""
                prefix = f"{_action_icon(action)} " if self.show_icons else ""
                label = Text(
                    f"{prefix}{_action_title(action)}{tgt}  ({cost}){suffix}",
                    style="dim",
                )
            action_options[option_id] = action
            verb_entries.append((option_id, label, label.plain))
        self._action_options = action_options

        verbs_signature = tuple((oid, plain) for oid, _label, plain in verb_entries)
        if verbs_signature != self._verbs_signature:
            verbs = self._main_query_one("#verbs", OptionList)
            highlighted_id = None
            highlighted = verbs.highlighted
            if highlighted is not None and highlighted >= 0 and highlighted < verbs.option_count:
                highlighted_id = verbs.get_option_at_index(highlighted).id
            verbs.clear_options()
            for option_id, label, _plain in verb_entries:
                verbs.add_option(Option(label, id=option_id))
            option_ids = [option_id for option_id, _label, _plain in verb_entries]
            if highlighted_id in option_ids:
                verbs.highlighted = option_ids.index(highlighted_id)
            self._verbs_signature = verbs_signature

        if not self.queued_commands:
            queued_entries = (("queued-empty", "No queued actions."),)
        else:
            countdown = self._next_tick_countdown()
            queued_entries = tuple(
                (
                    f"queued:{index}",
                    f"{_queued_command_label(command, actions)}"
                    f"{f' · next tick in {countdown}s' if countdown is not None else ''}",
                )
                for index, command in enumerate(self.queued_commands)
            )
        if queued_entries == self._queued_signature:
            return
        queued = self._main_query_one("#queued", OptionList)
        queued.clear_options()
        for option_id, label in queued_entries:
            queued.add_option(Option(label, id=option_id, disabled=option_id == "queued-empty"))
        self._queued_signature = queued_entries

    def _next_tick_countdown(self) -> int | None:
        next_tick = self.queue_timing.get("next_tick_at_unix")
        if next_tick is None:
            return None
        return max(0, int(round(float(next_tick) - time.time())))

    def _available_actions(self) -> list[dict]:
        return self.action_views

    def _filtered_actions(self) -> list[dict]:
        actions = self._available_actions()
        query = self.action_filter.strip().lower()
        if query:
            actions = [
                action
                for action in actions
                if query in _action_title(action).lower()
                or query in _action_tool(action).lower()
                or query in str(action.get("command_type", "")).lower()
            ]
        # Available actions come first; the sort is stable so each group keeps its order.
        # Unavailable actions stay in the list (de-emphasized, not removed) so a player can
        # still queue a not-yet-valid action.
        return sorted(actions, key=lambda action: not _action_available(action))

    def _drain_activity(self, events: list[dict], *, prime: bool = False) -> None:
        lines = self._events.drain_events(
            events,
            player_id=self.player_id,
            room_of=self.world.room_of,
            name_for=self._name_for,
            show_icons=self.show_icons,
        )
        image_lines = self._image_activity(events, prime=prime)
        if prime:
            self._render_activity()
            return
        for line in lines:
            self._append_activity(line)
        for line in image_lines:
            self._append_activity(line)

    def _image_activity(self, events: list[dict], *, prime: bool) -> list[Text]:
        # Image-generation events ride at SYSTEM visibility (no actor), so the perception
        # filter in EventNarrator drops them. Pull completions/failures straight from the
        # recent-events feed instead, matching the web clients. On the priming pass we only
        # record what is already there so reconnecting does not replay an old image.
        lines: list[Text] = []
        completion = latest_image_completion(events, purpose="event")
        if completion is not None and completion["url"] != self._event_image_url:
            self._event_image_url = completion["url"]
            if not prime:
                lines.append(
                    Text(f"{DELIVER_EMOJI} scene image ready: {completion['url']}", style="cyan")
                )
        failure = latest_image_failure(events, purpose="event")
        if failure is not None and failure["world_epoch"] != self._event_image_failure_epoch:
            self._event_image_failure_epoch = failure["world_epoch"]
            if not prime:
                reason = failure.get("reason") or "image generation failed"
                lines.append(Text(f"{FAIL_EMOJI} image request failed: {reason}", style="yellow"))
        return lines

    def _append_activity(self, line: Text) -> None:
        self.activity_lines.append(line)
        self.activity_lines = self.activity_lines[-ACTIVITY_LIMIT:]
        self._render_activity()

    def _render_activity(self) -> None:
        activity = self._main_query_one("#activity", OptionList)
        activity.clear_options()
        if not self.activity_lines:
            activity.add_option(Option("No recent activity.", id="activity-empty", disabled=True))
            return
        for index, line in enumerate(self.activity_lines):
            activity.add_option(Option(line, id=f"activity:{index}"))

    def _name_for(self, entity_id: str) -> str | None:
        entity = self.world.get(entity_id)
        return entity_name(entity) if entity else None

    def _sync_target_controls(self) -> None:
        target_name = self._name_for(self.selected_id) if self.selected_id else None
        label = target_name or self.selected_id or "none"
        self._main_query_one("#target-label", Static).update(f"Target: {label}")
        self._main_query_one("#target-clear", Button).disabled = self.selected_id is None

    # ── events ──────────────────────────────────────────────────────────────────
    @on(Select.Changed, "#player")
    async def _player_changed(self, event: Select.Changed) -> None:
        new_id = "" if event.value in (Select.BLANK, Select.NULL) else str(event.value)
        if new_id == self.player_id:
            return
        self.player_id = new_id
        self.selected_id = None
        self.control = await self.backend.claim(new_id, self.world) if new_id else None
        self._restart_live_updates()
        await self.refresh_world()

    @on(Button.Pressed, "#character-release")
    async def _character_release_pressed(self, _event: Button.Pressed) -> None:
        if not self.player_id:
            return
        if self.control is None or not self.control.active:
            self.control = await self.backend.claim(self.player_id, self.world)
            self._restart_live_updates()
            await self.refresh_world()
            return
        if not self.control.claim_id or not self.control.claim_secret:
            self._drop_player()
            await self.refresh_world()
            return
        control = await self.backend.release_controller(self.player_id, self.control)
        if control is None:
            self._append_activity(Text("Could not release controller.", style="dark_orange"))
            return
        self.control = control
        await self.refresh_world()

    @on(Button.Pressed, "#claim-release")
    async def _claim_release_pressed(self, _event: Button.Pressed) -> None:
        if not self.player_id or self.control is None:
            return
        if not await self.backend.release_claim(self.player_id, self.control):
            self._append_activity(Text("Could not release claim.", style="dark_orange"))
            return
        self._drop_player()
        await self.refresh_world()

    def _drop_player(self) -> None:
        self._stop_live_updates()
        self.player_id = ""
        self.control = None
        self.selected_id = None
        self.world = World()
        self.action_views = []
        self.queued_commands = []
        self.queue_timing = {}
        self.view_room_id = None
        self._verbs_signature = ()
        self._queued_signature = ()
        self._points_line = ""
        self._main_query_one("#player", Select).clear()

    @on(Button.Pressed, "#request-image")
    async def _request_image_pressed(self, _event: Button.Pressed) -> None:
        await self.action_request_image()

    @on(Button.Pressed, "#open-sheet")
    async def _open_sheet_pressed(self, _event: Button.Pressed) -> None:
        await self.action_open_sheet()

    @on(Button.Pressed, "#open-chat")
    async def _open_chat_pressed(self, _event: Button.Pressed) -> None:
        await self.action_open_chat()

    @on(Button.Pressed, "#target-clear")
    def _target_clear_pressed(self, _event: Button.Pressed) -> None:
        self.action_clear_target()

    def action_help(self) -> None:
        """Show the key-binding cheat-sheet."""
        self.push_screen(HelpScreen())

    def action_clear_target(self) -> None:
        """Clear the selected action target without releasing the character."""
        if self.selected_id is None:
            return
        self.selected_id = None
        self._sync_target_controls()
        self._render_room()

    async def action_request_image(self) -> None:
        """Request an image of the player's current scene when the backend supports it."""
        if not self.player_id:
            self._append_activity(Text("Select a character before requesting an image."))
            return
        if not self.backend.supports_image_requests:
            self._append_activity(Text("Image requests are not available for this session."))
            return
        result = await self.backend.request_image(self.player_id)
        if result.ok:
            note = "image ready" if result.status == "skipped" else "image requested"
            self._append_activity(Text(f"{REQUEST_EMOJI} {note}.", style="cyan"))
        else:
            self._append_activity(Text(f"{REQUEST_EMOJI} {result.reason}", style="yellow"))

    async def action_open_sheet(self) -> None:
        """Open the selected or current character's native terminal sheet."""
        if not self.player_id:
            self._append_activity(Text("Select a character before opening a sheet."))
            return
        if not self.backend.supports_character_sheets:
            self._append_activity(Text("Character sheets require a remote server URL."))
            return
        character_id = self.player_id
        if self.selected_id:
            selected = self.world.get(self.selected_id)
            if selected is None or not has(selected, "CharacterComponent"):
                self._append_activity(Text("Select a visible character or clear the target."))
                return
            character_id = self.selected_id
        # Compatibility for third-party backends that only implement the former browser
        # operation; built-in local and remote backends always use the typed profile.
        if type(self.backend).fetch_character_profile is Backend.fetch_character_profile:
            result = await self.backend.open_character_sheet(character_id)
            if result.ok:
                self._append_activity(Text(f"Opened sheet: {result.url}", style="cyan"))
            else:
                self._append_activity(Text(result.reason, style="yellow"))
            return
        try:
            profile = await self.backend.fetch_character_profile(character_id)
        except Exception as exc:
            self._append_activity(Text(f"Could not load character sheet: {exc}", style="yellow"))
            return
        self.push_screen(CharacterSheetScreen(profile))

    async def action_open_chat(self) -> None:
        """Open chat for the selected character, current character, or a picker choice."""
        character_id = ""
        if self.selected_id:
            selected = self.world.get(self.selected_id)
            if selected is not None and has(selected, "CharacterComponent"):
                character_id = self.selected_id
        if not character_id:
            character_id = self.player_id
        if character_id:
            self._open_conversation(character_id)
            return
        if not self.character_list:
            self._append_activity(Text("No characters are available to chat."))
            return
        self.push_screen(
            CharacterPickerScreen(self.character_list, title="Choose a character to chat with"),
            callback=lambda chosen: self._open_conversation(chosen) if chosen else None,
        )

    def _open_conversation(self, character_id: str) -> None:
        summary = next(
            (item for item in self.character_list if item.character_id == character_id), None
        )
        name = summary.name if summary is not None else entity_name(self.world.get(character_id))
        self.push_screen(ConversationScreen(self.backend, character_id, name or character_id))

    @on(OptionList.OptionSelected, "#members")
    def _member_selected(self, event: OptionList.OptionSelected) -> None:
        self.selected_id = event.option.id
        self._sync_target_controls()

    @on(OptionList.OptionSelected, "#inventory")
    def _inventory_selected(self, event: OptionList.OptionSelected) -> None:
        self.selected_id = str(event.option.id or "").removeprefix("inv:")
        self._sync_target_controls()

    @on(OptionList.OptionSelected, "#doors")
    def _door_selected(self, event: OptionList.OptionSelected) -> None:
        option_id = str(event.option.id or "")
        if not option_id.startswith("door:"):
            return
        self.run_worker(self._move_through_exit(option_id.removeprefix("door:")), exclusive=True)

    @on(OptionList.OptionSelected, "#verbs")
    def _verb_selected(self, event: OptionList.OptionSelected) -> None:
        action = self._action_options.get(str(event.option.id))
        if action:
            self.run_worker(self._do_action(action), exclusive=True)

    @on(OptionList.OptionSelected, "#queued")
    def _queued_selected(self, event: OptionList.OptionSelected) -> None:
        option_id = str(event.option.id or "")
        if not option_id.startswith("queued:"):
            return
        index = int(option_id.removeprefix("queued:"))
        if index < 0 or index >= len(self.queued_commands):
            return
        self.run_worker(self._cancel_queued_command(self.queued_commands[index]), exclusive=True)

    @on(Input.Changed, "#action-filter")
    def _action_filter_changed(self, event: Input.Changed) -> None:
        value = event.value.strip()
        if value == self.action_filter:
            return
        self.action_filter = value
        self._render_actions()

    @on(Button.Pressed, "#action-filter-clear")
    def _action_filter_clear_pressed(self, _event: Button.Pressed) -> None:
        self._main_query_one("#action-filter", Input).value = ""
        if self.action_filter:
            self.action_filter = ""
            self._render_actions()

    # ── actions ─────────────────────────────────────────────────────────────────
    def _action_fields(self, action: dict) -> list[FormField]:
        # Prompt for every required argument plus any entity argument that has a target
        # group, so the form can offer a dropdown of nearby candidates.
        fields: list[FormField] = []
        for argument in _action_arguments(action):
            key = argument.get("key")
            if not key:
                continue
            required = bool(argument.get("required"))
            target_group = argument.get("target_group")
            if not required and not target_group:
                continue
            candidates = (
                tuple(self.world.target_candidates(self.player_id, target_group))
                if target_group
                else None
            )
            initial_value = (
                self.selected_id
                if candidates is not None
                and self.selected_id in {candidate.value for candidate in candidates}
                else None
            )
            fields.append(
                FormField(
                    key=key,
                    label=str(argument.get("title") or key),
                    kind=str(argument.get("kind") or "string"),
                    required=required,
                    candidates=candidates,
                    initial_value=initial_value,
                )
            )
        return fields

    async def _move_through_exit(self, exit_id: str) -> None:
        action = next(
            (
                action
                for action in self._available_actions()
                if any(arg.get("target_group") == "exits" for arg in _action_arguments(action))
            ),
            None,
        )
        if action is None:
            return
        exit_arg = next(
            arg for arg in _action_arguments(action) if arg.get("target_group") == "exits"
        )
        await self._submit_action(action, {exit_arg.get("key"): exit_id})

    async def _do_action(self, action: dict) -> None:
        if not self.player_id or not self.control:
            return
        # Only one action form may be open at a time; ignore a second selection while one
        # is still on the screen stack.
        if any(isinstance(screen, ActionForm) for screen in self.screen_stack):
            return
        payload: dict = {}
        fields = self._action_fields(action)
        if fields:
            result = await self.push_screen_wait(ActionForm(_action_title(action), fields))
            if result is None:
                return
            payload = result

        await self._submit_action(action, payload)

    async def _submit_action(self, action: dict, payload: dict) -> None:
        if not self.player_id or not self.control:
            return
        if not self.control.active:
            self.control = await self.backend.claim(self.player_id, self.world)
            if self.control is None:
                self._append_activity(Text("Could not resume this character.", style="dark_orange"))
                return
        cost = _action_cost(action)
        result = await self.backend.submit(
            {
                "character_id": self.player_id,
                "controller_id": self.control.controller_id,
                "controller_generation": self.control.generation,
                "claim_id": self.control.claim_id,
                "command_type": _action_command_type(action),
                "payload": payload,
                "cost": cost,
                "lane": _action_lane(action),
                "on_insufficient_points": "queue",
            }
        )
        if not result.accepted:
            reason = result.reason or "command rejected"
            self._append_activity(
                Text(f"✗ {_action_title(action)} — {reason}", style="dark_orange")
            )
        await self.refresh_world()

    async def _cancel_queued_command(self, command: dict) -> None:
        if not self.player_id or not self.control:
            return
        ok = await self.backend.cancel_command(
            self.player_id,
            str(command.get("command_id") or ""),
            self.control.controller_id,
            self.control.generation,
        )
        if not ok:
            self._append_activity(Text("Could not cancel queued command.", style="dark_orange"))
        await self.refresh_world()

    async def action_refresh(self) -> None:
        await self.refresh_world()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="bunnyland tui", description=__doc__)
    parser.add_argument(
        "--server",
        help="connect to a v1 API root (e.g. http://localhost:8765/v1)",
    )
    parser.add_argument("--username", default="", help="login username for a remote server")
    parser.add_argument("--password-stdin", action="store_true")
    parser.add_argument(
        "--token-file",
        default=None,
        help="explicitly persist the bearer token in this mode-0600 credential file",
    )
    parser.add_argument("--seed", default=None, help="seed for a locally hosted world")
    parser.add_argument("--generator", default=None, help="generator for a locally hosted world")
    parser.add_argument(
        "--list-generators",
        action="store_true",
        help="list the available world generators (demo worlds) for local play and exit",
    )
    parser.add_argument(
        "--claim-fallback",
        default=None,
        help="idle controller id for this TUI claim; also accepts suspend or llm",
    )
    parser.add_argument(
        "--claim-timeout-minutes",
        type=int,
        default=None,
        help="idle timeout override in minutes, between 5 and 60",
    )
    parser.add_argument(
        "--no-icons",
        action="store_true",
        help="hide action and activity icons",
    )
    parser.add_argument(
        "--chat-provider",
        choices=("ollama-local", "ollama-cloud", "openrouter"),
        default=None,
    )
    parser.add_argument("--chat-model", default=None)
    parser.add_argument("--ollama-host", default=None)
    parser.add_argument("--openrouter-server-url", default=None)
    parser.add_argument("--no-chat", action="store_true")
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
    password = ""
    if args.server and args.username:
        if args.password_stdin:
            password = sys.stdin.readline().rstrip("\r\n")
        else:
            from getpass import getpass

            password = getpass("Bunnyland password: ")

    try:
        saved_chat = None if args.server else load_terminal_config()
    except TerminalConfigError as exc:
        raise SystemExit(str(exc)) from exc
    explicit_chat = any(
        (
            args.chat_provider,
            args.chat_model,
            args.ollama_host,
            args.openrouter_server_url,
            args.no_chat,
        )
    )
    chat_settings = resolve_terminal_chat_config(
        saved_chat,
        chat_provider=args.chat_provider,
        chat_model=args.chat_model,
        ollama_host=args.ollama_host,
        openrouter_server_url=args.openrouter_server_url,
        no_chat=args.no_chat,
    )
    if not args.server and (saved_chat is not None or explicit_chat):
        try:
            chat_settings.validate_credentials()
        except TerminalConfigError as exc:
            raise SystemExit(str(exc)) from exc

    show_generator_selector = not args.server and args.generator is None
    local_kwargs = {
        "seed": args.seed or DEFAULT_LOCAL_SEED,
        "generator": args.generator or DEFAULT_LOCAL_GENERATOR,
        "fallback_controller": args.claim_fallback,
        "timeout_seconds": timeout_seconds,
    }
    if saved_chat is not None or explicit_chat:
        local_kwargs["chat_config"] = chat_settings
    backend: Backend = (
        RemoteBackend(
            args.server,
            fallback_controller=args.claim_fallback,
            timeout_seconds=timeout_seconds,
            username=args.username,
            password=password,
            token_file=args.token_file,
        )
        if args.server
        else LocalBackend(**local_kwargs)
    )
    app = BunnylandTUI(backend)
    app.show_generator_selector = show_generator_selector
    app.needs_chat_setup = not args.server and saved_chat is None and not explicit_chat
    app.show_icons = not args.no_icons
    app.show_intro = True
    app.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
