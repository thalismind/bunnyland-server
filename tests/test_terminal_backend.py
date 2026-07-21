from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from bunnyland.server.models import CharacterChatActionResult
from bunnyland.server.v1_models import ImageJobResult, JobResource
from bunnyland.terminal_config import resolve_terminal_chat_config
from bunnyland.tui.backend import (
    Backend,
    CharacterChatJob,
    LocalBackend,
    RemoteBackend,
    persistent_client_id,
)


class Response:
    is_success = True
    status_code = 200

    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload

    def raise_for_status(self):
        if not self.is_success:
            raise RuntimeError(f"HTTP {self.status_code}")


def profile_payload():
    return {
        "world_id": "world-1",
        "world_epoch": 42,
        "character_id": "character:1",
        "character_name": "Pib",
        "sheet": {
            "species": "rabbit",
            "biography": "A curious resident.",
            "status": ["awake"],
            "skills": [{"label": "Cooking", "value": "3"}],
        },
    }


async def test_local_backend_builds_typed_character_profile():
    backend = LocalBackend(generator="apartment-demo", autorun=False, client_id="local-client")
    await backend.start()
    try:
        content_flags = await backend.fetch_content_flags()
        assert content_flags == tuple(sorted(content_flags))
        assert "pvp" in content_flags
        character = (await backend.fetch_character_list())[0]
        profile = await backend.fetch_character_profile(character.character_id)
        assert profile.character_id == character.character_id
        assert profile.character_name == character.name
        assert profile.world_id == backend.meta.world_id
        assert profile.sheet.kind == "character"
        assert profile.room.entities == []
    finally:
        await backend.close()


async def test_remote_backend_validates_character_profile():
    class Client:
        async def get(self, url):
            assert url.endswith("/profile/characters/character%3A1")
            return Response(profile_payload())

    backend = RemoteBackend("https://server.example")
    backend._client = Client()
    profile = await backend.fetch_character_profile("character:1")
    assert profile.sheet.species == "rabbit"
    assert profile.sheet.skills[0].label == "Cooking"


async def test_remote_backend_validates_public_content_flags():
    class Client:
        async def get(self, url):
            assert url.endswith("/public/world")
            return Response(
                {
                    "world_id": "world-1",
                    "world_epoch": 42,
                    "title": "Clover City",
                    "description": "Mind the foxes after dark.",
                    "content_flags": ["adult:violence", "pvp"],
                }
            )

    backend = RemoteBackend("https://server.example")
    backend._client = Client()

    assert await backend.fetch_content_flags() == ("adult:violence", "pvp")


async def test_remote_backend_rejects_invalid_character_profile():
    class Client:
        async def get(self, _url):
            return Response({"world_id": "world-1", "world_epoch": "invalid"})

    backend = RemoteBackend("https://server.example")
    backend._client = Client()
    with pytest.raises(ValidationError):
        await backend.fetch_character_profile("character:1")


async def test_local_backend_direct_chat_and_pending_result():
    calls = []

    class Service:
        async def chat(self, character_id, request):
            calls.append((character_id, request))
            return SimpleNamespace(
                reply="I will look.",
                action=CharacterChatActionResult(
                    tool="look", command_id="command-1", status="queued"
                ),
            )

        async def pending_result(self, character_id, client_id, command_id):
            calls.append((character_id, client_id, command_id))
            return SimpleNamespace(
                complete=True,
                reply="I found a lantern.",
                action=CharacterChatActionResult(
                    tool="look", command_id="command-1", status="executed"
                ),
            )

    backend = LocalBackend(
        client_id="local-client",
        chat_config=resolve_terminal_chat_config(None, environ={}),
    )
    backend.character_chat = Service()
    job = await backend.submit_character_chat(
        "character:1",
        "What do you see?",
        history=[{"role": "user", "text": "Hello"}],
    )
    assert job.pending
    assert calls[0][1].client_id == "local-client"
    assert len(calls[0][1].history) == 1
    completed = await backend.poll_character_chat(job)
    assert completed.status == "succeeded"
    assert completed.reply == "I found a lantern."
    assert completed.action.status == "executed"


async def test_local_backend_surfaces_chat_service_errors():
    class Service:
        async def chat(self, _character_id, _request):
            raise PermissionError("character chat requires the current controller to be llm")

    backend = LocalBackend(
        client_id="local-client",
        chat_config=resolve_terminal_chat_config(None, environ={}),
    )
    backend.character_chat = Service()
    with pytest.raises(PermissionError, match="current controller"):
        await backend.submit_character_chat("character:1", "Hello")


def job_payload(*, status="queued", result=None, failure=None):
    now = datetime.now(UTC).isoformat()
    if result is not None:
        result = {
            "world_epoch": 42,
            "character_id": "character:1",
            **result,
        }
    return {
        "world_id": "world-1",
        "world_epoch": 42,
        "id": "job-1",
        "kind": "chat",
        "status": status,
        "created_at": now,
        "updated_at": now,
        "result": result,
        "failure": failure,
    }


async def test_remote_backend_submits_and_polls_chat_job():
    requests = []

    class Client:
        async def post(self, url, **kwargs):
            requests.append(("post", url, kwargs))
            return Response(job_payload())

        async def get(self, url):
            requests.append(("get", url, {}))
            return Response(
                job_payload(
                    status="succeeded",
                    result={
                        "reply": "Hello.",
                        "action": {"tool": "say", "status": "executed"},
                    },
                )
            )

    backend = RemoteBackend("https://server.example", client_id="remote-client")
    backend._client = Client()
    history = [{"role": "user", "text": str(index)} for index in range(30)]
    job = await backend.submit_character_chat("character:1", "Hello", history=history)
    assert job.pending
    assert len(requests[0][2]["json"]["history"]) == 24
    completed = await backend.poll_character_chat(job)
    assert completed.complete
    assert completed.reply == "Hello."
    assert completed.action.tool == "say"
    assert requests[1][1].endswith("/chat/characters/character%3A1/jobs/job-1")


