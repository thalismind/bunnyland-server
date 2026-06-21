"""Tests for the ComfyUI client (HTTP polling, websocket, fallback) and config."""

from __future__ import annotations

import json
import sys
import types

import pytest

from bunnyland.imagegen.client import (
    ComfyError,
    ComfyTimeoutError,
    HttpComfyClient,
    WebSocketComfyClient,
    _is_completion,
    _ws_url,
    build_comfy_client,
)
from bunnyland.imagegen.config import ImageGenConfig


def _config(**kw) -> ImageGenConfig:
    base = {
        "server_url": "http://comfy.local:8188",
        "poll_interval_seconds": 1.0,
        "timeout_seconds": 5.0,
    }
    base.update(kw)
    return ImageGenConfig(**base)


# --- config -------------------------------------------------------------------------


def test_config_from_env_disabled_without_server():
    assert ImageGenConfig.from_env({}) is None


def test_config_from_env_reads_all_fields():
    config = ImageGenConfig.from_env(
        {
            "COMFYUI_SERVER_URL": "http://host:8188/",
            "COMFYUI_USE_WEBSOCKET": "no",
            "COMFYUI_POLL_INTERVAL_SECONDS": "2.5",
            "COMFYUI_TIMEOUT_SECONDS": "30",
            "BUNNYLAND_MEDIA_DIR": "/srv/media",
            "BUNNYLAND_PUBLIC_BASE_URL": "https://play.example/",
            "BUNNYLAND_IMAGE_TEMPLATES": "/srv/templates.json",
            "BUNNYLAND_IMAGE_WORKFLOWS": "anima-my-server",
            "BUNNYLAND_IMAGE_PROMPT_STYLE": "tag",
            "BUNNYLAND_IMAGE_ENHANCER": "llm",
            "BUNNYLAND_IMAGE_MODEL": "flux",
            "OLLAMA_HOST": "https://ollama.com",
            "OLLAMA_CLOUD_API_KEY": "secret",
        }
    )
    assert config is not None
    assert config.server_url == "http://host:8188"  # trailing slash stripped
    assert config.use_websocket is False
    assert config.poll_interval_seconds == 2.5
    assert config.timeout_seconds == 30.0
    assert config.media_root == "/srv/media"
    assert config.public_base_url == "https://play.example"
    assert config.workflows == "anima-my-server"
    assert config.prompt_style == "tag"
    assert config.enhancer == "llm"
    assert config.model == "flux"
    assert config.api_key == "secret"


def test_config_from_env_defaults():
    config = ImageGenConfig.from_env({"COMFYUI_SERVER_URL": "http://host:8188"})
    assert config.use_websocket is True
    assert config.poll_interval_seconds == 1.0
    assert config.media_root == "media"
    assert config.public_base_url == ""
    assert config.workflows == "anima"
    assert config.prompt_style == ""


# --- fakes --------------------------------------------------------------------------


class _Response:
    def __init__(self, payload=None, content=b"", status_error=None):
        self._payload = payload
        self.content = content
        self._status_error = status_error

    def raise_for_status(self):
        if self._status_error is not None:
            raise self._status_error

    def json(self):
        return self._payload


class _FakeHttp:
    """Records requests and replays a scripted sequence of /history responses."""

    def __init__(self, *, history_sequence, image_bytes=b"PNG"):
        self._history_sequence = list(history_sequence)
        self._image_bytes = image_bytes
        self.posts: list[dict] = []
        self.view_params: list[dict] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, path, *, json):  # noqa: A002 - mirror httpx signature
        self.posts.append({"path": path, "json": json})
        return _Response(payload={"prompt_id": "pid-1"})

    async def get(self, path, *, params=None):
        if path.startswith("/history/"):
            return _Response(payload=self._history_sequence.pop(0))
        self.view_params.append(params)
        return _Response(content=self._image_bytes)


def _completed_history(*, with_image=True, node="9"):
    images = [{"filename": "out.png", "subfolder": "", "type": "output"}] if with_image else []
    return {"pid-1": {"outputs": {node: {"images": images}}}}


# --- HTTP client --------------------------------------------------------------------


async def test_http_client_happy_path():
    http = _FakeHttp(history_sequence=[_completed_history()])
    client = HttpComfyClient(_config(), http_factory=lambda: http)
    result = await client.generate({"1": {}}, output_node_id="9")
    assert result == b"PNG"
    assert http.posts[0]["json"]["prompt"] == {"1": {}}
    assert http.view_params[0]["filename"] == "out.png"


async def test_http_client_polls_then_succeeds():
    slept = []
    http = _FakeHttp(history_sequence=[{}, _completed_history()])
    def _record_sleep(seconds):
        slept.append(seconds)
        return _noop()

    client = HttpComfyClient(_config(), http_factory=lambda: http, sleep=_record_sleep)
    result = await client.generate({"1": {}})
    assert result == b"PNG"
    assert slept == [1.0]


async def _noop():
    return None


async def test_http_client_completed_without_image():
    http = _FakeHttp(history_sequence=[_completed_history(with_image=False)])
    client = HttpComfyClient(_config(), http_factory=lambda: http)
    with pytest.raises(ComfyError, match="without an image"):
        await client.generate({"1": {}})


