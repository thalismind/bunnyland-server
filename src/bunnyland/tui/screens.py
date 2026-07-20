"""Reusable Textual screens shared by the TUI, REPL, and focused chat app."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, OptionList, Select, Static
from textual.widgets.option_list import Option

from ..server.v1_models import CharacterProfileResource
from ..terminal_chat import load_history, save_history
from ..terminal_config import TerminalConfig
from .backend import Backend, CharacterChatJob


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
    #conversation-buttons { height: auto; margin-top: 1; }
    #conversation-sheet { margin-right: 1; }
    """

    def __init__(self, backend: Backend, character_id: str, character_name: str) -> None:
        super().__init__()
        self.backend = backend
        self.character_id = character_id
        self.character_name = character_name
        self.state = load_history(backend.client_id, character_id)
        self._job: CharacterChatJob | None = None
        self._send_task: asyncio.Task | None = None

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
            with Horizontal(id="conversation-buttons"):
                yield Button("Sheet", id="conversation-sheet")
                yield Button("Close", id="conversation-close", variant="primary")

    async def on_mount(self) -> None:
        self._render_transcript()
        available, reason = await self.backend.character_chat_availability()
        if not available:
            self.query_one("#conversation-status", Static).update(reason)
            self.query_one("#conversation-input", Input).disabled = True
        else:
            self.query_one("#conversation-input", Input).focus()

    def _render_transcript(self) -> None:
        transcript = Text()
        for item in self.state.get("messages") or []:
            role = item.get("role")
            label = "You" if role == "user" else self.character_name
            style = "bold cyan" if role == "user" else "bold green"
            if len(transcript):
                transcript.append("\n\n")
            transcript.append(f"{label}: ", style=style)
            transcript.append(str(item.get("text") or ""))
        self.query_one("#conversation-transcript", Static).update(transcript)
        self.query_one("#conversation-transcript-scroll", VerticalScroll).scroll_end(animate=False)

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
        input_widget.disabled = True
        self.state.setdefault("messages", []).append({"role": "user", "text": message})
        self.state["messages"] = self.state["messages"][-24:]
        self._render_transcript()
        status.update(f"Waiting for {self.character_name}…")
        action_view.update("")
        try:
            self._job = await self.backend.submit_character_chat(
                self.character_id,
                message,
                history_summary=str(self.state.get("summary") or ""),
                history=list(self.state.get("messages") or [])[:-1],
            )
            while self._job.pending:
                if self._job.reply:
                    status.update(f"Pending action · {self._job.reply}")
                await asyncio.sleep(0.25)
                self._job = await self.backend.poll_character_chat(self._job)
            if self._job.status == "failed":
                raise RuntimeError(self._job.failure or "Chat failed")
            reply = self._job.reply or "…"
            # The user message is already present, so append only the character response.
            self.state.setdefault("messages", []).append({"role": "character", "text": reply})
            self.state["messages"] = self.state["messages"][-24:]
            save_history(self.backend.client_id, self.character_id, self.state)
            action = self._job.action
            if action.tool:
                detail = action.reason or ", ".join(
                    str(item.get("type") or item) for item in action.result_events
                )
                suffix = f" — {detail}" if detail else ""
                action_view.update(f"{action.tool}: {action.status}{suffix}")
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
            input_widget.disabled = False
            input_widget.focus()

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
    "ConversationScreen",
    "TerminalSetupScreen",
    "render_character_profile",
]
