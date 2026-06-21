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
from typing import Any, Protocol

from .config import ImageGenConfig

logger = logging.getLogger("bunnyland.imagegen")

DEFAULT_CLIENT_ID = "bunnyland"


class ComfyError(RuntimeError):
    """A ComfyUI request failed or produced no image."""


class ComfyTimeoutError(ComfyError):
    """ComfyUI did not finish the workflow within the configured timeout."""


class ComfyClient(Protocol):
    """Runs one workflow graph and returns the resulting image bytes."""

    async def generate(self, graph: dict[str, Any], *, output_node_id: str = "") -> bytes: ...


def _open_http(config: ImageGenConfig, http_factory: Any) -> Any:
    """Open an httpx-like async client, using the injected factory when provided."""
    if http_factory is not None:
        return http_factory()
    import httpx

    return httpx.AsyncClient(base_url=config.server_url, timeout=config.timeout_seconds)


async def _submit(http: Any, graph: dict[str, Any], client_id: str) -> str:
    response = await http.post("/prompt", json={"prompt": graph, "client_id": client_id})
    response.raise_for_status()
    return response.json()["prompt_id"]


async def _history(http: Any, prompt_id: str) -> dict[str, Any]:
    response = await http.get(f"/history/{prompt_id}")
    response.raise_for_status()
    return response.json()


def _extract_image_ref(entry: dict[str, Any], output_node_id: str) -> dict[str, Any] | None:
    """Find the first saved (non-preview) image in a completed history entry."""
    outputs = entry.get("outputs", {})
    node_ids = [output_node_id] if output_node_id else list(outputs)
    for node_id in node_ids:
        for image in outputs.get(node_id, {}).get("images", []):
            if image.get("type") == "temp":
                continue
            return image
    return None


async def _fetch_view(http: Any, image: dict[str, Any]) -> bytes:
    params = {
        "filename": image["filename"],
        "subfolder": image.get("subfolder", ""),
        "type": image.get("type", "output"),
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


def _is_completion(payload: dict[str, Any], prompt_id: str) -> bool:
    """True when a ws frame signals our prompt has finished executing."""
    if payload.get("type") != "executing":
        return False
    data = payload.get("data") or {}
    return data.get("node") is None and data.get("prompt_id") == prompt_id


class HttpComfyClient:
    """Submits a workflow and polls ``/history`` until the image is ready."""

    def __init__(
        self,
        config: ImageGenConfig,
        *,
        http_factory: Any = None,
        client_id: str = DEFAULT_CLIENT_ID,
        sleep: Any = asyncio.sleep,
    ) -> None:
        self._config = config
        self._http_factory = http_factory
        self._client_id = client_id
        self._sleep = sleep

    async def generate(self, graph: dict[str, Any], *, output_node_id: str = "") -> bytes:
        config = self._config
        max_polls = max(1, int(config.timeout_seconds / config.poll_interval_seconds))
        async with _open_http(config, self._http_factory) as http:
            prompt_id = await _submit(http, graph, self._client_id)
            attempts = 0
            while True:
                history = await _history(http, prompt_id)
                entry = history.get(prompt_id)
                if entry is not None:
                    image = _extract_image_ref(entry, output_node_id)
                    if image is None:
                        raise ComfyError("comfyui completed without an image")
                    return await _fetch_view(http, image)
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
        config: ImageGenConfig,
        *,
        ws_connect: Any,
        http_factory: Any = None,
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

    async def generate(self, graph: dict[str, Any], *, output_node_id: str = "") -> bytes:
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
                    if _is_completion(json.loads(message), prompt_id):
                        break
                history = await _history(http, prompt_id)
                entry = history.get(prompt_id)
                image = _extract_image_ref(entry, output_node_id) if entry is not None else None
                if image is None:
                    raise ComfyError("comfyui completed without an image")
                return await _fetch_view(http, image)
        finally:
            await connection.close()


def _import_ws_connect() -> Any:
    try:
        import websockets
    except ImportError:
        return None
    return websockets.connect


def build_comfy_client(
    config: ImageGenConfig,
    *,
    http_factory: Any = None,
    ws_connect: Any = None,
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