async def test_http_client_times_out():
    http = _FakeHttp(history_sequence=[{}, {}])
    client = HttpComfyClient(
        _config(timeout_seconds=2.0, poll_interval_seconds=1.0),
        http_factory=lambda: http,
        sleep=lambda s: _noop(),
    )
    with pytest.raises(ComfyTimeoutError, match="timed out after 2 polls"):
        await client.generate({"1": {}})


async def test_http_client_skips_preview_image():
    history = {
        "pid-1": {
            "outputs": {
                "9": {
                    "images": [
                        {"filename": "preview.png", "type": "temp"},
                        {"filename": "final.png", "type": "output"},
                    ]
                }
            }
        }
    }
    http = _FakeHttp(history_sequence=[history])
    client = HttpComfyClient(_config(), http_factory=lambda: http)
    await client.generate({"1": {}})
    assert http.view_params[0]["filename"] == "final.png"


async def test_http_client_default_factory_imports_httpx(monkeypatch):
    captured = {}
    http = _FakeHttp(history_sequence=[_completed_history()])

    class FakeAsyncClient:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        async def __aenter__(self):
            return http

        async def __aexit__(self, *exc):
            return False

    module = types.ModuleType("httpx")
    module.AsyncClient = FakeAsyncClient
    monkeypatch.setitem(sys.modules, "httpx", module)

    client = HttpComfyClient(_config())
    assert await client.generate({"1": {}}) == b"PNG"
    assert captured["base_url"] == "http://comfy.local:8188"


# --- websocket helpers --------------------------------------------------------------


def test_ws_url_schemes():
    assert _ws_url("http://h:8188", "cid") == "ws://h:8188/ws?clientId=cid"
    assert _ws_url("https://h", "cid") == "wss://h/ws?clientId=cid"


def test_is_completion_matrix():
    def executing(**data):
        return {"type": "executing", "data": data}

    assert _is_completion({"type": "status"}, "pid-1") is False
    assert _is_completion(executing(node="3"), "pid-1") is False
    assert _is_completion(executing(node=None, prompt_id="x"), "pid-1") is False
    assert _is_completion(executing(node=None, prompt_id="pid-1"), "pid-1") is True


# --- websocket client ---------------------------------------------------------------


class _FakeConnection:
    def __init__(self, messages):
        self._messages = list(messages)
        self.closed = False

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._messages:
            raise StopAsyncIteration
        return self._messages.pop(0)

    async def close(self):
        self.closed = True


async def test_ws_client_happy_path():
    connection = _FakeConnection(
        [
            b"\x00binary-preview",  # non-str frame is skipped
            json.dumps({"type": "status"}),  # unrelated text frame
            json.dumps({"type": "executing", "data": {"node": None, "prompt_id": "pid-1"}}),
        ]
    )
    http = _FakeHttp(history_sequence=[_completed_history()])
    client = WebSocketComfyClient(
        _config(), ws_connect=lambda url: _ready(connection), http_factory=lambda: http
    )
    result = await client.generate({"1": {}}, output_node_id="9")
    assert result == b"PNG"
    assert connection.closed is True


async def _ready(value):
    return value


async def test_ws_client_falls_back_on_connect_failure():
    class _Fallback:
        async def generate(self, graph, *, output_node_id=""):
            return b"FALLBACK"

    def _boom(url):
        raise ConnectionRefusedError("nope")

    client = WebSocketComfyClient(_config(), ws_connect=_boom, fallback=_Fallback())
    assert await client.generate({"1": {}}) == b"FALLBACK"


async def test_ws_client_stream_ends_then_reads_history():
    # The socket closes before a completion frame; we still read the finished history.
    connection = _FakeConnection([json.dumps({"type": "status"})])
    http = _FakeHttp(history_sequence=[_completed_history()])
    client = WebSocketComfyClient(
        _config(), ws_connect=lambda url: _ready(connection), http_factory=lambda: http
    )
    assert await client.generate({"1": {}}, output_node_id="9") == b"PNG"
    assert connection.closed is True


async def test_ws_client_completed_without_image():
    connection = _FakeConnection(
        [json.dumps({"type": "executing", "data": {"node": None, "prompt_id": "pid-1"}})]
    )
    http = _FakeHttp(history_sequence=[_completed_history(with_image=False)])
    client = WebSocketComfyClient(
        _config(), ws_connect=lambda url: _ready(connection), http_factory=lambda: http
    )
    with pytest.raises(ComfyError, match="without an image"):
        await client.generate({"1": {}})
    assert connection.closed is True


# --- builder ------------------------------------------------------------------------


def test_build_comfy_client_http_when_websocket_disabled():
    client = build_comfy_client(_config(use_websocket=False))
    assert isinstance(client, HttpComfyClient)


def test_build_comfy_client_websocket_when_injected():
    client = build_comfy_client(_config(), ws_connect=lambda url: None)
    assert isinstance(client, WebSocketComfyClient)


def test_build_comfy_client_falls_back_when_websockets_missing(monkeypatch):
    monkeypatch.setitem(sys.modules, "websockets", None)
    client = build_comfy_client(_config())
    assert isinstance(client, HttpComfyClient)


def test_build_comfy_client_uses_websockets_when_available(monkeypatch):
    module = types.ModuleType("websockets")
    module.connect = lambda url: None
    monkeypatch.setitem(sys.modules, "websockets", module)
    client = build_comfy_client(_config())
    assert isinstance(client, WebSocketComfyClient)
