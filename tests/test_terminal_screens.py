from __future__ import annotations

import asyncio
from types import SimpleNamespace

from textual.app import App, ComposeResult
from textual.widgets import Input, Select, Static

from bunnyland.server.models import CharacterChatActionResult, CharacterSummaryView
from bunnyland.server.v1_models import CharacterProfileResource
from bunnyland.tui.backend import CharacterChatJob
from bunnyland.tui.screens import (
    CharacterPickerScreen,
    CharacterSheetScreen,
    ConversationScreen,
    TerminalSetupScreen,
    render_character_profile,
)


def _profile() -> CharacterProfileResource:
    return CharacterProfileResource.model_validate(
        {
            "world_id": "world-1",
            "world_epoch": 12,
            "character_id": "character:1",
            "character_name": "Juniper",
            "sheet": {
                "kind": "character",
                "species": "rabbit",
                "biography": "Juniper keeps the neighborhood garden.",
                "description": "A patient gardener.",
                "appearance": "Green overalls.",
                "tags": ["neighbor"],
                "status": ["awake", "content"],
                "vitals": [{"label": "Health", "value": 8, "maximum": 10}],
                "needs": [{"label": "Hunger", "value": 2, "band": "low"}],
                "affect": [{"label": "Joy", "value": 4, "text": "bright"}],
                "profile": [{"label": "Home", "value": "Apartment 3"}],
                "skills": [{"label": "Gardening", "value": "expert"}],
                "traits": ["Kind"],
                "relations": [{"label": "Friend", "value": "Marlow"}],
                "injuries": [{"label": "Scratch", "detail": "healing"}],
                "notes": [{"label": "Reminder", "value": "Water basil"}],
            },
        }
    )


class ScreenHost(App[None]):
    def __init__(self, screen):
        super().__init__()
        self.screen_to_push = screen
        self.result = "unset"

    def compose(self) -> ComposeResult:
        yield Static("host", id="host")

    def on_mount(self) -> None:
        self.push_screen(self.screen_to_push, callback=self._finished)

    def _finished(self, result) -> None:
        self.result = result


def test_character_profile_renderer_includes_all_sections():
    text = render_character_profile(_profile()).plain
    for expected in (
        "Juniper",
        "rabbit",
        "Biography",
        "Status",
        "Vitals",
        "Needs",
        "Affect",
        "Profile",
        "Skills",
        "Traits",
        "Relationships",
        "Injuries",
        "Notes",
        "8/10",
        "bright",
        "healing",
    ):
        assert expected in text

    minimal = CharacterProfileResource(
        world_id="world-1",
        world_epoch=0,
        character_id="character:2",
        character_name="Pib",
    )
    assert render_character_profile(minimal).plain == "Pib\ncharacter"

    sparse = CharacterProfileResource.model_validate(
        {
            "world_id": "world-1",
            "world_epoch": 0,
            "character_id": "character:3",
            "character_name": "Marlow",
            "sheet": {"kind": "", "description": "Description only"},
        }
    )
    assert "Description only" in render_character_profile(sparse).plain
    appearance_only = sparse.model_copy(
        update={"sheet": sparse.sheet.model_copy(update={"description": "", "appearance": "Hat"})}
    )
    assert "Appearance: Hat" in render_character_profile(appearance_only).plain


async def test_character_sheet_screen_renders_scrolls_and_closes():
    host = ScreenHost(CharacterSheetScreen(_profile()))
    async with host.run_test(size=(100, 35)) as pilot:
        screen = host.screen_to_push
        assert "Juniper" in screen.query_one("#sheet-content", Static).render().plain
        await pilot.press("end")
        await pilot.click("#sheet-close")
        await pilot.pause()
        assert host.result is None


