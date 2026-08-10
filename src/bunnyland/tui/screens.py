"""Reusable Textual screens shared by the TUI, REPL, and focused chat app."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass, replace
from functools import partial
from typing import Literal

from rich.console import Console
from rich.markdown import Markdown
from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, Input, Label, OptionList, Select, Static
from textual.widgets.option_list import Option

from ..character_chat_display import format_action_call
from ..server.v1_models import CharacterProfileResource
from ..terminal_chat import (
    PARAGRAPH_REVEAL_DELAY_SECONDS,
    clear_all_history,
    clear_history,
    load_chat_preferences,
    load_history,
    save_chat_preferences,
    save_history,
    split_reply_paragraphs,
)
from ..terminal_config import TerminalConfig
from .backend import Backend, CharacterChatAccess, CharacterChatJob

WorldIntroductionSkip = Literal["none", "world", "all"]
_MARKDOWN_CONSOLE = Console(width=1000, color_system=None)


@dataclass(frozen=True)
class SignInCredentials:
    username: str
    password: str


class SignInScreen(ModalScreen[SignInCredentials | None]):
    """Collect remote player credentials without exposing the password on screen."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    CSS = """
    SignInScreen { align: center middle; }
    #sign-in-panel {
        width: 54; height: auto; border: thick $accent;
        background: $surface; padding: 1 2;
    }
    #sign-in-title { text-style: bold; margin-bottom: 1; }
    .sign-in-label { margin-top: 1; }
    #sign-in-error { color: $error; height: auto; min-height: 1; margin-top: 1; }
    #sign-in-buttons { height: auto; margin-top: 1; }
    #sign-in-submit { margin-right: 1; }
    """

    def __init__(self, *, username: str = "", error: str = "") -> None:
        super().__init__()
        self.username = username
        self.error = error

    def compose(self) -> ComposeResult:
        with Vertical(id="sign-in-panel"):
            yield Label("Sign in to Bunnyland", id="sign-in-title")
            yield Label("Username", classes="sign-in-label")
            yield Input(value=self.username, id="sign-in-username")
            yield Label("Password", classes="sign-in-label")
            yield Input(password=True, id="sign-in-password")
            yield Label(self.error, id="sign-in-error")
            with Horizontal(id="sign-in-buttons"):
                yield Button("Sign in", id="sign-in-submit", variant="primary")
                yield Button("Cancel", id="sign-in-cancel")

    def on_mount(self) -> None:
        target = "#sign-in-password" if self.username else "#sign-in-username"
        self.query_one(target, Input).focus()

    @on(Input.Submitted)
    def _input_submitted(self, _event: Input.Submitted) -> None:
        self._try_submit()

    @on(Button.Pressed, "#sign-in-submit")
    def _submit_pressed(self, _event: Button.Pressed) -> None:
        self._try_submit()

    @on(Button.Pressed, "#sign-in-cancel")
    def _cancel_pressed(self, _event: Button.Pressed) -> None:
        self.action_cancel()

    def _try_submit(self) -> None:
        username = self.query_one("#sign-in-username", Input).value.strip()
        password = self.query_one("#sign-in-password", Input).value
        error = self.query_one("#sign-in-error", Label)
        if not username:
            error.update("Username is required.")
            return
        if not password:
            error.update("Password is required.")
            return
        self.dismiss(SignInCredentials(username=username, password=password))

    def action_cancel(self) -> None:
        self.dismiss(None)


def render_character_profile(profile: CharacterProfileResource) -> Text:
    """Render every stable character-sheet section in deterministic order."""

    sheet = profile.sheet
    out = Text()
    out.append(profile.character_name, style="bold cyan")
    identity = " · ".join(part for part in (sheet.kind, sheet.species) if part)
    if identity:
        out.append(f"\n{identity}", style="dim")
    if sheet.tags:
        out.append(f"\nTags: {', '.join(sheet.tags)}")
    if sheet.biography:
        out.append("\n\nBiography\n", style="bold")
        out.append(sheet.biography)
    if sheet.description or sheet.appearance:
        out.append("\n\nIdentity\n", style="bold")
        if sheet.description:
            out.append(sheet.description)
        if sheet.appearance:
            out.append(f"\nAppearance: {sheet.appearance}")
    if sheet.status:
        out.append("\n\nStatus\n", style="bold")
        out.append(" · ".join(sheet.status))

    out.append("\n\nDetails\n", style="bold")
    out.append(f"ID: {profile.character_id}")
    room = profile.room.title or profile.room.id or "—"
    out.append(f"\nRoom: {room}")
    if profile.controller is None:
        out.append("\nController: —")
    else:
        controller = profile.controller
        label = controller.name or controller.kind or controller.controller_id
        kind = f"{controller.kind}: " if controller.kind else ""
        detail = f"{controller.controller_id} gen {controller.generation}"
        if controller.detail:
            detail = f"{controller.detail} · {detail}"
        out.append(f"\nController: {kind}{label} · {detail}")
    out.append(
        f"\nAction Points: {profile.points.action:g}/{profile.points.action_max:g}"
        f"\nFocus Points: {profile.points.focus:g}/{profile.points.focus_max:g}"
    )
    if profile.portrait.url:
        out.append(f"\nPortrait: {profile.portrait.url}")

    def metrics(title: str, rows) -> None:
        if not rows:
            return
        out.append(f"\n\n{title}\n", style="bold")
        for row in rows:
            value = row.text or f"{row.value:g}"
            if row.maximum is not None:
                value = f"{row.value:g}/{row.maximum:g}"
            suffix = f" · {row.band}" if row.band else ""
            out.append(f"{row.label}: {value}{suffix}\n")

    def entries(title: str, rows) -> None:
        if not rows:
            return
        out.append(f"\n{title}\n", style="bold")
        for row in rows:
            value = f": {row.value}" if row.value else ""
            detail = f" — {row.detail}" if row.detail else ""
            out.append(f"{row.label}{value}{detail}\n")

    metrics("Vitals", sheet.vitals)
    metrics("Needs", sheet.needs)
    metrics("Affect", sheet.affect)
    entries("Profile", sheet.profile)
    entries("Skills", sheet.skills)
    if sheet.traits:
        out.append("\nTraits\n", style="bold")
        for trait in sheet.traits:
            out.append(f"{trait}\n")
    entries("Relationships", sheet.relations)
    entries("Injuries", sheet.injuries)
    entries("Notes", sheet.notes)
    return out


def render_chat_markdown(value: str) -> Text:
    """Render Markdown into styled terminal text without fixing its display width."""

    rendered = Text()
    lines = _MARKDOWN_CONSOLE.render_lines(
        Markdown(value),
        _MARKDOWN_CONSOLE.options,
        pad=False,
    )
    for index, line in enumerate(lines):
        rendered.append_tokens((segment.text, segment.style) for segment in line)
        if index < len(lines) - 1:
            rendered.append("\n")
    rendered.rstrip()
    return rendered


class CharacterSheetScreen(ModalScreen[None]):
    BINDINGS = [("escape", "close", "Close")]

    CSS = """
    CharacterSheetScreen { align: center middle; }
    #sheet-panel { width: 78; height: 90%; border: thick $accent; background: $surface; }
    #sheet-title { height: 3; padding: 1 2 0 2; text-style: bold; }
    #sheet-scroll { height: 1fr; padding: 0 2; }
    #sheet-close { width: 12; margin: 1 2; }
    """

    def __init__(self, profile: CharacterProfileResource) -> None:
        super().__init__()
        self.profile = profile

    def compose(self) -> ComposeResult:
        with Vertical(id="sheet-panel"):
            yield Label(f"Character Sheet · {self.profile.character_name}", id="sheet-title")
            with VerticalScroll(id="sheet-scroll"):
                yield Static(render_character_profile(self.profile), id="sheet-content")
            yield Button("Close", id="sheet-close", variant="primary")

    @on(Button.Pressed, "#sheet-close")
    def _close_pressed(self, _event: Button.Pressed) -> None:
        self.dismiss(None)

    def action_close(self) -> None:
        self.dismiss(None)


class CharacterPickerScreen(ModalScreen[str | None]):
    BINDINGS = [("escape", "cancel", "Cancel")]

    CSS = """
    CharacterPickerScreen { align: center middle; }
    #character-picker-panel {
        width: 60; height: 70%; border: thick $accent;
        background: $surface; padding: 1 2;
    }
    #character-picker { height: 1fr; margin: 1 0; }
    """

    def __init__(self, characters: Sequence, *, title: str = "Choose a character") -> None:
        super().__init__()
        self.characters = list(characters)
        self.title = title

    def compose(self) -> ComposeResult:
        with Vertical(id="character-picker-panel"):
            yield Label(self.title, id="character-picker-title")
            choices = OptionList(id="character-picker")
            for character in self.characters:
                character_id = getattr(character, "character_id", None) or getattr(
                    character, "id", ""
                )
                choices.add_option(
                    Option(getattr(character, "name", character_id), id=character_id)
                )
            if not self.characters:
                choices.add_option(Option("No characters are available.", disabled=True))
            yield choices
            yield Button("Cancel", id="character-picker-cancel")

    @on(OptionList.OptionSelected, "#character-picker")
    def _selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(str(event.option.id))

    @on(Button.Pressed, "#character-picker-cancel")
    def _cancel_pressed(self, _event: Button.Pressed) -> None:
        self.action_cancel()

    def action_cancel(self) -> None:
        self.dismiss(None)


class ContentWarningScreen(ModalScreen[bool]):
    """Require explicit acceptance before a terminal client enters a flagged world."""

    BINDINGS = [("escape", "decline", "Leave")]

    CSS = """
    ContentWarningScreen { align: center middle; }
    #content-warning-panel {
        width: 72; height: auto; max-height: 85%; border: thick $warning;
        background: $surface; padding: 1 2;
    }
    #content-warning-flags { height: auto; max-height: 14; margin: 1 0; }
    #content-warning-buttons { height: auto; }
    #content-warning-accept { margin-right: 1; }
    """

    def __init__(self, content_flags: Sequence[str]) -> None:
        super().__init__()
        self.content_flags = tuple(content_flags)

    def compose(self) -> ComposeResult:
        with Vertical(id="content-warning-panel"):
            yield Label("Content warning", id="content-warning-title")
            yield Static(
                "This world may contain the following content. "
                "You must accept this warning before joining."
            )
            with VerticalScroll(id="content-warning-flags"):
                yield Static("\n".join(f"• {flag}" for flag in self.content_flags))
            with Horizontal(id="content-warning-buttons"):
                yield Button("Accept and Join", id="content-warning-accept", variant="primary")
                yield Button("Leave", id="content-warning-decline")

    @on(Button.Pressed, "#content-warning-accept")
    def _accept_pressed(self, _event: Button.Pressed) -> None:
        self.dismiss(True)

    @on(Button.Pressed, "#content-warning-decline")
    def _decline_pressed(self, _event: Button.Pressed) -> None:
        self.action_decline()

    def action_decline(self) -> None:
        self.dismiss(False)


class WorldIntroductionScreen(ModalScreen[WorldIntroductionSkip]):
    """Show public world identity before a terminal player joins."""

    CSS = """
    WorldIntroductionScreen { align: center middle; }
    #world-introduction-panel {
        width: 72; height: auto; max-height: 85%; border: thick $accent;
        background: $surface; padding: 1 2;
    }
    #world-introduction-title { text-style: bold; margin-bottom: 1; }
    #world-introduction-description { height: auto; max-height: 16; }
    #world-introduction-options { height: auto; margin-top: 1; }
    #world-introduction-buttons { height: auto; margin-top: 1; }
    """

    def __init__(self, title: str, description: str) -> None:
        super().__init__()
        self.world_title = title
        self.world_description = description

    def compose(self) -> ComposeResult:
        with Vertical(id="world-introduction-panel"):
            yield Label(self.world_title, id="world-introduction-title")
            with VerticalScroll(id="world-introduction-description"):
                yield Static(self.world_description)
            with Vertical(id="world-introduction-options"):
                yield Checkbox(
                    "Skip this introduction for this world and server.",
                    id="world-introduction-skip-world",
                )
                yield Checkbox(
                    "Skip introductions for all worlds and servers.",
                    id="world-introduction-skip-all",
                )
            with Horizontal(id="world-introduction-buttons"):
                yield Button("Continue", id="world-introduction-continue", variant="primary")

    @on(Checkbox.Changed, "#world-introduction-skip-world")
    def _skip_world_changed(self, event: Checkbox.Changed) -> None:
        if event.value:
            self.query_one("#world-introduction-skip-all", Checkbox).value = False

    @on(Checkbox.Changed, "#world-introduction-skip-all")
    def _skip_all_changed(self, event: Checkbox.Changed) -> None:
        if event.value:
            self.query_one("#world-introduction-skip-world", Checkbox).value = False

    @on(Button.Pressed, "#world-introduction-continue")
    def _continue_pressed(self, _event: Button.Pressed) -> None:
        if self.query_one("#world-introduction-skip-all", Checkbox).value:
            self.dismiss("all")
        elif self.query_one("#world-introduction-skip-world", Checkbox).value:
            self.dismiss("world")
        else:
            self.dismiss("none")


class ConversationScreen(ModalScreen[None]):
    BINDINGS = [("escape", "close", "Close")]

    CSS = """
    ConversationScreen { align: center middle; }
    #conversation-panel {
        width: 84; height: 90%; border: thick $accent;
        background: $surface; padding: 1 2;
    }
    #conversation-transcript-scroll { height: 1fr; margin: 1 0; }
    #conversation-status, #conversation-action { height: auto; min-height: 1; color: $text-muted; }
    #conversation-input { width: 1fr; }
    #conversation-preferences { height: auto; margin-top: 1; }
    #conversation-preferences Checkbox { margin-right: 1; }
    #conversation-controller-row { height: auto; margin-top: 1; }
    #conversation-controller { width: 1fr; margin-right: 1; }
    #conversation-buttons { height: auto; margin-top: 1; }
    #conversation-sheet { margin-right: 1; }
    """

    def __init__(self, backend: Backend, character_id: str, character_name: str) -> None:
        super().__init__()
        self.backend = backend
        self.character_id = character_id
        self.character_name = character_name
        self.preferences = load_chat_preferences()
        self.state = (
            load_history(backend.client_id, character_id)
            if self.preferences.remember_history
            else {"summary": "", "messages": []}
        )
        self._job: CharacterChatJob | None = None
        self._send_task: asyncio.Task | None = None
        self._paragraph_visibility: dict[int, int] = {}
        self._access = CharacterChatAccess(writable=False, reason="Checking chat access…")

    def compose(self) -> ComposeResult:
        with Vertical(id="conversation-panel"):
            yield Label(f"Chat · {self.character_name}", id="conversation-title")
            with VerticalScroll(id="conversation-transcript-scroll"):
                yield Static("", id="conversation-transcript")
            yield Static("", id="conversation-status")
            yield Static("", id="conversation-action")
            yield Input(
                placeholder=f"Say something to {self.character_name}",
                id="conversation-input",
            )
            with Horizontal(id="conversation-controller-row"):
                yield Select(
                    [],
                    prompt="— choose an LLM controller —",
                    allow_blank=True,
                    id="conversation-controller",
                )
                yield Button(
                    "Assign LLM",
                    id="conversation-controller-assign",
                    variant="warning",
                    disabled=True,
                )
            with Horizontal(id="conversation-preferences"):
                yield Checkbox(
                    "Markdown",
                    value=self.preferences.markdown,
                    id="conversation-markdown",
                )
                yield Checkbox(
                    "Remember on this device",
                    value=self.preferences.remember_history,
                    id="conversation-remember-history",
                )
                yield Checkbox(
                    "Separate reply paragraphs",
                    value=self.preferences.separate_reply_paragraphs,
                    id="conversation-separate-paragraphs",
                )
            with Horizontal(id="conversation-buttons"):
                yield Button("Clear history", id="conversation-clear-history")
                yield Button("Sheet", id="conversation-sheet")
                yield Button("Close", id="conversation-close", variant="primary")

    async def on_mount(self) -> None:
        self._render_transcript()
        await self._refresh_access()

    async def _refresh_access(self) -> CharacterChatAccess:
        self._access = await self.backend.character_chat_access(self.character_id)
        status = self.query_one("#conversation-status", Static)
        input_widget = self.query_one("#conversation-input", Input)
        select = self.query_one("#conversation-controller", Select)
        assign = self.query_one("#conversation-controller-assign", Button)
        row = self.query_one("#conversation-controller-row", Horizontal)
        input_widget.disabled = not self._access.writable
        status.update("" if self._access.writable else self._access.reason)
        row.display = self._access.can_assign
        select.set_options(
            [(choice.label, choice.controller_id) for choice in self._access.controllers]
        )
        if self._access.controllers:
            select.value = (
                self._access.activation_controller_id or self._access.controllers[0].controller_id
            )
        assign.label = "Activate default LLM" if self._access.can_activate else "Assign LLM"
        assign.disabled = not self._access.can_assign
        if self._access.writable:
            input_widget.focus()
        return self._access

    def _render_transcript(self) -> None:
        transcript = Text()
        markdown = self.query_one("#conversation-markdown", Checkbox).value
        separate_paragraphs = self.query_one(
            "#conversation-separate-paragraphs", Checkbox
        ).value
        for item in self.state.get("messages") or []:
            role = item.get("role")
            label = "You" if role == "user" else self.character_name
            style = "bold cyan" if role == "user" else "bold green"
            text = str(item.get("text") or "")
            paragraphs = (
                split_reply_paragraphs(text)
                if separate_paragraphs and role == "character"
                else (text,)
            )
            visible = self._paragraph_visibility.get(id(item), len(paragraphs))
            for paragraph in paragraphs[:visible]:
                if len(transcript):
                    transcript.append("\n\n")
                transcript.append(f"{label}: ", style=style)
                if markdown:
                    transcript.append_text(render_chat_markdown(paragraph))
                else:
                    transcript.append(paragraph)
        self.query_one("#conversation-transcript", Static).update(transcript)
        self.query_one("#conversation-transcript-scroll", VerticalScroll).scroll_end(animate=False)
        self.query_one("#conversation-clear-history", Button).disabled = not bool(
            self.state.get("summary") or self.state.get("messages")
        )

    def _schedule_paragraph_reveal(self, message: dict[str, str]) -> None:
        checkbox = self.query_one("#conversation-separate-paragraphs", Checkbox)
        paragraphs = split_reply_paragraphs(message["text"])
        if not checkbox.value or len(paragraphs) < 2:
            return
        key = id(message)
        self._paragraph_visibility[key] = 1
        for visible in range(2, len(paragraphs) + 1):
            self.set_timer(
                PARAGRAPH_REVEAL_DELAY_SECONDS * (visible - 1),
                partial(self._reveal_paragraph, key, visible, len(paragraphs)),
            )

    def _reveal_paragraph(self, key: int, visible: int, total: int) -> None:
        if key not in self._paragraph_visibility:
            return
        if visible >= total:
            self._paragraph_visibility.pop(key)
        else:
            self._paragraph_visibility[key] = visible
        self._render_transcript()

    @on(Checkbox.Changed, "#conversation-separate-paragraphs")
    def _separate_paragraphs_changed(self, event: Checkbox.Changed) -> None:
        self.preferences = replace(
            self.preferences,
            separate_reply_paragraphs=event.value,
        )
        save_chat_preferences(self.preferences)
        if not event.value:
            self._paragraph_visibility.clear()
        self._render_transcript()

    @on(Checkbox.Changed, "#conversation-markdown")
    def _markdown_changed(self, event: Checkbox.Changed) -> None:
        self.preferences = replace(self.preferences, markdown=event.value)
        save_chat_preferences(self.preferences)
        self._render_transcript()

    @on(Checkbox.Changed, "#conversation-remember-history")
    def _remember_history_changed(self, event: Checkbox.Changed) -> None:
        self.preferences = replace(self.preferences, remember_history=event.value)
        save_chat_preferences(self.preferences)
        if event.value:
            save_history(self.backend.client_id, self.character_id, self.state)
        else:
            clear_all_history()
            self.state = {"summary": "", "messages": []}
            self._paragraph_visibility.clear()
        self._render_transcript()

    @on(Button.Pressed, "#conversation-clear-history")
    def _clear_history_pressed(self, _event: Button.Pressed) -> None:
        clear_history(self.backend.client_id, self.character_id)
        self.state = {"summary": "", "messages": []}
        self._paragraph_visibility.clear()
        self.query_one("#conversation-action", Static).update("")
        self.query_one("#conversation-status", Static).update("Local chat history cleared.")
        self._render_transcript()

    @on(Input.Submitted, "#conversation-input")
    def _submitted(self, event: Input.Submitted) -> None:
        message = event.value.strip()
        if not message or self._send_task is not None:
            return
        event.input.value = ""
        self._send_task = asyncio.create_task(self._send(message))

    async def _send(self, message: str) -> None:
        input_widget = self.query_one("#conversation-input", Input)
        status = self.query_one("#conversation-status", Static)
        action_view = self.query_one("#conversation-action", Static)
        try:
            access = await self._refresh_access()
            if not access.writable:
                return
            input_widget.disabled = True
            self.state.setdefault("messages", []).append({"role": "user", "text": message})
            self.state["messages"] = self.state["messages"][-24:]
            self._render_transcript()
            status.update(f"Waiting for {self.character_name}…")
            action_view.update("")
            self._job = await self.backend.submit_character_chat(
                self.character_id,
                message,
                history_summary=str(self.state.get("summary") or ""),
                history=list(self.state.get("messages") or [])[:-1],
            )
            while self._job.pending:
                action = self._job.action
                if action.tool:
                    action_view.update(
                        f"{format_action_call(action.tool, action.parameters)}: {action.status}"
                    )
                if self._job.reply:
                    status.update(f"Pending action · {self._job.reply}")
                await asyncio.sleep(0.25)
                self._job = await self.backend.poll_character_chat(self._job)
            if self._job.status == "failed":
                raise RuntimeError(self._job.failure or "Chat failed")
            reply = self._job.reply or "…"
            # The user message is already present, so append only the character response.
            reply_message = {"role": "character", "text": reply}
            self.state.setdefault("messages", []).append(reply_message)
            self.state["messages"] = self.state["messages"][-24:]
            if self.preferences.remember_history:
                save_history(self.backend.client_id, self.character_id, self.state)
            self._schedule_paragraph_reveal(reply_message)
            action = self._job.action
            if action.tool:
                detail = action.reason or ", ".join(
                    str(item.get("type") or item) for item in action.result_events
                )
                suffix = f" — {detail}" if detail else ""
                action_view.update(
                    f"{format_action_call(action.tool, action.parameters)}: "
                    f"{action.status}{suffix}"
                )
            status.update("")
            self._render_transcript()
        except asyncio.CancelledError:
            if self._job is not None:
                await self.backend.cancel_character_chat(self._job)
            raise
        except Exception as exc:
            status.update(f"Chat error: {exc}")
        finally:
            self._send_task = None
            input_widget.disabled = not self._access.writable
            if self._access.writable:
                input_widget.focus()

    @on(Button.Pressed, "#conversation-controller-assign")
    async def _assign_controller_pressed(self, _event: Button.Pressed) -> None:
        select = self.query_one("#conversation-controller", Select)
        assign = self.query_one("#conversation-controller-assign", Button)
        selected = str(select.value)
        if not selected or selected not in {
            choice.controller_id for choice in self._access.controllers
        }:
            return
        assign.disabled = True
        status = self.query_one("#conversation-status", Static)
        status.update("Assigning LLM controller…")
        try:
            self._access = await self.backend.assign_character_chat_controller(
                self.character_id,
                selected,
            )
            await self._refresh_access()
        except Exception as exc:
            status.update(f"Controller assignment failed: {exc}")
            assign.disabled = False

    @on(Button.Pressed, "#conversation-sheet")
    async def _sheet_pressed(self, _event: Button.Pressed) -> None:
        try:
            profile = await self.backend.fetch_character_profile(self.character_id)
        except Exception as exc:
            self.query_one("#conversation-status", Static).update(f"Sheet error: {exc}")
            return
        self.app.push_screen(CharacterSheetScreen(profile))

    @on(Button.Pressed, "#conversation-close")
    async def _close_pressed(self, _event: Button.Pressed) -> None:
        await self.action_close()

    async def action_close(self) -> None:
        if self._send_task is not None:
            self._send_task.cancel()
            await asyncio.gather(self._send_task, return_exceptions=True)
        if self.preferences.remember_history:
            save_history(self.backend.client_id, self.character_id, self.state)
        self.dismiss(None)


class TerminalSetupScreen(ModalScreen[TerminalConfig | None]):
    BINDINGS = [("escape", "cancel", "Cancel")]

    CSS = """
    TerminalSetupScreen { align: center middle; }
    #terminal-setup {
        width: 70; height: auto; max-height: 90%; border: thick $accent;
        background: $surface; padding: 1 2;
    }
    .setup-label { margin-top: 1; color: $text-muted; }
    #terminal-setup-buttons { height: auto; margin-top: 1; }
    #terminal-setup-save { margin-right: 1; }
    """

    PROVIDERS = (
        ("Local Ollama", "ollama-local"),
        ("Ollama Cloud", "ollama-cloud"),
        ("OpenRouter", "openrouter"),
        ("No chat", "no-chat"),
    )

    def compose(self) -> ComposeResult:
        with Vertical(id="terminal-setup"):
            yield Label("Set up character chat", id="terminal-setup-title")
            yield Static(
                "Choose a provider for local terminal chat. "
                "API keys are read only from the environment."
            )
            yield Label("Provider", classes="setup-label")
            yield Select(
                self.PROVIDERS, value="ollama-local", allow_blank=False, id="setup-provider"
            )
            yield Label("Model", classes="setup-label")
            yield Input(value="deepseek-v4-flash", id="setup-model")
            yield Label("Ollama endpoint", classes="setup-label")
            yield Input(value="http://127.0.0.1:11434", id="setup-ollama-host")
            yield Label("OpenRouter endpoint", classes="setup-label")
            yield Input(value="https://openrouter.ai/api/v1", id="setup-openrouter-url")
            yield Static("", id="setup-error")
            with Horizontal(id="terminal-setup-buttons"):
                yield Button("Save", id="terminal-setup-save", variant="primary")
                yield Button("Cancel", id="terminal-setup-cancel")

    @on(Button.Pressed, "#terminal-setup-save")
    def _save_pressed(self, _event: Button.Pressed) -> None:
        selected = str(self.query_one("#setup-provider", Select).value)
        model = self.query_one("#setup-model", Input).value.strip()
        if selected != "no-chat" and not model:
            self.query_one("#setup-error", Static).update("Choose a model or select no chat.")
            return
        self.dismiss(
            TerminalConfig(
                chat_enabled=selected != "no-chat",
                chat_provider="ollama-local" if selected == "no-chat" else selected,
                chat_model=model or "deepseek-v4-flash",
                ollama_host=self.query_one("#setup-ollama-host", Input).value.strip() or None,
                openrouter_server_url=self.query_one("#setup-openrouter-url", Input).value.strip()
                or None,
            )
        )

    @on(Button.Pressed, "#terminal-setup-cancel")
    def _cancel_pressed(self, _event: Button.Pressed) -> None:
        self.action_cancel()

    def action_cancel(self) -> None:
        self.dismiss(None)


__all__ = [
    "CharacterPickerScreen",
    "CharacterSheetScreen",
    "ContentWarningScreen",
    "ConversationScreen",
    "TerminalSetupScreen",
    "render_character_profile",
]
