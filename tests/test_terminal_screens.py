from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Button, Checkbox, Input, Link, Select, Static

from bunnyland.server.models import (
    CharacterChatActionResult,
    CharacterChatMediaJobReference,
    CharacterSummaryView,
)
from bunnyland.server.v1_models import CharacterProfileResource
from bunnyland.terminal_chat import (
    history_path,
    load_chat_preferences,
    load_history,
    save_history,
)
from bunnyland.tui.backend import (
    Backend,
    CharacterChatAccess,
    CharacterChatController,
    CharacterChatJob,
    CharacterChatMediaJob,
)
from bunnyland.tui.screens import (
    CharacterPickerScreen,
    CharacterSheetScreen,
    ContentWarningScreen,
    ConversationScreen,
    TerminalSetupScreen,
    WorldIntroductionScreen,
    render_character_profile,
)


def _profile() -> CharacterProfileResource:
    return CharacterProfileResource.model_validate(
        {
            "world_id": "world-1",
            "world_epoch": 12,
            "character_id": "character:1",
            "character_name": "Juniper",
            "portrait": {"url": "https://images.example/juniper.png"},
            "room": {"id": "room:garden", "title": "Community Garden"},
            "points": {"action": 4, "action_max": 5, "focus": 2, "focus_max": 3},
            "controller": {
                "controller_id": "controller:llm",
                "detail": "ollama/qwen",
                "generation": 1,
                "kind": "llm",
                "name": "default",
            },
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
        "ID: character:1",
        "Room: Community Garden",
        "Controller: llm: default · ollama/qwen · controller:llm gen 1",
        "Action Points: 4/5",
        "Focus Points: 2/3",
        "Portrait: https://images.example/juniper.png",
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
    assert render_character_profile(minimal).plain == (
        "Pib\ncharacter\n\nDetails\nID: character:2\nRoom: —\nController: —"
        "\nAction Points: 0/0\nFocus Points: 0/0"
    )

    sparse = CharacterProfileResource.model_validate(
        {
            "world_id": "world-1",
            "world_epoch": 0,
            "character_id": "character:3",
            "character_name": "Marlow",
            "controller": {"controller_id": "controller:fallback", "generation": 2},
            "sheet": {"kind": "", "description": "Description only"},
        }
    )
    sparse_text = render_character_profile(sparse).plain
    assert "Description only" in sparse_text
    assert (
        "Controller: controller:fallback · controller:fallback gen 2" in sparse_text
    )
    appearance_only = sparse.model_copy(
        update={
            "room": sparse.room.model_copy(update={"id": "room:attic"}),
            "sheet": sparse.sheet.model_copy(update={"description": "", "appearance": "Hat"}),
        }
    )
    appearance_text = render_character_profile(appearance_only).plain
    assert "Appearance: Hat" in appearance_text
    assert "Room: room:attic" in appearance_text


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
        host.screen_to_push._selected(SimpleNamespace(option=SimpleNamespace(id="character:1")))
        await pilot.pause()
        assert host.result == "character:1"

    cancelled = ScreenHost(CharacterPickerScreen([]))
    async with cancelled.run_test() as pilot:
        await pilot.click("#character-picker-cancel")
        await pilot.pause()
        assert cancelled.result is None


async def test_content_warning_requires_acceptance_or_decline():
    accepted = ScreenHost(ContentWarningScreen(("adult:violence", "pvp")))
    async with accepted.run_test() as pilot:
        assert (
            "adult:violence"
            in accepted.screen_to_push.query_one("#content-warning-flags Static", Static)
            .render()
            .plain
        )
        await pilot.click("#content-warning-accept")
        await pilot.pause()
        assert accepted.result is True

    declined = ScreenHost(ContentWarningScreen(("theft",)))
    async with declined.run_test() as pilot:
        await pilot.click("#content-warning-decline")
        await pilot.pause()
        assert declined.result is False


async def test_world_introduction_has_padded_content_and_mutually_exclusive_skip_scopes():
    host = ScreenHost(
        WorldIntroductionScreen("Clover City", "Mind the foxes after dark.")
    )
    async with host.run_test(size=(100, 35)) as pilot:
        screen = host.screen_to_push
        assert screen.world_title == "Clover City"
        assert screen.world_description == "Mind the foxes after dark."
        assert "padding: 1 2" in screen.CSS
        world = screen.query_one("#world-introduction-skip-world", Checkbox)
        all_worlds = screen.query_one("#world-introduction-skip-all", Checkbox)
        world.value = True
        await pilot.pause()
        all_worlds.value = True
        await pilot.pause()
        assert world.value is False
        assert all_worlds.value is True
        await pilot.click("#world-introduction-continue")
        await pilot.pause()
        assert host.result == "all"

    world_host = ScreenHost(WorldIntroductionScreen("Clover City", "Welcome."))
    async with world_host.run_test(size=(100, 35)) as pilot:
        screen = world_host.screen_to_push
        all_worlds = screen.query_one("#world-introduction-skip-all", Checkbox)
        all_worlds.value = True
        await pilot.pause()
        all_worlds.value = False
        await pilot.pause()
        screen.query_one("#world-introduction-skip-world", Checkbox).value = True
        await pilot.pause()
        await pilot.click("#world-introduction-continue")
        await pilot.pause()
        assert world_host.result == "world"


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
    supports_character_chat_media_tools = False
    supports_chat_image_requests = False
    supports_chat_video_requests = False

    def __init__(
        self,
        jobs=(),
        *,
        available=True,
        availability_reason="disabled",
        controllers=(),
        profile=None,
    ):
        self.jobs = list(jobs)
        self.available = available
        self.availability_reason = availability_reason
        self.submitted = []
        self.cancelled = []
        self.controllers = tuple(controllers)
        self.assignments = []
        self.profile = profile or _profile()

    async def character_chat_availability(self):
        return self.available, self.availability_reason

    async def character_chat_access(self, character_id):
        return await Backend.character_chat_access(self, character_id)

    async def assignable_character_chat_controllers(self):
        return self.controllers

    async def assign_character_chat_controller(self, character_id, controller_id):
        self.assignments.append((character_id, controller_id))
        self.controllers = ()
        return CharacterChatAccess(writable=True)

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
        return self.profile


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
                    tool="look",
                    parameters={"target_id": "red apple"},
                    command_id="command-1",
                    status="queued",
                ),
            ),
            _job(
                "succeeded",
                reply="There is a lantern here.",
                action=CharacterChatActionResult(
                    tool="look",
                    parameters={"target_id": "red apple"},
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
        assert "look — target: red apple: executed" in screen.query_one(
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
        assert (
            "server disabled"
            in unavailable_screen.query_one("#conversation-status", Static).render().plain
        )

    failed = ConversationBackend([RuntimeError("provider unavailable")])
    failed_screen = ConversationScreen(failed, "character:1", "Juniper")
    failed_host = ScreenHost(failed_screen)
    async with failed_host.run_test() as pilot:
        failed_screen.query_one("#conversation-input", Input).value = "Hello"
        await pilot.press("enter")
        await pilot.pause()
        assert (
            "provider unavailable"
            in failed_screen.query_one("#conversation-status", Static).render().plain
        )
        assert failed_screen.query_one("#conversation-input", Input).disabled is False


async def test_conversation_screen_handles_failed_job_blank_submissions_and_sheet_error(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    backend = ConversationBackend([_job("failed")])

    async def failed_profile(_character_id):
        raise RuntimeError("profile unavailable")

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
        backend.fetch_character_profile = failed_profile
        await screen._sheet_pressed(SimpleNamespace())
        assert (
            "profile unavailable" in screen.query_one("#conversation-status", Static).render().plain
        )
        await screen._close_pressed(SimpleNamespace())
        await pilot.pause()


async def test_conversation_screen_success_without_action_uses_ellipsis(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    backend = ConversationBackend([_job("succeeded")])
    screen = ConversationScreen(backend, "character:1", "Juniper")
    host = ScreenHost(screen)
    async with host.run_test():
        await screen._send("hello")
        assert "Juniper: …" in screen.query_one("#conversation-transcript", Static).render().plain


async def test_conversation_screen_polls_character_media_and_saves_opt_in(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    class MediaBackend(ConversationBackend):
        supports_character_chat_media_tools = True
        supports_chat_image_requests = True
        supports_chat_video_requests = True

        async def poll_character_chat_media(self, job):
            return CharacterChatMediaJob(
                id=job.id,
                status="succeeded",
                character_id=job.character_id,
                kind=job.kind,
                url="https://media.example/character.png",
            )

    backend = MediaBackend([
        _job(
            "succeeded",
            reply="I pictured it.",
            action=CharacterChatActionResult(
                tool="request_chat_image",
                status="executed",
                media_job=CharacterChatMediaJobReference(
                    id="media-character",
                    kind="chat_image",
                    status="queued",
                ),
            ),
        )
    ])
    screen = ConversationScreen(backend, "character:1", "Juniper")
    host = ScreenHost(screen)
    async with host.run_test() as pilot:
        allow = screen.query_one("#conversation-allow-character-media", Checkbox)
        allow.value = True
        await pilot.pause()
        await screen._send("Picture it")
        assert load_chat_preferences().allow_character_media is True
        assert backend.submitted[0][2]["allow_character_media"] is True
        assert screen.query_one("#conversation-media", Static).render().plain.startswith(
            "📷 ready"
        )
        link = screen.query_one("#conversation-media-link", Link)
        assert link.display is True
        assert link.url == "https://media.example/character.png"


async def test_conversation_screen_reports_and_cancels_media_requests(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    class FailedMediaBackend(ConversationBackend):
        supports_chat_image_requests = True
        supports_chat_video_requests = True

        async def request_character_chat_media(self, *_args, **_kwargs):
            raise RuntimeError("generator offline")

    failed_screen = ConversationScreen(
        FailedMediaBackend(), "character:1", "Juniper"
    )
    failed_host = ScreenHost(failed_screen)
    async with failed_host.run_test():
        await failed_screen._poll_media(
            CharacterChatMediaJob(
                id="failed",
                status="failed",
                character_id="character:1",
                kind="chat_image",
                failure="render failed",
            )
        )
        assert failed_screen.query_one("#conversation-media-link", Link).display is False
        await failed_screen._request_media("chat_video")
        assert "🎬 failed · generator offline" in failed_screen.query_one(
            "#conversation-media", Static
        ).render().plain

    class WaitingMediaBackend(ConversationBackend):
        supports_chat_image_requests = True

        async def request_character_chat_media(self, *_args, **_kwargs):
            await asyncio.Event().wait()

    waiting_screen = ConversationScreen(
        WaitingMediaBackend(), "character:1", "Juniper"
    )
    waiting_host = ScreenHost(waiting_screen)
    async with waiting_host.run_test() as pilot:
        waiting_screen._start_media_request("chat_image")
        task = waiting_screen._media_task
        waiting_screen._start_media_request("chat_image")
        assert waiting_screen._media_task is task
        await pilot.pause()
        await waiting_screen.action_close()
        assert task is not None and task.cancelled()


async def test_conversation_screen_separates_reply_paragraphs_with_visual_delay(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    reply = "First thought.\n\nSecond thought.\n\nThird thought."
    backend = ConversationBackend([_job("succeeded", reply=reply)])
    screen = ConversationScreen(backend, "character:1", "Juniper")
    host = ScreenHost(screen)
    async with host.run_test() as pilot:
        reveals: asyncio.Queue[int] = asyncio.Queue()
        reveal_paragraph = screen._reveal_paragraph

        def record_reveal(key: int, visible: int, total: int) -> None:
            reveal_paragraph(key, visible, total)
            reveals.put_nowait(visible)

        monkeypatch.setattr(screen, "_reveal_paragraph", record_reveal)
        screen.query_one("#conversation-separate-paragraphs", Checkbox).value = True
        await screen._send("hello")

        transcript = screen.query_one("#conversation-transcript", Static)
        assert transcript.render().plain.count("Juniper:") == 1
        assert "Second thought." not in transcript.render().plain

        saved = load_history(backend.client_id, "character:1")
        assert saved["messages"][-1] == {"role": "character", "text": reply}

        assert await asyncio.wait_for(reveals.get(), timeout=2) == 2
        await pilot.pause()
        assert transcript.render().plain.count("Juniper:") == 2
        assert "Second thought." in transcript.render().plain

        assert await asyncio.wait_for(reveals.get(), timeout=2) == 3
        await pilot.pause()
        assert transcript.render().plain.count("Juniper:") == 3
        assert "Third thought." in transcript.render().plain

        screen._reveal_paragraph(-1, 2, 3)
        screen.query_one("#conversation-separate-paragraphs", Checkbox).value = False
        await pilot.pause()
        assert transcript.render().plain.count("Juniper:") == 1


async def test_conversation_screen_matches_web_history_and_formatting_controls(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    save_history(
        "client-1",
        "character:1",
        {"summary": "", "messages": [{"role": "character", "text": "**Earlier.**"}]},
    )
    save_history(
        "client-1",
        "character:2",
        {"summary": "", "messages": [{"role": "character", "text": "Other."}]},
    )
    backend = ConversationBackend([_job("succeeded", reply="Session reply.")])
    screen = ConversationScreen(backend, "character:1", "Juniper")
    host = ScreenHost(screen)
    async with host.run_test() as pilot:
        markdown = screen.query_one("#conversation-markdown", Checkbox)
        remember = screen.query_one("#conversation-remember-history", Checkbox)
        paragraphs = screen.query_one("#conversation-separate-paragraphs", Checkbox)
        clear = screen.query_one("#conversation-clear-history", Button)
        transcript = screen.query_one("#conversation-transcript", Static)

        assert markdown.value is True
        assert remember.value is True
        assert paragraphs.value is False
        assert clear.disabled is False
        assert "Earlier." in transcript.render().plain
        assert "**Earlier.**" not in transcript.render().plain

        markdown.value = False
        paragraphs.value = True
        await pilot.pause()
        assert "**Earlier.**" in transcript.render().plain
        preferences = load_chat_preferences()
        assert preferences.markdown is False
        assert preferences.separate_reply_paragraphs is True

        await pilot.click("#conversation-clear-history")
        assert history_path("client-1", "character:1").exists() is False
        assert history_path("client-1", "character:2").exists() is True
        assert clear.disabled is True
        assert "Local chat history cleared." in screen.query_one(
            "#conversation-status", Static
        ).render().plain

        remember.value = False
        await pilot.pause()
        assert history_path("client-1", "character:2").exists() is False
        assert load_chat_preferences().remember_history is False

        await screen._send("Session")
        assert "You: Session" in transcript.render().plain
        assert "Juniper: Session reply." in transcript.render().plain
        assert history_path("client-1", "character:1").exists() is False

        remember.value = True
        await pilot.pause()
        assert load_history("client-1", "character:1")["messages"] == [
            {"role": "user", "text": "Session"},
            {"role": "character", "text": "Session reply."},
        ]

        remember.value = False
        await pilot.pause()
        await screen.action_close()
        assert history_path("client-1", "character:1").exists() is False


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


async def test_conversation_screen_read_only_and_assignment_error_branches(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    save_history(
        "client-1",
        "character:1",
        {
            "summary": "",
            "messages": [
                {"role": "user", "text": "Earlier question."},
                {"role": "character", "text": "Earlier answer."},
            ],
        },
    )
    readonly_profile = _profile().model_copy(
        update={
            "controller": _profile().controller.model_copy(
                update={"controller_id": "controller:web", "kind": "web"}
            )
        }
    )
    choice = CharacterChatController("controller:llm", "default")
    backend = ConversationBackend(profile=readonly_profile, controllers=(choice,))

    async def failed_assignment(_character_id, _controller_id):
        raise RuntimeError("assignment offline")

    backend.assign_character_chat_controller = failed_assignment
    screen = ConversationScreen(backend, "character:1", "Juniper")
    host = ScreenHost(screen)
    async with host.run_test():
        assert screen.query_one("#conversation-input", Input).disabled is True
        await screen._send("must not send")
        assert backend.submitted == []

        select = screen.query_one("#conversation-controller", Select)
        select.value = Select.NULL
        await screen._assign_controller_pressed(SimpleNamespace())
        assert "read-only" in screen.query_one("#conversation-status", Static).render().plain

        select.value = choice.controller_id
        await screen._assign_controller_pressed(SimpleNamespace())
        assert (
            "assignment offline" in screen.query_one("#conversation-status", Static).render().plain
        )
        assert screen.query_one("#conversation-controller-assign").disabled is False

    with pytest.raises(PermissionError, match="cannot assign"):
        await Backend.assign_character_chat_controller(backend, "character:1", choice.controller_id)

    backend.profile = readonly_profile.model_copy(update={"controller": None})
    access = await Backend.character_chat_access(backend, "character:1")
    assert "has no controller" in access.reason
