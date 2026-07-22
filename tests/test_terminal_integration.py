from __future__ import annotations

from types import SimpleNamespace

from textual.widgets import Input, Select

from bunnyland.chat import CharacterChatApp
from bunnyland.repl.app import BunnylandReplApp
from bunnyland.repl.client import BunnylandRepl, OpenChatIntent, OpenSheetIntent
from bunnyland.server.models import CharacterSummaryView
from bunnyland.server.v1_models import CharacterProfileResource
from bunnyland.tui.app import BunnylandTUI
from bunnyland.tui.backend import Backend, LocalBackend, SubmitResult
from bunnyland.tui.generator_selector import GeneratorSelection, WorldGeneratorSelector
from bunnyland.tui.model import World
from bunnyland.tui.screens import (
    CharacterPickerScreen,
    ContentWarningScreen,
    ConversationScreen,
    TerminalSetupScreen,
)


class EmptyBackend(Backend):
    label = "test"
    supports_character_sheets = True
    supports_character_chat = True
    client_id = "client-1"

    def __init__(self):
        self.started = False
        self.closed = False

    async def start(self):
        self.started = True

    async def close(self):
        self.closed = True

    async def fetch_snapshot(self):
        return {"world_epoch": 0, "entities": []}

    async def fetch_character_list(self):
        return [CharacterSummaryView(character_id="character:1", name="Juniper")]

    async def fetch_character_projection(self, _character_id):
        return None

    async def fetch_character_profile(self, _character_id):
        return CharacterProfileResource.model_validate(
            {
                "world_id": "world-1",
                "world_epoch": 0,
                "character_id": "character:1",
                "character_name": "Juniper",
                "controller": {
                    "controller_id": "controller:llm",
                    "generation": 1,
                    "kind": "llm",
                    "name": "default",
                },
            }
        )

    async def recent_events(self, _character_id=""):
        return []

    async def submit(self, _command):
        return SubmitResult(True)

    async def claim(self, _player_id, _world):
        return None

    async def character_chat_availability(self):
        return True, ""


class FlaggedBackend(EmptyBackend):
    async def fetch_content_flags(self):
        return ("adult:violence", "pvp")


async def test_terminal_player_clients_block_loading_until_content_warning_acceptance():
    for app in (BunnylandTUI(FlaggedBackend()), BunnylandReplApp(FlaggedBackend())):
        async with app.run_test() as pilot:
            warning = next(
                screen for screen in app.screen_stack if isinstance(screen, ContentWarningScreen)
            )
            assert warning.content_flags == ("adult:violence", "pvp")
            await pilot.click("#content-warning-accept")
            await pilot.pause()
            assert not any(isinstance(screen, ContentWarningScreen) for screen in app.screen_stack)


async def test_terminal_player_clients_skip_configured_ignored_content_flags():
    for app in (
        BunnylandTUI(FlaggedBackend(), ignored_content_flags=("adult:violence", "pvp")),
        BunnylandReplApp(FlaggedBackend(), ignored_content_flags=("adult:violence", "pvp")),
    ):
        async with app.run_test() as pilot:
            await pilot.pause()
            assert not any(isinstance(screen, ContentWarningScreen) for screen in app.screen_stack)


async def test_terminal_player_clients_leave_flagged_world_when_warning_is_declined(
    monkeypatch,
):
    for app in (BunnylandTUI(FlaggedBackend()), BunnylandReplApp(FlaggedBackend())):
        exits = []
        monkeypatch.setattr(
            app,
            "exit",
            lambda *args, exits=exits, **kwargs: exits.append(True),
        )
        async with app.run_test() as pilot:
            await pilot.click("#content-warning-decline")
            await pilot.pause()
            assert exits == [True]


async def test_repl_sheet_and_chat_commands_emit_typed_ui_intents():
    backend = EmptyBackend()
    repl = BunnylandRepl(backend)
    repl.character_list = await backend.fetch_character_list()
    repl.player_id = "character:1"

    sheet = await repl.dispatch("sheet")
    chat = await repl.dispatch("chat Jun")

    assert sheet == OpenSheetIntent("character:1", "Juniper")
    assert chat == OpenChatIntent("character:1", "Juniper")
    assert sheet.plain == "Open sheet: Juniper"
    assert chat.plain == "Open chat: Juniper"
    assert repl.complete("chat Ju") == ["chat Juniper"]

    repl.player_id = ""
    assert "Usage" in (await repl.dispatch("chat")).plain
    assert "No character chat target" in (await repl.dispatch("chat Nobody")).plain


