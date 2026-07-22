from __future__ import annotations

import json
import urllib.error
from unittest.mock import patch

import pytest

from bunnyland import chat
from bunnyland.server.models import CharacterChatActionResult, CharacterSummaryView
from bunnyland.tui.backend import (
    CharacterChatAccess,
    CharacterChatController,
    CharacterChatJob,
    RemoteBackend,
)


class FakeResponse:
    def __init__(self, payload: dict, *, headers: dict | None = None):
        self.payload = payload
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")

    def close(self):
        return None


def test_chat_client_keeps_bounded_history_in_payload():
    state = {"summary": "old context", "messages": []}
    for index in range(chat.HISTORY_LIMIT + 4):
        chat.append_exchange(state, f"user {index}", f"reply {index}")

    assert len(state["messages"]) == chat.HISTORY_LIMIT
    payload = chat.request_payload("client-1", state, "next")
    assert payload["kind"] == "chat"
    assert payload["history_summary"] == "old context"
    assert len(payload["history"]) == chat.HISTORY_LIMIT
    assert payload["message"] == "next"


def test_chat_client_history_round_trips_under_config_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    state = {"summary": "", "messages": [{"role": "user", "text": "hello"}]}

    chat.save_history("client:1", "character:1", state)
    loaded = chat.load_history("client:1", "character:1")

    assert loaded == state
    assert chat.history_path("client:1", "character:1").name == "client_1-character_1.json"


def test_chat_client_save_history_ignores_write_error(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setattr(
        chat.Path,
        "write_text",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError()),
    )

    chat.save_history("client", "character", {"summary": "", "messages": []})


