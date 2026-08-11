"""ComfyUI client: submit a workflow and fetch the resulting image (spec 27).

ComfyUI runs a workflow asynchronously: POST ``/prompt`` queues it and returns a
``prompt_id``; the result is then read from ``/history/{prompt_id}`` and the bytes from
``/view``. Two clients share that fetch logic: :class:`HttpComfyClient` polls ``/history``,
and :class:`WebSocketComfyClient` waits for the completion frame on ``/ws`` (falling back to
HTTP polling if the socket cannot be opened). Both take an injected ``http_factory`` /
``ws_connect`` so the network is fully mockable; the optional ``httpx``/``websockets`` imports
are lazy, behind the ``imagegen`` extra.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from types import TracebackType
from typing import Protocol, Self, cast

from pydantic import JsonValue, TypeAdapter

from .config import ComfyUIConfig

logger = logging.getLogger("bunnyland.imagegen")

DEFAULT_CLIENT_ID = "bunnyland"


class ComfyError(RuntimeError):
    """A ComfyUI request failed or produced no image."""


class ComfyTimeoutError(ComfyError):
    """ComfyUI did not finish the workflow within the configured timeout."""


class ComfyClient(Protocol):
    """Runs one workflow graph and returns the resulting media bytes."""

    async def generate(
        self, graph: dict[str, JsonValue], *, output_node_id: str = ""
    ) -> bytes: ...


class _HttpResponse(Protocol):
    content: bytes

    def raise_for_status(self) -> None: ...

    def json(self) -> object: ...


class _HttpClient(Protocol):
    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...

    async def post(self, url: str, *, json: object) -> _HttpResponse: ...

    async def get(
        self, url: str, *, params: dict[str, str] | None = None
    ) -> _HttpResponse: ...


class _WebSocketConnection(Protocol):
    def __aiter__(self) -> AsyncIterator[str | bytes]: ...

    async def close(self) -> None: ...


_HttpFactory = Callable[[], _HttpClient]
_Sleep = Callable[[float], Awaitable[None]]
_WebSocketConnect = Callable[[str], Awaitable[_WebSocketConnection]]
_JSON_OBJECT_ADAPTER = TypeAdapter(dict[str, JsonValue])


def _open_http(config: ComfyUIConfig, http_factory: _HttpFactory | None) -> _HttpClient:
    """Open an httpx-like async client, using the injected factory when provided."""
    if http_factory is not None:
        return http_factory()
    import httpx

    return cast(
        _HttpClient,
        httpx.AsyncClient(base_url=config.server_url, timeout=config.timeout_seconds),
    )


async def _submit(http: _HttpClient, graph: dict[str, JsonValue], client_id: str) -> str:
    response = await http.post("/prompt", json={"prompt": graph, "client_id": client_id})
    response.raise_for_status()
    payload = _JSON_OBJECT_ADAPTER.validate_python(response.json())
    prompt_id = payload.get("prompt_id")
    if not isinstance(prompt_id, str) or not prompt_id:
        raise ComfyError("comfyui response did not include a prompt id")
    return prompt_id


async def _history(http: _HttpClient, prompt_id: str) -> dict[str, JsonValue]:
    response = await http.get(f"/history/{prompt_id}")
    response.raise_for_status()
    return _JSON_OBJECT_ADAPTER.validate_python(response.json())


def _extract_media_ref(
    entry: dict[str, JsonValue], output_node_id: str
) -> dict[str, JsonValue] | None:
    """Find the first saved image or video in a completed history entry."""
    outputs = entry.get("outputs")
    if not isinstance(outputs, dict):
        return None
    node_ids = [output_node_id] if output_node_id else list(outputs)
    for node_id in node_ids:
        output = outputs.get(node_id)
        if not isinstance(output, dict):
            continue
        # VideoHelperSuite reports encoded clips under ``gifs`` while newer native ComfyUI
        # video nodes use ``videos``. Images retain their original ``images`` collection.
        for collection in ("images", "gifs", "videos"):
            media_refs = output.get(collection)
            if not isinstance(media_refs, list):
                continue
            for media_ref in media_refs:
                if not isinstance(media_ref, dict) or media_ref.get("type") == "temp":
                    continue
                if isinstance(media_ref.get("filename"), str):
                    return media_ref
    return None


async def _fetch_view(http: _HttpClient, media_ref: dict[str, JsonValue]) -> bytes:
    filename = media_ref.get("filename")
    if not isinstance(filename, str):
        raise ComfyError("comfyui output did not include a filename")
    subfolder = media_ref.get("subfolder")
    output_type = media_ref.get("type")
    params = {
        "filename": filename,
        "subfolder": subfolder if isinstance(subfolder, str) else "",
        "type": output_type if isinstance(output_type, str) else "output",
    }
    response = await http.get("/view", params=params)
    response.raise_for_status()
    return response.content


def _ws_url(server_url: str, client_id: str) -> str:
    base = server_url
    if base.startswith("https://"):
        base = "wss://" + base[len("https://") :]
    else:
        base = "ws://" + base.removeprefix("http://")
    return f"{base}/ws?clientId={client_id}"


def _is_completion(payload: dict[str, JsonValue], prompt_id: str) -> bool:
    """True when a ws frame signals our prompt has finished executing."""
    if payload.get("type") != "executing":
        return False
    data = payload.get("data")
    return (
        isinstance(data, dict)
        and data.get("node") is None
        and data.get("prompt_id") == prompt_id
    )


class HttpComfyClient:
    """Submits a workflow and polls ``/history`` until the image is ready."""

    def __init__(
        self,
        config: ComfyUIConfig,
        *,
        http_factory: _HttpFactory | None = None,
        client_id: str = DEFAULT_CLIENT_ID,
        sleep: _Sleep = asyncio.sleep,
    ) -> None:
        self._config = config
        self._http_factory = http_factory
        self._client_id = client_id
        self._sleep = sleep

    async def generate(
        self, graph: dict[str, JsonValue], *, output_node_id: str = ""
    ) -> bytes:
        config = self._config
        max_polls = max(1, int(config.timeout_seconds / config.poll_interval_seconds))
        async with _open_http(config, self._http_factory) as http:
            prompt_id = await _submit(http, graph, self._client_id)
            attempts = 0
            while True:
                history = await _history(http, prompt_id)
                entry = history.get(prompt_id)
                if isinstance(entry, dict):
                    media_ref = _extract_media_ref(entry, output_node_id)
                    if media_ref is None:
                        raise ComfyError("comfyui completed without an image or video")
                    return await _fetch_view(http, media_ref)
                attempts += 1
                if attempts >= max_polls:
                    raise ComfyTimeoutError(f"comfyui timed out after {attempts} polls")
                await self._sleep(config.poll_interval_seconds)


class WebSocketComfyClient:
    """Waits for the ComfyUI completion frame on a websocket, fetching the image over HTTP.

    If the socket cannot be opened it transparently falls back to ``HttpComfyClient``.
    """

    def __init__(
        self,
        config: ComfyUIConfig,
        *,
        ws_connect: _WebSocketConnect,
        http_factory: _HttpFactory | None = None,
        client_id: str = DEFAULT_CLIENT_ID,
        fallback: ComfyClient | None = None,
    ) -> None:
        self._config = config
        self._ws_connect = ws_connect
        self._http_factory = http_factory
        self._client_id = client_id
        self._fallback = fallback or HttpComfyClient(
            config, http_factory=http_factory, client_id=client_id
        )

    async def generate(
        self, graph: dict[str, JsonValue], *, output_node_id: str = ""
    ) -> bytes:
        config = self._config
        ws_url = _ws_url(config.server_url, self._client_id)
        try:
            connection = await self._ws_connect(ws_url)
        except Exception as exc:  # noqa: BLE001 - any connect failure falls back to HTTP
            logger.warning("comfyui websocket connect failed (%s); using HTTP polling", exc)
            return await self._fallback.generate(graph, output_node_id=output_node_id)
        try:
            async with _open_http(config, self._http_factory) as http:
                prompt_id = await _submit(http, graph, self._client_id)
                async for message in connection:
                    if not isinstance(message, str):
                        continue
                    payload = _JSON_OBJECT_ADAPTER.validate_python(json.loads(message))
                    if _is_completion(payload, prompt_id):
                        break
                history = await _history(http, prompt_id)
                entry = history.get(prompt_id)
                media_ref = (
                    _extract_media_ref(entry, output_node_id)
                    if isinstance(entry, dict)
                    else None
                )
                if media_ref is None:
                    raise ComfyError("comfyui completed without an image or video")
                return await _fetch_view(http, media_ref)
        finally:
            await connection.close()


def _import_ws_connect() -> _WebSocketConnect | None:
    try:
        import websockets
    except ImportError:
        return None
    return cast(_WebSocketConnect, websockets.connect)


def build_comfy_client(
    config: ComfyUIConfig,
    *,
    http_factory: _HttpFactory | None = None,
    ws_connect: _WebSocketConnect | None = None,
) -> ComfyClient:
    """Pick a client: websocket (with HTTP fallback) when enabled and available, else HTTP."""
    http = HttpComfyClient(config, http_factory=http_factory)
    if not config.use_websocket:
        return http
    if ws_connect is None:
        ws_connect = _import_ws_connect()
        if ws_connect is None:
            logger.warning("websockets not installed; using HTTP polling for ComfyUI")
            return http
    return WebSocketComfyClient(
        config, ws_connect=ws_connect, http_factory=http_factory, fallback=http
    )


__all__ = [
    "DEFAULT_CLIENT_ID",
    "ComfyClient",
    "ComfyError",
    "ComfyTimeoutError",
    "HttpComfyClient",
    "WebSocketComfyClient",
    "build_comfy_client",
]