async def test_remote_backend_preserves_pending_reply_and_failure():
    pending_resource = RemoteBackend._character_chat_job(
        JobResource.model_validate(
            job_payload(
                status="running",
                result={
                    "reply": "I will try that when I can.",
                    "action": {"tool": "look", "status": "queued", "command_id": "cmd"},
                },
            )
        ),
        "character:1",
    )
    assert pending_resource.pending
    assert pending_resource.reply == "I will try that when I can."

    failed = RemoteBackend._character_chat_job(
        JobResource.model_validate(
            job_payload(
                status="failed",
                failure={
                    "title": "Chat failed",
                    "status": 409,
                    "detail": "provider unavailable",
                    "code": "chat_unavailable",
                },
            )
        ),
        "character:1",
    )
    assert failed.failure == "provider unavailable"


def test_remote_backend_rejects_non_chat_job_results() -> None:
    resource = JobResource(
        world_id="world-1",
        world_epoch=42,
        id="job-image",
        kind="image",
        status="succeeded",
        result=ImageJobResult(
            world_epoch=42,
            job_id="image-1",
            status="succeeded",
            entity_id="character:1",
            purpose="portrait",
        ),
    )

    with pytest.raises(ValueError, match="non-chat result"):
        RemoteBackend._character_chat_job(resource, "character:1")


async def test_character_chat_cancellation_is_safe():
    backend = RemoteBackend("https://server.example")
    await backend.cancel_character_chat(
        CharacterChatJob(id="job", status="running", character_id="character:1")
    )


async def test_remote_chat_availability_reports_disabled_server():
    class Client:
        async def get(self, url):
            assert url.endswith("/public/features")
            return Response({"character_chat": False})

    backend = RemoteBackend("https://server.example")
    backend._client = Client()
    assert await backend.character_chat_availability() == (
        False,
        "Character chat is not enabled on this server",
    )


async def test_backend_default_character_operations_are_typed_failures():
    class Stub(Backend):
        supports_character_chat = True

        async def start(self): ...
        async def close(self): ...
        async def fetch_snapshot(self):
            return {}

        async def submit(self, _command):
            raise NotImplementedError

        async def claim(self, _player_id, _world):
            return None

    backend = Stub()
    assert await backend.character_chat_availability() == (True, "")
    with pytest.raises(RuntimeError, match="Character sheets"):
        await backend.fetch_character_profile("character:1")
    with pytest.raises(RuntimeError, match="Character chat"):
        await backend.submit_character_chat("character:1", "hello")
    job = CharacterChatJob(id="job", status="succeeded", character_id="character:1")
    assert await backend.poll_character_chat(job) is job
    await backend.cancel_character_chat(job)

    backend.supports_character_chat = False
    assert await backend.character_chat_availability() == (
        False,
        "Character chat is not available for this session",
    )


def test_persistent_client_id_ignores_invalid_legacy_id(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    legacy = tmp_path / "bunnyland" / "chat-client-id"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("not-a-uuid", encoding="utf-8")
    assert persistent_client_id() != "not-a-uuid"


async def test_local_backend_constructs_configured_chat_service(monkeypatch):
    import bunnyland.server.character_chat as character_chat
    import bunnyland.tui.backend as backend_module

    captured = {}

    class Service:
        def __init__(self, actor, builder, agent):
            captured.update(actor=actor, builder=builder, agent=agent)

    monkeypatch.setattr(character_chat, "CharacterChatService", Service)
    monkeypatch.setattr(backend_module, "build_terminal_chat_agent", lambda _settings: "agent")
    backend = LocalBackend(
        generator="apartment-demo",
        autorun=False,
        chat_config=resolve_terminal_chat_config(None, environ={}),
    )
    await backend.start()
    try:
        assert captured["actor"] is backend.actor
        assert captured["agent"] == "agent"
        assert backend.character_chat.__class__ is Service
    finally:
        await backend.close()


async def test_local_chat_disabled_and_terminal_job_shortcuts():
    disabled = LocalBackend(chat_config=None)
    with pytest.raises(RuntimeError, match="disabled"):
        await disabled.submit_character_chat("character:1", "hello")

    complete = CharacterChatJob(id="done", status="succeeded", character_id="character:1")
    assert await disabled.poll_character_chat(complete) is complete
    pending = CharacterChatJob(
        id="pending",
        status="running",
        character_id="character:1",
        action=CharacterChatActionResult(command_id="command-1", status="queued"),
    )
    failed = await disabled.poll_character_chat(pending)
    assert failed.status == "failed"
    assert "disabled" in failed.failure


async def test_local_chat_immediate_reply_gets_completed_job():
    class Service:
        async def chat(self, _character_id, _request):
            return SimpleNamespace(
                reply="Hello.", action=CharacterChatActionResult(status="none")
            )

    backend = LocalBackend(
        chat_config=resolve_terminal_chat_config(None, environ={}), client_id="local-client"
    )
    backend.character_chat = Service()
    job = await backend.submit_character_chat("character:1", "hello")
    assert job.status == "succeeded"
    assert job.id


async def test_remote_chat_available_and_completed_poll_shortcut():
    class Client:
        async def get(self, url):
            assert url.endswith("/public/features")
            return Response({"character_chat": True})

    backend = RemoteBackend("https://server.example")
    backend._client = Client()
    assert await backend.character_chat_availability() == (True, "")
    complete = CharacterChatJob(id="done", status="succeeded", character_id="character:1")
    assert await backend.poll_character_chat(complete) is complete