def test_chat_client_persistent_client_id_reuses_existing(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    path = chat.config_dir() / "chat-client-id"
    path.parent.mkdir(parents=True)
    legacy_id = "8ee9ca69-84cf-49f1-b8c3-cab8a0c80a2e"
    path.write_text(f"{legacy_id}\n", encoding="utf-8")

    assert chat.persistent_client_id() == legacy_id
    assert (chat.config_dir() / "client-id").read_text(encoding="utf-8").strip() == legacy_id


def test_chat_client_persistent_client_id_creates_new(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    generated = chat.persistent_client_id()
    assert generated
    assert (chat.config_dir() / "client-id").read_text(encoding="utf-8").strip() == generated


def test_chat_client_persistent_client_id_ignores_write_error(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setattr(
        __import__("bunnyland.tui.backend", fromlist=["Path"]).Path,
        "write_text",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError()),
    )

    assert chat.persistent_client_id()


def test_chat_client_load_history_handles_missing_or_invalid(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert chat.load_history("client", "character") == {"summary": "", "messages": []}
    path = chat.history_path("client", "character")
    path.parent.mkdir(parents=True)
    path.write_text("{not json", encoding="utf-8")
    assert chat.load_history("client", "character") == {"summary": "", "messages": []}
    path.write_text("[]", encoding="utf-8")
    assert chat.load_history("client", "character") == {"summary": "", "messages": []}


def test_chat_client_api_helpers_and_character_selection(monkeypatch):
    calls = []

    def fake_urlopen(request, timeout):
        calls.append((request, timeout))
        return FakeResponse(
            {
                "characters": [
                    {"id": "char-1", "name": "Juniper"},
                    {"id": "char-2", "name": "Hazel"},
                ]
            }
        )

    monkeypatch.setattr(chat.urllib.request, "urlopen", fake_urlopen)

    assert chat.api_url(" http://server/ ", "/play/characters") == "http://server/play/characters"
    assert chat.get_json("http://server", "/play/characters")["characters"][0]["name"] == (
        "Juniper"
    )
    assert chat.choose_character("http://server", "") == ("char-1", "Juniper")
    assert chat.choose_character("http://server", "Hazel") == ("char-2", "Hazel")
    assert chat.choose_character("http://server", "char-2") == ("char-2", "Hazel")
    with pytest.raises(RuntimeError, match="no such character"):
        chat.choose_character("http://server", "Nobody")


def test_chat_client_choose_character_rejects_empty_list(monkeypatch):
    monkeypatch.setattr(chat, "get_json", lambda _base, _path, _client="": {"characters": []})

    with pytest.raises(RuntimeError, match="no characters"):
        chat.choose_character("http://server", "")


def test_chat_client_post_json_success_and_error(monkeypatch):
    requests = []

    def ok_urlopen(request, timeout):
        requests.append((request, timeout))
        return FakeResponse({"reply": "hello"})

    monkeypatch.setattr(chat.urllib.request, "urlopen", ok_urlopen)

    assert chat.post_json("http://server", "/chat", {"message": "hi"}) == {"reply": "hello"}
    assert requests[0][0].headers["Content-type"] == "application/json"

    def error_urlopen(_request, timeout):
        del timeout
        raise urllib.error.HTTPError(
            "http://server/chat",
            409,
            "Conflict",
            {},
            FakeResponse({"detail": "disabled"}),
        )

    monkeypatch.setattr(chat.urllib.request, "urlopen", error_urlopen)
    with pytest.raises(RuntimeError, match="disabled"):
        chat.post_json("http://server", "/chat", {"message": "hi"})


def test_chat_client_waits_for_async_job(monkeypatch):
    responses = iter(
        [
            {"id": "job-1", "status": "running"},
            {"id": "job-1", "status": "succeeded", "result": {"reply": "hello"}},
        ]
    )
    paths = []
    monkeypatch.setattr(chat.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(
        chat,
        "get_json",
        lambda _base, path, _client_id: paths.append(path) or next(responses),
    )

    result = chat.wait_for_job(
        "http://server/v1",
        "character:1",
        "client-1",
        {"id": "job-1", "status": "queued"},
    )

    assert result["result"]["reply"] == "hello"
    assert paths == [
        "/chat/characters/character%3A1/jobs/job-1",
        "/chat/characters/character%3A1/jobs/job-1",
    ]


class FakeChatBackend:
    def __init__(self, *args, available=True, jobs=None, access=None, **kwargs):
        self.args = args
        self.kwargs = kwargs
        self.client_id = "client-1"
        self.available = available
        self.access = access or CharacterChatAccess(writable=True)
        self.jobs = list(jobs or [])
        self.submitted = []
        self.assignments = []
        self.started = False
        self.closed = False

    async def start(self):
        self.started = True

    async def close(self):
        self.closed = True

    async def character_chat_availability(self):
        return (self.available, "Character chat is not enabled on this server")

    async def fetch_character_list(self):
        return [CharacterSummaryView(character_id="char:1", name="Juniper")]

    async def character_chat_access(self, _character_id):
        return self.access

    async def assign_character_chat_controller(self, character_id, controller_id):
        self.assignments.append((character_id, controller_id))
        self.access = CharacterChatAccess(writable=True)
        return self.access

    async def submit_character_chat(self, character_id, message, **kwargs):
        self.submitted.append((character_id, message, kwargs))
        item = self.jobs.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    async def poll_character_chat(self, job):
        del job
        item = self.jobs.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def test_chat_client_main_disabled_server_exits(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    backend = FakeChatBackend(available=False)
    monkeypatch.setattr(chat, "RemoteBackend", lambda *_args, **_kwargs: backend)

    with pytest.raises(SystemExit, match="not enabled"):
        chat.main(["--server", "https://server", "--cli"])
    assert backend.closed is True


def test_chat_client_main_interactive_round_trip(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    inputs = iter(["", "hello", "/quit"])
    backend = FakeChatBackend(
        jobs=[
            CharacterChatJob(
                id="job-1",
                status="succeeded",
                character_id="char:1",
                reply="I am here.",
                action=CharacterChatActionResult(tool="look", status="executed"),
            )
        ]
    )
    monkeypatch.setattr(chat, "RemoteBackend", lambda *_args, **_kwargs: backend)

    with patch("builtins.input", lambda _prompt: next(inputs)):
        assert chat.main(["--server", "https://server", "--character", "Juniper", "--cli"]) == 0

    out = capsys.readouterr().out
    assert "Chatting with Juniper" in out
    assert "Juniper: I am here. [look executed]" in out
    assert backend.submitted[0][0:2] == ("char:1", "hello")
    assert backend.closed is True


def test_chat_client_main_reports_failed_job(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    backend = FakeChatBackend(
        jobs=[
            CharacterChatJob(
                id="job-1",
                status="failed",
                character_id="char:1",
                failure="Juniper is unavailable.",
            )
        ]
    )
    monkeypatch.setattr(chat, "RemoteBackend", lambda *_args, **_kwargs: backend)

    with patch("builtins.input", side_effect=["hello", "/quit"]):
        assert chat.main(["--server", "https://server", "--cli"]) == 0

    assert "Juniper: Juniper is unavailable." in capsys.readouterr().out


def test_chat_client_main_exits_on_eof(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    backend = FakeChatBackend()
    monkeypatch.setattr(chat, "RemoteBackend", lambda *_args, **_kwargs: backend)
    with patch("builtins.input", side_effect=EOFError):
        assert chat.main(["--server", "https://server", "--cli"]) == 0

    assert "Chatting with Juniper" in capsys.readouterr().out


def test_local_cli_requires_flags_or_saved_configuration(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    with pytest.raises(SystemExit, match="needs saved terminal configuration"):
        chat.main(["--cli", "--generator", "empty"])
    with pytest.raises(SystemExit, match="disabled"):
        chat.main(["--cli", "--generator", "empty", "--no-chat"])


def test_cloud_cli_reports_missing_environment_credentials(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.delenv("OLLAMA_CLOUD_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(SystemExit, match="OLLAMA_CLOUD_API_KEY"):
        chat.main(["--cli", "--chat-provider", "ollama-cloud"])
    with pytest.raises(SystemExit, match="OPENROUTER_API_KEY"):
        chat.main(["--cli", "--chat-provider", "openrouter"])


def test_textual_local_chat_forwards_generator_and_provider_flags(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    created = {}

    class LocalStub:
        def __init__(self, **kwargs):
            created["backend"] = kwargs

    class AppStub:
        def __init__(self, backend, **kwargs):
            created["app"] = (backend, kwargs)

        def run(self):
            created["ran"] = True

    monkeypatch.setattr(chat, "LocalBackend", LocalStub)
    monkeypatch.setattr(chat, "CharacterChatApp", AppStub)

    assert (
        chat.main(
            [
                "--generator",
                "empty",
                "--seed",
                "quiet hill",
                "--character",
                "Juniper",
                "--chat-provider",
                "ollama-local",
                "--chat-model",
                "llama3.2",
                "--ollama-host",
                "http://localhost:11435",
                "--openrouter-server-url",
                "https://router.example/v1",
            ]
        )
        == 0
    )
    assert created["backend"]["generator"] == "empty"
    assert created["backend"]["seed"] == "quiet hill"
    settings = created["backend"]["chat_config"]
    assert settings.model == "llama3.2"
    assert settings.ollama_host == "http://localhost:11435"
    assert settings.openrouter_server_url == "https://router.example/v1"
    assert created["app"][1] == {
        "character": "Juniper",
        "show_generator_selector": False,
        "needs_chat_setup": False,
    }
    assert created["ran"] is True


def test_textual_remote_chat_forwards_auth_and_skips_local_setup(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    (tmp_path / "bunnyland").mkdir()
    (tmp_path / "bunnyland" / "terminal.yml").write_text("not: [valid", encoding="utf-8")
    created = {}

    class RemoteStub:
        def __init__(self, server, **kwargs):
            created["backend"] = (server, kwargs)

    class AppStub:
        def __init__(self, backend, **kwargs):
            created["app"] = kwargs

        def run(self):
            return None

    monkeypatch.setattr(chat, "RemoteBackend", RemoteStub)
    monkeypatch.setattr(chat, "CharacterChatApp", AppStub)
    monkeypatch.setattr(chat.sys, "stdin", __import__("io").StringIO("secret\n"))

    assert (
        chat.main(
            [
                "--server",
                "https://play.example/v1",
                "--username",
                "player",
                "--password-stdin",
                "--token-file",
                "/tmp/token",
            ]
        )
        == 0
    )
    assert created["backend"] == (
        "https://play.example/v1",
        {
            "fallback_controller": None,
            "timeout_seconds": None,
            "username": "player",
            "password": "secret",
            "token_file": "/tmp/token",
        },
    )
    assert created["app"]["needs_chat_setup"] is False


def test_chat_lists_local_generators(monkeypatch, capsys):
    monkeypatch.setattr(chat, "available_generators", lambda: {"empty": object()})
    monkeypatch.setattr(chat, "format_generator_lines", lambda _items: ["empty - Empty"])
    assert chat.main(["--list-generators"]) == 0
    assert capsys.readouterr().out == "empty - Empty\n"


async def test_line_chat_rejects_empty_and_unknown_character():
    class Empty(FakeChatBackend):
        async def fetch_character_list(self):
            return []

    with pytest.raises(SystemExit, match="no characters"):
        await chat._run_cli(Empty(), "")
    with pytest.raises(SystemExit, match="no such character"):
        await chat._run_cli(FakeChatBackend(), "Nobody")


async def test_line_chat_polls_pending_reply_and_recovers_from_provider_error(capsys):
    backend = FakeChatBackend(
        jobs=[
            CharacterChatJob(
                id="job-1",
                status="running",
                character_id="char:1",
                reply="One moment.",
                action=CharacterChatActionResult(tool="look", status="queued"),
            ),
            CharacterChatJob(
                id="job-1",
                status="succeeded",
                character_id="char:1",
                reply="I see a lamp.",
            ),
            RuntimeError("provider offline"),
        ]
    )
    inputs = iter(["first", "second", "/exit"])
    with patch("builtins.input", lambda _prompt: next(inputs)):
        assert await chat._run_cli(backend, "char:1") == 0
    output = capsys.readouterr().out
    assert "One moment. [pending look]" in output
    assert "I see a lamp." in output
    assert "Chat failed: provider offline" in output


async def test_line_chat_polls_pending_job_without_intermediate_reply(capsys):
    backend = FakeChatBackend(
        jobs=[
            CharacterChatJob(id="job-1", status="running", character_id="char:1"),
            CharacterChatJob(id="job-1", status="succeeded", character_id="char:1", reply="Done."),
        ]
    )
    with patch("builtins.input", side_effect=["hello", "/quit"]):
        assert await chat._run_cli(backend, "") == 0
    assert "Done." in capsys.readouterr().out


async def test_line_chat_keeps_history_readable_and_assigns_before_sending(
    tmp_path,
    monkeypatch,
    capsys,
):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    chat.save_history(
        "client-1",
        "char:1",
        {
            "summary": "",
            "messages": [
                {"role": "user", "text": "Are you there?"},
                {"role": "character", "text": "I was."},
            ],
        },
    )
    backend = FakeChatBackend(
        access=CharacterChatAccess(
            writable=False,
            reason="Juniper has suspended; existing chat history is read-only.",
            controllers=(CharacterChatController("controller:llm", "default (ollama/qwen)"),),
        ),
        jobs=[
            CharacterChatJob(
                id="job-1",
                status="succeeded",
                character_id="char:1",
                reply="I am back.",
            )
        ],
    )
    inputs = iter(
        [
            "blocked message",
            "/meta",
            "/controllers",
            "/controller controller:missing",
            "/controller controller:llm",
            "hello again",
            "/quit",
        ]
    )

    with patch("builtins.input", lambda _prompt: next(inputs)):
        assert await chat._run_cli(backend, "Juniper") == 0

    output = capsys.readouterr().out
    assert "You: Are you there?" in output
    assert "Juniper: I was." in output
    assert "existing chat history is read-only" in output
    assert "Meta: /controller <id>, /controllers, /help, /quit" in output
    assert "controller:llm · default (ollama/qwen)" in output
    assert "That LLM controller is not assignable" in output
    assert "Juniper is now assigned to an LLM controller" in output
    assert backend.assignments == [("char:1", "controller:llm")]
    assert [item[1] for item in backend.submitted] == ["hello again"]


async def test_line_chat_read_only_without_assignable_controllers(capsys):
    backend = FakeChatBackend(
        access=CharacterChatAccess(
            writable=False,
            reason="Juniper has no controller; existing chat history is read-only.",
        )
    )
    with patch(
        "builtins.input",
        side_effect=["/controllers", "/controller", "must not send", "/quit"],
    ):
        assert await chat._run_cli(backend, "Juniper") == 0

    output = capsys.readouterr().out
    assert output.count("No assignable LLM controllers") == 1
    assert "Usage: /controller <id>" in output
    assert "existing chat history is read-only" in output
    assert "Use /controllers to list assignable" not in output
    assert backend.submitted == []


async def test_line_chat_reports_assignment_failure_and_still_read_only(capsys):
    choice = CharacterChatController("controller:llm", "default")

    class AssignmentBackend(FakeChatBackend):
        def __init__(self):
            super().__init__(
                access=CharacterChatAccess(
                    writable=False,
                    reason="read-only",
                    controllers=(choice,),
                )
            )
            self.attempts = 0

        async def assign_character_chat_controller(self, character_id, controller_id):
            self.assignments.append((character_id, controller_id))
            self.attempts += 1
            if self.attempts == 1:
                raise RuntimeError("assignment offline")
            return CharacterChatAccess(
                writable=False,
                reason="controller changed before assignment completed",
                controllers=(choice,),
            )

    backend = AssignmentBackend()
    with patch(
        "builtins.input",
        side_effect=[
            "/controller controller:llm",
            "/controller controller:llm",
            "/quit",
        ],
    ):
        assert await chat._run_cli(backend, "Juniper") == 0

    output = capsys.readouterr().out
    assert "Controller assignment failed: assignment offline" in output
    assert "controller changed before assignment completed" in output
    assert backend.assignments == [
        ("char:1", "controller:llm"),
        ("char:1", "controller:llm"),
    ]


async def test_textual_chat_is_read_only_until_controller_assignment(tmp_path, monkeypatch):
    from textual.app import App
    from textual.widgets import Button, Input, Static

    from bunnyland.tui.screens import ConversationScreen

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    chat.save_history(
        "client-1",
        "char:1",
        {"summary": "", "messages": [{"role": "character", "text": "Earlier."}]},
    )
    backend = FakeChatBackend(
        access=CharacterChatAccess(
            writable=False,
            reason="Juniper has web; existing chat history is read-only.",
            controllers=(CharacterChatController("controller:llm", "default"),),
        )
    )

    screen = ConversationScreen(backend, "char:1", "Juniper")

    class ChatHarness(App[None]):
        def on_mount(self) -> None:
            self.push_screen(screen)

    app = ChatHarness()
    async with app.run_test() as pilot:
        for _ in range(20):
            if screen.query("#conversation-input"):
                await pilot.pause(0.05)
                break
            await pilot.pause(0.05)
        input_widget = screen.query_one("#conversation-input", Input)
        assign = screen.query_one("#conversation-controller-assign", Button)
        status = screen.query_one("#conversation-status", Static)
        transcript = screen.query_one("#conversation-transcript", Static)
        assert input_widget.disabled is True
        assert assign.disabled is False
        assert "read-only" in str(status.render())
        assert "Earlier." in str(transcript.render())

        await pilot.click("#conversation-controller-assign")
        await pilot.pause()
        assert backend.assignments == [("char:1", "controller:llm")]
        assert input_widget.disabled is False
        assert screen.query_one("#conversation-controller-row").display is False


async def test_remote_chat_access_uses_profile_admin_snapshot_and_assignment_contracts():
    class Response:
        def __init__(self, payload):
            self.payload = payload

        def raise_for_status(self): ...

        def json(self):
            return self.payload

    class Client:
        def __init__(self):
            self.assigned = False
            self.puts = []
            self.gets = []

        async def get(self, url):
            self.gets.append(url)
            if url.endswith("/public/features"):
                return Response({"character_chat": True})
            if "/profile/characters/" in url:
                return Response(
                    {
                        "world_id": "world:1",
                        "world_epoch": 7,
                        "character_id": "character:1",
                        "character_name": "Juniper",
                        "controller": {
                            "controller_id": "controller:llm"
                            if self.assigned
                            else "controller:web",
                            "generation": 3,
                            "kind": "llm" if self.assigned else "web",
                        },
                    }
                )
            if url.endswith("/admin/world/snapshot"):
                return Response(
                    {
                        "entities": [
                            {
                                "id": "controller:llm",
                                "components": {
                                    "LLMControllerComponent": {
                                        "profile_name": "default",
                                        "provider": "ollama",
                                        "model": "qwen",
                                    }
                                },
                            },
                            {
                                "id": "controller:web",
                                "components": {"WebControllerComponent": {}},
                            },
                            {
                                "id": "controller:invalid",
                                "components": {"LLMControllerComponent": "invalid"},
                            },
                            {
                                "id": "controller:unnamed",
                                "components": {
                                    "LLMControllerComponent": {
                                        "profile_name": 7,
                                        "provider": "",
                                        "model": "",
                                    }
                                },
                            },
                        ]
                    }
                )
            raise AssertionError(url)

        async def put(self, url, *, json):
            self.puts.append((url, json))
            self.assigned = True
            return Response({"world_epoch": 8})

    backend = RemoteBackend("https://server.example/v1", client_id="client-1")
    backend._client = Client()
    backend._auth_scopes = frozenset({"world:admin"})

    access = await backend.character_chat_access("character:1")
    assert access == CharacterChatAccess(
        writable=False,
        reason="Juniper has web; existing chat history is read-only.",
        controllers=(
            CharacterChatController("controller:unnamed", "controller:unnamed"),
            CharacterChatController("controller:llm", "default (ollama/qwen)"),
        ),
    )

    refreshed = await backend.assign_character_chat_controller("character:1", "controller:llm")
    assert refreshed == CharacterChatAccess(writable=True)
    assert backend._client.puts == [
        (
            "https://server.example/v1/admin/characters/character%3A1/controller",
            {"controller_id": "controller:llm"},
        )
    ]


async def test_remote_chat_assignment_requires_admin_scope_without_snapshot_request():
    backend = RemoteBackend("https://server.example/v1", client_id="client-1")
    assert await backend.assignable_character_chat_controllers() == ()
    with pytest.raises(PermissionError, match="Administrator scope"):
        await backend.assign_character_chat_controller("character:1", "controller:llm")


async def test_remote_auth_rejects_missing_login_and_rotation_tokens():
    class Response:
        status_code = 200

        def __init__(self, *, rotate_after=None):
            self.rotate_after = rotate_after

        def raise_for_status(self): ...

        def json(self):
            return {
                "token": None,
                "subject": "player",
                "scopes": ["world:admin"],
                "expires_at": 999,
                "rotate_after": self.rotate_after,
                "rotation_eligible": True,
            }

    class Client:
        async def post(self, _url, **_kwargs):
            return Response()

        async def patch(self, _url):
            return Response()

    backend = RemoteBackend("https://server.example/v1", client_id="client-1")
    backend._client = Client()
    backend.username = "player"
    backend._password = "secret"
    with pytest.raises(RuntimeError, match="login did not return"):
        await backend._login()
    assert backend._password == ""
    with pytest.raises(RuntimeError, match="rotation did not return"):
        await backend._rotate_token()


def test_chat_main_reports_malformed_local_config(monkeypatch):
    monkeypatch.setattr(
        chat,
        "load_terminal_config",
        lambda: (_ for _ in ()).throw(chat.TerminalConfigError("bad terminal config")),
    )
    with pytest.raises(SystemExit, match="bad terminal config"):
        chat.main(["--generator", "empty"])


def test_chat_main_prompts_for_remote_password(monkeypatch):
    created = {}

    class RemoteStub:
        def __init__(self, server, **kwargs):
            created.update(server=server, **kwargs)

    class AppStub:
        def __init__(self, *_args, **_kwargs): ...
        def run(self): ...

    monkeypatch.setattr(chat, "RemoteBackend", RemoteStub)
    monkeypatch.setattr(chat, "CharacterChatApp", AppStub)
    monkeypatch.setattr("getpass.getpass", lambda _prompt: "prompted-secret")
    assert chat.main(["--server", "https://play.example/v1", "--username", "player"]) == 0
    assert created["password"] == "prompted-secret"
