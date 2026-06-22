from __future__ import annotations

import json
import urllib.error
from unittest.mock import patch

import pytest

from bunnyland import chat


class FakeResponse:
    def __init__(self, payload: dict):
        self.payload = payload

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
    assert payload["client_id"] == "client-1"
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
    path.write_text("client-1\n", encoding="utf-8")

    assert chat.persistent_client_id() == "client-1"


def test_chat_client_persistent_client_id_creates_new(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setattr(chat, "uuid4", lambda: "generated-client")

    assert chat.persistent_client_id() == "generated-client"
    assert (chat.config_dir() / "chat-client-id").read_text(encoding="utf-8").strip() == (
        "generated-client"
    )


def test_chat_client_persistent_client_id_ignores_write_error(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setattr(chat, "uuid4", lambda: "generated-client")
    monkeypatch.setattr(
        chat.Path,
        "write_text",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError()),
    )

    assert chat.persistent_client_id() == "generated-client"


def test_chat_client_load_history_handles_missing_or_invalid(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert chat.load_history("client", "character") == {"summary": "", "messages": []}
    path = chat.history_path("client", "character")
    path.parent.mkdir(parents=True)
    path.write_text("{not json", encoding="utf-8")
    assert chat.load_history("client", "character") == {"summary": "", "messages": []}


def test_chat_client_api_helpers_and_character_selection(monkeypatch):
    calls = []

    def fake_urlopen(request, timeout):
        calls.append((request, timeout))
        return FakeResponse(
            {
                "characters": [
                    {"character_id": "char-1", "name": "Juniper"},
                    {"character_id": "char-2", "name": "Hazel"},
                ]
            }
        )

    monkeypatch.setattr(chat.urllib.request, "urlopen", fake_urlopen)

    assert chat.api_url(" http://server/ ", "/world") == "http://server/world"
    assert chat.get_json("http://server", "/world/characters")["characters"][0]["name"] == (
        "Juniper"
    )
    assert chat.choose_character("http://server", "") == ("char-1", "Juniper")
    assert chat.choose_character("http://server", "Hazel") == ("char-2", "Hazel")
    assert chat.choose_character("http://server", "char-2") == ("char-2", "Hazel")
    with pytest.raises(RuntimeError, match="no such character"):
        chat.choose_character("http://server", "Nobody")


def test_chat_client_choose_character_rejects_empty_list(monkeypatch):
    monkeypatch.setattr(chat, "get_json", lambda _base, _path: {"characters": []})

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


def test_chat_client_main_disabled_server_exits(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setattr(chat, "get_json", lambda _base, _path: {"enabled": False})

    with pytest.raises(SystemExit, match="not enabled"):
        chat.main(["--server", "http://server"])


def test_chat_client_main_interactive_round_trip(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    inputs = iter(["", "hello", "/quit"])
    posted = []

    def fake_get_json(_base, path):
        if path == "/world/chat/status":
            return {"enabled": True}
        return {"characters": [{"character_id": "char:1", "name": "Juniper"}]}

    def fake_post_json(base, path, payload):
        posted.append((base, path, payload))
        return {"reply": "I am here.", "action": {"tool": "look", "status": "executed"}}

    monkeypatch.setattr(chat, "get_json", fake_get_json)
    monkeypatch.setattr(chat, "post_json", fake_post_json)

    with patch("builtins.input", lambda _prompt: next(inputs)):
        assert chat.main(["--server", "http://server", "--character", "Juniper"]) == 0

    out = capsys.readouterr().out
    assert "Chatting with Juniper" in out
    assert "Juniper: I am here. [look executed]" in out
    assert posted[0][1] == "/world/character/char%3A1/chat"


def test_chat_client_main_exits_on_eof(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    def fake_get_json(_base, path):
        if path == "/world/chat/status":
            return {"enabled": True}
        return {"characters": [{"character_id": "char:1", "name": "Juniper"}]}

    monkeypatch.setattr(chat, "get_json", fake_get_json)

    with patch("builtins.input", side_effect=EOFError):
        assert chat.main(["--server", "http://server"]) == 0

    assert "Chatting with Juniper" in capsys.readouterr().out