async def test_repl_app_opens_conversation_from_chat_intent(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    backend = EmptyBackend()
    app = BunnylandReplApp(backend)
    async with app.run_test() as pilot:
        command = app.query_one("#cmd", Input)
        command.value = "chat Juniper"
        await pilot.press("enter")
        await pilot.pause()
        assert any(isinstance(screen, ConversationScreen) for screen in app.screen_stack)


async def test_tui_chat_without_current_character_uses_picker(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    backend = EmptyBackend()
    app = BunnylandTUI(backend)
    async with app.run_test() as pilot:
        await app.action_open_chat()
        await pilot.pause()
        picker = next(
            screen for screen in app.screen_stack if isinstance(screen, CharacterPickerScreen)
        )
        picker._selected(SimpleNamespace(option=SimpleNamespace(id="character:1")))
        await pilot.pause()
        assert any(isinstance(screen, ConversationScreen) for screen in app.screen_stack)


async def test_standalone_chat_starts_with_character_picker(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    backend = EmptyBackend()
    app = CharacterChatApp(backend)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert backend.started is True
        picker = next(
            screen for screen in app.screen_stack if isinstance(screen, CharacterPickerScreen)
        )
        picker._selected(SimpleNamespace(option=SimpleNamespace(id="character:1")))
        await pilot.pause()
        conversation = next(
            screen for screen in app.screen_stack if isinstance(screen, ConversationScreen)
        )
        await conversation.action_close()
        await pilot.pause()
        assert any(isinstance(screen, CharacterPickerScreen) for screen in app.screen_stack)
    assert backend.closed is True


class SetupLocalBackend(LocalBackend):
    def __init__(self):
        super().__init__(autorun=False)
        self.started = False

    async def start(self):
        self.started = True

    async def close(self):
        return None

    async def fetch_character_list(self):
        return []

    async def fetch_content_flags(self):
        return ()

    async def fetch_character_projection(self, _character_id):
        return None

    async def recent_events(self, _character_id=""):
        return []

    async def fetch_snapshot(self):
        return {"world_epoch": 0, "entities": []}


def _choose_no_chat(screen: TerminalSetupScreen) -> None:
    screen.query_one("#setup-provider", Select).value = "no-chat"
    screen.query_one("#setup-model", Input).value = ""
    screen._save_pressed(SimpleNamespace())


async def test_first_local_tui_runs_setup_before_start(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    backend = SetupLocalBackend()
    app = BunnylandTUI(backend)
    app.needs_chat_setup = True
    async with app.run_test() as pilot:
        assert backend.started is False
        setup = next(
            screen for screen in app.screen_stack if isinstance(screen, TerminalSetupScreen)
        )
        _choose_no_chat(setup)
        await pilot.pause()
        assert backend.started is True
        assert backend.chat_config.enabled is False


async def test_first_local_repl_runs_setup_before_start(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    backend = SetupLocalBackend()
    app = BunnylandReplApp(backend)
    app.needs_chat_setup = True
    async with app.run_test() as pilot:
        assert backend.started is False
        setup = next(
            screen for screen in app.screen_stack if isinstance(screen, TerminalSetupScreen)
        )
        _choose_no_chat(setup)
        await pilot.pause()
        assert backend.started is True
        assert backend.chat_config.enabled is False


async def test_standalone_chat_wanted_character_closes_app(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    backend = EmptyBackend()
    app = CharacterChatApp(backend, character="Juniper")
    async with app.run_test() as pilot:
        await pilot.pause()
        conversation = next(
            screen for screen in app.screen_stack if isinstance(screen, ConversationScreen)
        )
        await conversation.action_close()
        await pilot.pause()
        assert app._exit is True


async def test_standalone_chat_reports_start_empty_and_unknown_character(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    class Failing(EmptyBackend):
        async def start(self):
            raise RuntimeError("world failed")

    failing = CharacterChatApp(Failing())
    async with failing.run_test():
        assert "world failed" in failing.query_one("#chat-app-status").render().plain

    class Empty(EmptyBackend):
        async def fetch_character_list(self):
            return []

    empty = CharacterChatApp(Empty())
    async with empty.run_test():
        assert "No characters" in empty.query_one("#chat-app-status").render().plain

    unknown = CharacterChatApp(EmptyBackend(), character="Nobody")
    async with unknown.run_test():
        assert "No such character" in unknown.query_one("#chat-app-status").render().plain
        unknown._open_conversation("missing")


async def test_standalone_first_run_setup_cancel_and_success(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    cancelled = CharacterChatApp(SetupLocalBackend(), needs_chat_setup=True)
    async with cancelled.run_test() as pilot:
        cancelled._chat_setup_selected(None)
        await pilot.pause()
        assert cancelled._exit is True

    backend = SetupLocalBackend()
    app = CharacterChatApp(backend, needs_chat_setup=True)
    async with app.run_test() as pilot:
        setup = next(
            screen for screen in app.screen_stack if isinstance(screen, TerminalSetupScreen)
        )
        _choose_no_chat(setup)
        await pilot.pause()
        assert backend.started is True


async def test_standalone_setup_error_reopens_and_generator_selection(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    backend = SetupLocalBackend()
    app = CharacterChatApp(backend, needs_chat_setup=True)
    async with app.run_test() as pilot:
        from bunnyland.terminal_config import TerminalConfig

        app._chat_setup_selected(TerminalConfig(chat_provider="openrouter"))
        await pilot.pause()
        assert len([s for s in app.screen_stack if isinstance(s, TerminalSetupScreen)]) >= 2

    selector_backend = SetupLocalBackend()
    selector = CharacterChatApp(selector_backend, show_generator_selector=True)
    async with selector.run_test() as pilot:
        assert any(isinstance(s, WorldGeneratorSelector) for s in selector.screen_stack)
        selector._generator_selected(GeneratorSelection(generator="empty", seed="quiet clearing"))
        await pilot.pause()
        assert selector_backend.started is True

    cancelled_selector = CharacterChatApp(SetupLocalBackend(), show_generator_selector=True)
    async with cancelled_selector.run_test() as pilot:
        cancelled_selector._generator_selected(None)
        await pilot.pause()
        assert cancelled_selector._exit is True


def _minimal_profile() -> CharacterProfileResource:
    return CharacterProfileResource(
        world_id="world-1",
        world_epoch=0,
        character_id="character:1",
        character_name="Juniper",
    )


async def test_repl_app_opens_sheet_and_reports_sheet_error(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    class Profiles(EmptyBackend):
        async def fetch_character_profile(self, _character_id):
            return _minimal_profile()

    app = BunnylandReplApp(Profiles())
    async with app.run_test() as pilot:
        field = app.query_one("#cmd", Input)
        field.value = "sheet Juniper"
        await pilot.press("enter")
        await pilot.pause()
        from bunnyland.tui.screens import CharacterSheetScreen

        assert any(isinstance(screen, CharacterSheetScreen) for screen in app.screen_stack)

    class BrokenProfile(EmptyBackend):
        async def fetch_character_profile(self, _character_id):
            raise RuntimeError("sheet offline")

    broken = BunnylandReplApp(BrokenProfile())
    async with broken.run_test() as pilot:
        field = broken.query_one("#cmd", Input)
        field.value = "sheet Juniper"
        await pilot.press("enter")
        await pilot.pause()
        text = "\n".join(
            "".join(segment.text for segment in strip._segments) for strip in broken.log_view.lines
        )
        assert "sheet offline" in text


async def test_tui_native_sheet_success_error_and_chat_targets(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    class Profiles(EmptyBackend):
        async def fetch_character_profile(self, _character_id):
            return _minimal_profile()

    app = BunnylandTUI(Profiles())
    async with app.run_test() as pilot:
        app.player_id = "character:1"
        app.character_list = await app.backend.fetch_character_list()
        await app.action_open_sheet()
        from bunnyland.tui.screens import CharacterSheetScreen

        assert any(isinstance(screen, CharacterSheetScreen) for screen in app.screen_stack)
        await pilot.press("escape")
        await app.action_open_chat()
        await pilot.pause()
        assert any(isinstance(screen, ConversationScreen) for screen in app.screen_stack)

    class BrokenProfile(Profiles):
        async def fetch_character_profile(self, _character_id):
            raise RuntimeError("sheet offline")

    broken = BunnylandTUI(BrokenProfile())
    async with broken.run_test() as pilot:
        broken.player_id = "character:1"
        broken.character_list = await broken.backend.fetch_character_list()
        await broken.action_open_sheet()
        assert any("sheet offline" in item.plain for item in broken.activity_lines)
        broken.player_id = ""
        broken.character_list = []
        await broken.action_open_chat()
        assert any("No characters" in item.plain for item in broken.activity_lines)
        await broken._open_chat_pressed(SimpleNamespace())
        await pilot.pause()


async def test_tui_chat_prefers_selected_visible_character(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    app = BunnylandTUI(EmptyBackend())
    async with app.run_test() as pilot:
        app.world = World.parse(
            {
                "world_epoch": 0,
                "entities": [
                    {
                        "id": "character:2",
                        "components": {
                            "CharacterComponent": {},
                            "IdentityComponent": {"name": "Marlow", "kind": "character"},
                        },
                        "relationships": {},
                    },
                    {
                        "id": "room:1",
                        "components": {"RoomComponent": {}},
                        "relationships": {},
                    },
                ],
            }
        )
        app.character_list = [CharacterSummaryView(character_id="character:2", name="Marlow")]
        app.selected_id = "character:2"
        await app.action_open_chat()
        await pilot.pause()
        conversation = next(
            screen for screen in app.screen_stack if isinstance(screen, ConversationScreen)
        )
        assert conversation.character_id == "character:2"
        await pilot.press("escape")
        app.selected_id = "room:1"
        app.player_id = "character:2"
        await app.action_open_chat()
        await pilot.pause()
        conversation = next(
            screen for screen in app.screen_stack if isinstance(screen, ConversationScreen)
        )
        assert conversation.character_id == "character:2"


async def test_tui_and_repl_setup_intro_cancel_error_and_generator_branch(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    from bunnyland.terminal_config import TerminalConfig
    from bunnyland.tui.splash import IntroSplash

    for app in (BunnylandTUI(SetupLocalBackend()), BunnylandReplApp(SetupLocalBackend())):
        app.needs_chat_setup = True
        app.show_intro = True
        async with app.run_test() as pilot:
            splash = next(screen for screen in app.screen_stack if isinstance(screen, IntroSplash))
            splash._finish()
            await pilot.pause()
            assert any(isinstance(s, TerminalSetupScreen) for s in app.screen_stack)

    cancelled_tui = BunnylandTUI(SetupLocalBackend())
    cancelled_tui.needs_chat_setup = True
    async with cancelled_tui.run_test() as pilot:
        cancelled_tui._chat_setup_selected(None)
        await pilot.pause()

    cancelled_repl = BunnylandReplApp(SetupLocalBackend())
    cancelled_repl.needs_chat_setup = True
    async with cancelled_repl.run_test() as pilot:
        cancelled_repl._chat_setup_selected(None)
        await pilot.pause()

    for app in (BunnylandTUI(SetupLocalBackend()), BunnylandReplApp(SetupLocalBackend())):
        app.needs_chat_setup = True
        async with app.run_test() as pilot:
            app._chat_setup_selected(TerminalConfig(chat_provider="openrouter"))
            await pilot.pause()
            assert len([s for s in app.screen_stack if isinstance(s, TerminalSetupScreen)]) >= 2

    for app in (BunnylandTUI(SetupLocalBackend()), BunnylandReplApp(SetupLocalBackend())):
        app.needs_chat_setup = True
        app.show_generator_selector = True
        async with app.run_test() as pilot:
            setup = next(
                screen for screen in app.screen_stack if isinstance(screen, TerminalSetupScreen)
            )
            _choose_no_chat(setup)
            await pilot.pause()
            assert any(isinstance(s, WorldGeneratorSelector) for s in app.screen_stack)


def test_tui_and_repl_main_report_config_errors_and_forward_chat_settings(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    import bunnyland.repl.app as repl_module
    import bunnyland.tui.app as tui_module
    from bunnyland.terminal_config import TerminalConfigError

    for module in (tui_module, repl_module):
        monkeypatch.setattr(
            module,
            "load_terminal_config",
            lambda: (_ for _ in ()).throw(TerminalConfigError("bad terminal config")),
        )
        with __import__("pytest").raises(SystemExit, match="bad terminal config"):
            module.main(["--generator", "empty"])
        monkeypatch.undo()
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    created = []
    created_apps = []

    class LocalStub:
        def __init__(self, **kwargs):
            created.append(kwargs)

    class TuiAppStub:
        def __init__(self, _backend):
            created_apps.append(self)
            self.show_generator_selector = False
            self.show_icons = True
            self.show_intro = False
            self.needs_chat_setup = False

        def run(self): ...

    class ReplAppStub:
        def __init__(self, _backend):
            created_apps.append(self)
            self.repl = SimpleNamespace(show_icons=True)
            self.show_generator_selector = False
            self.show_intro = False
            self.needs_chat_setup = False

        def run(self): ...

    monkeypatch.setattr(tui_module, "LocalBackend", LocalStub)
    monkeypatch.setattr(tui_module, "BunnylandTUI", TuiAppStub)
    monkeypatch.setattr(repl_module, "LocalBackend", LocalStub)
    monkeypatch.setattr(repl_module, "BunnylandReplApp", ReplAppStub)
    for module in (tui_module, repl_module):
        assert (
            module.main(
                [
                    "--generator",
                    "empty",
                    "--chat-provider",
                    "ollama-local",
                    "--chat-model",
                    "llama3.2",
                    "--ignore-content-flag",
                    "adult:violence,pvp",
                ]
            )
            == 0
        )
        assert created[-1]["chat_config"].model == "llama3.2"
        assert created_apps[-1].ignored_content_flags == ("adult:violence", "pvp")


def test_tui_and_repl_main_report_missing_cloud_credentials(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    import bunnyland.repl.app as repl_module
    import bunnyland.tui.app as tui_module

    for module in (tui_module, repl_module):
        with __import__("pytest").raises(SystemExit, match="OPENROUTER_API_KEY"):
            module.main(["--generator", "empty", "--chat-provider", "openrouter"])