async def test_character_picker_selects_and_cancels():
    character = CharacterSummaryView(character_id="character:1", name="Juniper")
    host = ScreenHost(CharacterPickerScreen([character]))
    async with host.run_test() as pilot:
        host.screen_to_push._selected(
            SimpleNamespace(option=SimpleNamespace(id="character:1"))
        )
        await pilot.pause()
        assert host.result == "character:1"

    cancelled = ScreenHost(CharacterPickerScreen([]))
    async with cancelled.run_test() as pilot:
        await pilot.click("#character-picker-cancel")
        await pilot.pause()
        assert cancelled.result is None


async def test_terminal_setup_saves_provider_and_no_chat():
    host = ScreenHost(TerminalSetupScreen())
    async with host.run_test(size=(100, 40)) as pilot:
        screen = host.screen_to_push
        screen.query_one("#setup-provider", Select).value = "openrouter"
        screen.query_one("#setup-model", Input).value = "openai/example"
        screen._save_pressed(SimpleNamespace())
        await pilot.pause()
        assert host.result.chat_provider == "openrouter"
        assert host.result.chat_model == "openai/example"
        assert host.result.chat_enabled is True

    disabled = ScreenHost(TerminalSetupScreen())
    async with disabled.run_test(size=(100, 40)) as pilot:
        screen = disabled.screen_to_push
        screen.query_one("#setup-provider", Select).value = "no-chat"
        screen.query_one("#setup-model", Input).value = ""
        screen.query_one("#setup-ollama-host", Input).value = ""
        screen.query_one("#setup-openrouter-url", Input).value = ""
        screen._save_pressed(SimpleNamespace())
        await pilot.pause()
        assert disabled.result.chat_enabled is False


async def test_terminal_setup_rejects_empty_model_and_cancels():
    host = ScreenHost(TerminalSetupScreen())
    async with host.run_test(size=(100, 40)) as pilot:
        screen = host.screen_to_push
        screen.query_one("#setup-model", Input).value = ""
        screen._save_pressed(SimpleNamespace())
        assert "Choose a model" in screen.query_one("#setup-error", Static).render().plain
        await pilot.click("#terminal-setup-cancel")
        await pilot.pause()
        assert host.result is None


class ConversationBackend:
    client_id = "client-1"
    supports_character_chat = True

    def __init__(self, jobs=(), *, available=True, availability_reason="disabled"):
        self.jobs = list(jobs)
        self.available = available
        self.availability_reason = availability_reason
        self.submitted = []
        self.cancelled = []

    async def character_chat_availability(self):
        return self.available, self.availability_reason

    async def submit_character_chat(self, character_id, message, **kwargs):
        self.submitted.append((character_id, message, kwargs))
        item = self.jobs.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    async def poll_character_chat(self, _job):
        item = self.jobs.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    async def cancel_character_chat(self, job):
        self.cancelled.append(job.id)

    async def fetch_character_profile(self, _character_id):
        return _profile()


def _job(status, *, reply="", action=None, failure=""):
    return CharacterChatJob(
        id="job-1",
        status=status,
        character_id="character:1",
        reply=reply,
        action=action or CharacterChatActionResult(),
        failure=failure,
    )


async def test_conversation_screen_sends_pending_chat_and_renders_action(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    backend = ConversationBackend(
        [
            _job(
                "running",
                reply="I will look.",
                action=CharacterChatActionResult(
                    tool="look", command_id="command-1", status="queued"
                ),
            ),
            _job(
                "succeeded",
                reply="There is a lantern here.",
                action=CharacterChatActionResult(
                    tool="look",
                    command_id="command-1",
                    status="executed",
                    result_events=[{"type": "LookedEvent"}],
                ),
            ),
        ]
    )
    screen = ConversationScreen(backend, "character:1", "Juniper")
    host = ScreenHost(screen)
    async with host.run_test() as pilot:
        field = screen.query_one("#conversation-input", Input)
        field.value = "What do you see?"
        await pilot.press("enter")
        await pilot.pause(0.4)
        transcript = screen.query_one("#conversation-transcript", Static).render().plain
        assert "You: What do you see?" in transcript
        assert "Juniper: There is a lantern here." in transcript
        assert "look: executed" in screen.query_one(
            "#conversation-action", Static
        ).render().plain
        assert backend.submitted[0][2]["history"] == []
        await pilot.click("#conversation-sheet")
        assert any(isinstance(item, CharacterSheetScreen) for item in host.screen_stack)
        await pilot.press("escape")
        await pilot.click("#conversation-close")
        await pilot.pause()


async def test_conversation_screen_disables_unavailable_chat_and_surfaces_errors(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    unavailable = ConversationBackend(available=False, availability_reason="server disabled")
    unavailable_screen = ConversationScreen(unavailable, "character:1", "Juniper")
    host = ScreenHost(unavailable_screen)
    async with host.run_test():
        assert unavailable_screen.query_one("#conversation-input", Input).disabled is True
        assert "server disabled" in unavailable_screen.query_one(
            "#conversation-status", Static
        ).render().plain

    failed = ConversationBackend([RuntimeError("provider unavailable")])
    failed_screen = ConversationScreen(failed, "character:1", "Juniper")
    failed_host = ScreenHost(failed_screen)
    async with failed_host.run_test() as pilot:
        failed_screen.query_one("#conversation-input", Input).value = "Hello"
        await pilot.press("enter")
        await pilot.pause()
        assert "provider unavailable" in failed_screen.query_one(
            "#conversation-status", Static
        ).render().plain
        assert failed_screen.query_one("#conversation-input", Input).disabled is False


async def test_conversation_screen_handles_failed_job_blank_submissions_and_sheet_error(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    backend = ConversationBackend([_job("failed")])

    async def failed_profile(_character_id):
        raise RuntimeError("profile unavailable")

    backend.fetch_character_profile = failed_profile
    screen = ConversationScreen(backend, "character:1", "Juniper")
    host = ScreenHost(screen)
    async with host.run_test() as pilot:
        field = screen.query_one("#conversation-input", Input)
        screen._submitted(SimpleNamespace(value=" ", input=field))
        screen._send_task = asyncio.current_task()
        screen._submitted(SimpleNamespace(value="hello", input=field))
        screen._send_task = None
        await screen._send("hello")
        assert "Chat failed" in screen.query_one("#conversation-status", Static).render().plain
        await screen._sheet_pressed(SimpleNamespace())
        assert "profile unavailable" in screen.query_one(
            "#conversation-status", Static
        ).render().plain
        await screen._close_pressed(SimpleNamespace())
        await pilot.pause()


async def test_conversation_screen_success_without_action_uses_ellipsis(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    backend = ConversationBackend([_job("succeeded")])
    screen = ConversationScreen(backend, "character:1", "Juniper")
    host = ScreenHost(screen)
    async with host.run_test():
        await screen._send("hello")
        assert "Juniper: …" in screen.query_one(
            "#conversation-transcript", Static
        ).render().plain


async def test_conversation_cancellation_before_submission_completes(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    backend = ConversationBackend()
    waiting = asyncio.Event()

    async def blocked_submit(*_args, **_kwargs):
        await waiting.wait()

    backend.submit_character_chat = blocked_submit
    screen = ConversationScreen(backend, "character:1", "Juniper")
    host = ScreenHost(screen)
    async with host.run_test() as pilot:
        screen.query_one("#conversation-input", Input).value = "Hello"
        await pilot.press("enter")
        await pilot.pause()
        await screen.action_close()
        assert backend.cancelled == []


async def test_conversation_screen_cancels_pending_send(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    backend = ConversationBackend([_job("running")])

    async def blocked_poll(_job):
        await asyncio.Event().wait()

    backend.poll_character_chat = blocked_poll
    screen = ConversationScreen(backend, "character:1", "Juniper")
    host = ScreenHost(screen)
    async with host.run_test() as pilot:
        screen.query_one("#conversation-input", Input).value = "Hello"
        await pilot.press("enter")
        await pilot.pause(0.3)
        await screen.action_close()
        assert backend.cancelled == ["job-1"]
